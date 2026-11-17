"""Run questions through the full agent and the plain run_sql-only baseline; save traces for the README.
Run: uv run python eval/compare.py [question_id ...]      (no args = all)
Traces: eval/traces/<id>_<mode>.json  ({question, mode, answer, seconds, tool_calls})
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import litellm  # noqa: E402
import app  # noqa: E402

OUT = Path(__file__).parent / "traces"
OUT.mkdir(exist_ok=True)

CLUTCH = ("Clutch time means the last 5 minutes of the 4th quarter or any overtime, when the score is within "
          "5 points. ")

QUESTIONS = {
    "clutch_efg": CLUTCH + "Among players with at least 150 clutch field goal attempts from 2015-16 to 2022-23 "
                  "(regular season and playoffs), who has the highest clutch effective field goal percentage, "
                  "and how many attempts did they take?",
    "comebacks_10": "In how many regular-season games from 2015-16 to 2022-23 did the winning team trail by 10 "
                    "or more points at some point in the game, out of how many games with play-by-play?",
    "q3_lead_hold": "When a team led by 10 or more points at the end of the 3rd quarter, how often did it win? "
                    "Use all games from 2015-16 to 2022-23 (regular season and playoffs).",
    "team_clutch_net": CLUTCH + "Which team had the best clutch net points (points scored minus points allowed "
                       "during clutch plays) in the 2022-23 regular season?",
    "biggest_run": "What was the biggest unanswered scoring run (consecutive points by one team with no points "
                   "from the opponent) by a team in a single 2022-23 regular season game, and which game was it?",
    "clutch_ft": CLUTCH + "Is free-throw shooting any different in clutch time than the rest of the game, "
                 "league-wide, from 2015-16 to 2022-23?",
    "shot_court": "Where on the court do teams take their clutch-time shots, and which zone is most efficient?",
    "defenders": "Which players are the best clutch-time defenders, meaning they hold the opponents they guard to "
                 "the lowest field goal percentage?",
    "out_of_range": "How did the Boston Celtics perform in clutch time in the 2023-24 season?",
    "final_minute": CLUTCH + "Who took the most field goal attempts in the final 60 seconds of clutch situations "
                    "from 2018-19 to 2022-23 (regular season and playoffs), and what was their FG%?",
    "blown15_2022": "Which team lost the most regular-season games in 2022-23 after leading by 15 or more points "
                    "at some point in the game, and how many?",
}


def run(qid: str, mode: str):
    q = QUESTIONS[qid]
    t = time.time()
    try:
        if mode == "bare":
            # Same model, no tools and no system prompt: what it says from memory alone.
            reply = litellm.completion(model=app.MODEL, vertex_location="global", num_retries=5,
                                       messages=[{"role": "user", "content": q}]).choices[0].message
            answer, calls = reply.content or "", []
        else:
            system = app.PLAIN_PROMPT if mode == "plain" else app.SYSTEM_PROMPT
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": q}]
            # The baseline gets 30 rounds (vs 12 for the agent) so a failure is not just a step-budget artifact.
            answer, calls = app.run_agent(msgs, mode, max_rounds=30 if mode == "plain" else app.MAX_TOOL_ROUNDS)
    except Exception as e:  # keep going; record the failure
        answer, calls = f"ERROR {type(e).__name__}: {e}", []
    rec = {"id": qid, "question": q, "mode": mode, "answer": answer,
           "seconds": round(time.time() - t), "tool_calls": calls}
    (OUT / f"{qid}_{mode}.json").write_text(json.dumps(rec, indent=1, default=str))
    return rec


if __name__ == "__main__":
    # Usage: compare.py [--modes bare,plain,agent] [question_id ...]
    args = sys.argv[1:]
    modes = ("plain", "agent")
    if args and args[0] == "--modes":
        modes, args = tuple(args[1].split(",")), args[2:]
    ids = args or list(QUESTIONS)
    jobs = [(i, m) for i in ids for m in modes]
    with ThreadPoolExecutor(max_workers=3) as ex:  # small pool: Vertex returns 429 under bursts
        for rec in ex.map(lambda j: run(*j), jobs):
            print(f"done {rec['id']:16s} {rec['mode']:5s} {rec['seconds']:4d}s {len(rec['tool_calls']):2d} calls")
