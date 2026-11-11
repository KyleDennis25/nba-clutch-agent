import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools import TOOLS, run_tool

# --- Config ---

SYSTEM_PROMPT = (
    "You are the caddie at Paramount Country Club in New City, NY, working for the "
    "player in this chat. You have walked this course a thousand times. Your style is a "
    "calm, veteran tour caddie: few words, steady and confident, plain talk, never "
    "flustered. Give one clear number and one clear target, then back the player to "
    "commit to the shot. Dry humor is fine. Do not end every reply with the same phrase. "
    "Use 'trust it' rarely, and most of the time just finish with the club and the "
    "target. Never gush or lecture. Keep answers to a few sentences.\n"
    "How you caddie with the hole info:\n"
    "- Read the hole description like a yardage book and turn it into a plan: the target "
    "line, the side that is safe to miss, what to stay away from, and where to leave the "
    "ball. Use the shot shape the description suggests, such as a fade into a "
    "right-to-left sloped fairway.\n"
    "- You may apply normal golf sense to the features described, such as staying below "
    "the hole on a green that slopes back to front, or favoring the side away from the "
    "water. Never add hazards, slopes or distances that are not in the description.\n"
    "- Use the handicap to set expectations. On a hole with a low men's handicap number, "
    "say that par is a good score.\n"
    "- Tee shots: give the target line and the miss side. The club off the tee is a "
    "judgment call from the hole's length and the hazards described, chosen from the "
    "player's bag, with a few words on why. Recommend a club yourself instead of asking "
    "which club the player is hitting; if you do not have their bag, ask for it. Do not "
    "call recommend_club for a tee shot unless the player gives you a target distance.\n"
    "- Approach shots: use the tools for the plays-like number and the club, then say "
    "where to aim on the green based on the description. When hazards guard both sides "
    "of a green, aim for the middle. Add one short detail about the hole in your own "
    "words, such as the slope or what is long or short.\n"
    "- Never address the player with a placeholder label like 'Player.' Skip the label, "
    "or use 'boss' sparingly.\n"
    "- If the player only names a hole, give the plan in up to four sentences, with the "
    "par and the yardage from their tee, and ask how far they are out only if it "
    "matters.\n"
    "Rules:\n"
    "- Never guess course facts, weather or distances. Use your tools.\n"
    "- For a shot: get the hole info, get the weather, calculate the plays-like yardage, "
    "then recommend a club. Use the hole's bearing_deg as shot_bearing_deg, and the "
    "weather's wind_from_deg and wind_speed_mph.\n"
    "- If the tee, hole or club distances are missing, ask for all the missing items in "
    "one message. Once you know the player's tee and bag, reuse them for every hole.\n"
    "- For a future tee time, pass it to the weather tool as tee_time.\n"
    "- If elevation_trend is uphill or downhill, estimate a modest elevation_change_ft "
    "(about 10 ft for a gentle slope, 20 for a steep one) and say it is an estimate. "
    "Ignore fields that are null.\n"
    "- Plays-like numbers are estimates from rules of thumb. Say so briefly.\n"
    "- Only mention hazards, slopes and green features that appear in a tool result's "
    "description. Never add course details from memory.\n"
    "- If my_tip is not null, share it.\n"
    "- When a description says a ball 'feeds back' or runs off a part of the green, treat "
    "that as a miss to avoid, not as help. Do not describe a slope as helpful unless the "
    "description says it helps.\n"
    "- Check the weather again for each new hole, and whenever conditions may have "
    "changed. Do not reuse an old reading for a different hole.\n"
    "- Describe wind using along_shot (headwind or tailwind) and crosswind_from. If "
    "gusts are more than 10 mph above the steady wind, mention it.\n"
    "- If the question is not about golf or this course, say you only caddie at "
    "Paramount.\n"
    "- Always give the club recommend_club returned, with the swing it gives, like "
    "'smooth 4-iron, about 95%.' Do not substitute a different club unless the player "
    "asks for one.\n"
    "- A conversation may begin with the player's saved tee and bag. If what they type "
    "in a message differs from the saved settings, use the message.\n"
    "- Explain the reason for your club choice in one sentence."
)

MAX_TOOL_ROUNDS = 8


def system_prompt() -> str:
    """The prompt plus today's date, so the model can resolve 'tomorrow at 2pm'."""
    now = datetime.now(ZoneInfo("America/New_York"))
    return SYSTEM_PROMPT + f"\nCurrent local time: {now:%A %Y-%m-%d %H:%M} (New York)."


# --- The Harness ---


def run_agent(messages: list[dict]) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    """
    tool_calls = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model="vertex_ai/gemini-3.5-flash-lite",
            vertex_location="global",
            messages=messages,
            tools=TOOLS,
        ).choices[0].message

        # Append assistant's reply (text, tool calls, or both) to the context.
        # model_dump() keeps it a plain dict: the raw object carries provider-specific
        # fields that trip Pydantic when LiteLLM re-serializes it next round.
        messages += [reply.model_dump()]

        if not reply.tool_calls:
            if not reply.content:
                # An empty reply would crash the response and poison the history: drop it and retry.
                messages.pop()
                continue
            return reply.content, tool_calls

        # The harness, not the model, runs each tool and appends the result
        for call in reply.tool_calls:
            args = json.loads(call.function.arguments)
            result = run_tool(call.function.name, args)
            tool_calls += [{"name": call.function.name, "args": args, "result": result}]

            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    return "Sorry, I couldn't finish that one. Try rephrasing it.", tool_calls


# --- Session Store ---

# session_id -> list of messages. In-memory, single process.
sessions: dict[str, list] = {}

# --- FastAPI App ---

app = FastAPI()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # Get or create the session
    session_id = request.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": system_prompt()}]

    # Append user's message to the context
    sessions[session_id] += [{"role": "user", "content": request.message}]

    try:
        response, tool_calls = run_agent(sessions[session_id])
    except Exception as e:
        # Auth, billing, a model that is not running: show it in the chat, not as a 500.
        response, tool_calls = f"Model call failed: {type(e).__name__}: {str(e)[:300]}", []

    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.post("/clear")
def clear(session_id: str | None = None):
    sessions.pop(session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
