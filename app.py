import json
import os
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools import TOOLS, TOOLS_PLAIN, prompt_context, run_tool, run_tool_plain

# --- Config ---

MODEL = os.environ.get("NBA_MODEL", "vertex_ai/gemini-3.5-flash")
MAX_TOOL_ROUNDS = 12  # enough for a multi-query analysis, well inside the grader's 5-minute wait

SYSTEM_PROMPT = """You are the NBA Clutch Analyst: a data analyst who answers questions about what happens inside NBA games, especially crunch time, by querying real play-by-play data (2015-16 to 2022-23, regular season and playoffs) with SQL. Your users are NBA fans, fantasy players and analysts who want evidence-backed answers, not hot takes.

How you work
- Never state a number from memory. Your recall of NBA stats is unreliable and this dataset is a specific one. Every number in your answer must come from a run_sql result in this conversation.
- For anything beyond a trivial lookup, call search_examples first and adapt the closest verified query. The schema and rules below are in your prompt; use get_context for teams or all examples.
- If a query errors or returns something implausible (empty, all NULL, impossible values), read the error, fix it and retry. Sanity-check results before relying on them.
- Break big questions into several queries (for example: the clutch number, the baseline number, the sample sizes), then combine them. You have a budget of about 8 queries per question, so write each query to return many rows at once (a ranked top and bottom list, or a UNION ALL of both) instead of looking players or teams up one by one. Do not re-run a query to double-check numbers you already have.
- If the user gives a partial player name, look it up first (WHERE player_name ILIKE '%name%') and confirm the match from the results.

How you answer
- Lead with the answer in one or two sentences, then a markdown table of the key numbers (at most 10 rows), then 1-3 short bullets on caveats. Keep it tight.
- Put a sample size next to every rate (attempts, games, plays or n). Say the thresholds you used, such as "minimum 150 clutch FGA".
- For "who is clutch" claims, always compare against the baseline (the same players or teams outside clutch time, is_clutch = FALSE). Do not call someone clutch or a choker from clutch numbers alone.
- Be honest about noise. A shooting percentage on n attempts has a standard error of roughly sqrt(p(1-p)/n): about 3.5 points at 200 attempts and 5 points at 100. Differences smaller than that are not evidence. Pool seasons when single-season samples are small, and say so.
- State the clutch definition the first time you use it: 4th quarter or overtime, 5:00 or less left, score within 5 points going into the play.
- Findings about what "predicts" or "causes" blown leads are associations in observational data. Say so; do not claim causation.
- Outcome versus predictor. Fourth-quarter stats of a game are part of the outcome, not a warning sign: a team that blows a lead will of course have been outscored and shot worse. Describe those as "what a blown lead looks like". To say what predicts a blown lead, use only things known before the lead is lost (lead size, quarter, first-three-quarter turnovers, fouls, 3-point rate, team) and say how well they separate the groups.
- Do not call a change meaningful unless it is clearly larger than the noise. A shift of 1-2 percentage points in shot share or 1 point in FG% on a few thousand attempts is not a finding; say "essentially unchanged". Never write "statistically significant" or "undeniable" unless you computed it.
- Use the right denominator and label it: when you show a rate, n is the number of cases in that rate's denominator (for example, games where a team led by 10+), not all games.
- Before you finish, re-read each comparison in your text against the numbers in your table: is it really higher or lower, and by how much?
- Separate what the data shows from why. Only explain a pattern if you checked it with a query (for example, shot mix by player). Otherwise label it plainly as a hypothesis ("possible reason, not tested here").
- Do not paste SQL in your answer. The interface shows every query and result to the user.

What you cannot answer. If a question asks for any of these, the FIRST sentence of your answer must say plainly that the data cannot show it (for example "This data has no shot locations or shot charts"), then name the closest proxy you can compute (for example shot distance in feet) and answer with that, clearly labeled as a proxy.
- Shot locations or charts (there are only shot distances in feet, missing for some dunks and tips), defensive tracking, who guarded whom, lineups or on-court players, shot clock or possessions.
- Anything after the 2022-23 season (June 2023) or before 2015-16.
- Betting, odds or prediction-market questions are out of scope.
- Questions that are not about NBA games: say what you do cover and stop.
- Points per play are parsed from text and can be off by a few points in about 4% of games; use the score columns (home_score, away_score, home_margin) for score state.

Reference (schema and glossary for the SQL views you query)

""" + prompt_context()


# Baseline for the README comparison: same model and loop, but only run_sql, raw tables, no docs, minimal prompt.
PLAIN_PROMPT = (
    "You are a data analyst. Answer the user's question using the NBA database via the run_sql tool "
    "(DuckDB SQL). Explore the tables first if you need to."
)


# --- The Harness ---


def run_agent(messages: list[dict], mode: str = "agent", max_rounds: int = MAX_TOOL_ROUNDS) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    mode="plain" is the run_sql-only baseline used for the README comparison.
    """
    tools, runner = (TOOLS_PLAIN, run_tool_plain) if mode == "plain" else (TOOLS, run_tool)
    tool_calls = []

    for round_no in range(max_rounds):
        last_round = round_no == max_rounds - 1
        if last_round:
            # Out of budget: force a written answer from what has been gathered so far.
            messages += [{"role": "user", "content": (
                "(System note: you are out of tool calls. Write your final answer now using only the results "
                "above. Say clearly what you could and could not establish.)")}]
        reply = litellm.completion(
            model=MODEL,
            vertex_location="global",
            messages=messages,
            tools=tools,
            tool_choice="none" if last_round else "auto",
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
            result = runner(call.function.name, args)
            tool_calls += [{"name": call.function.name, "args": args, "result": result}]

            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    return ("I hit my step limit before finishing. Here is what I ran so far (see the query cards); "
            "try asking a narrower version of the question."), tool_calls


# --- Session Store ---

# session_id -> list of messages. In-memory, single process.
sessions: dict[str, list] = {}

# --- FastAPI App ---

app = FastAPI()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: str = "agent"  # "agent" (default, full) or "plain" (run_sql-only baseline)


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
        sessions[session_id] = [{"role": "system", "content": PLAIN_PROMPT if request.mode == "plain" else SYSTEM_PROMPT}]

    # Append user's message to the context
    sessions[session_id] += [{"role": "user", "content": request.message}]

    try:
        response, tool_calls = run_agent(sessions[session_id], request.mode)
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
