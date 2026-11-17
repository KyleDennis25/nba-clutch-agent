# NBA Clutch Agent

A Text2SQL data-exploration agent for NBA play-by-play data. Columbia MSDS Agentic AI, Project 2 · Author: kd3070

**Live demo:** https://nba-clutch-agent-425887394975.us-east1.run.app (Columbia sign-in required)

## What it explores and who it is for

The agent answers questions about what happens *inside* NBA games, with a focus on crunch time:

1. **Clutch performance.** Who shoots well in clutch time, which teams win close games, and how much of that is real versus noise.
2. **Comebacks and blown leads.** How often double-digit leads are lost, and what is known before a lead is lost.
3. **Late-game shot choices.** How shot mix and efficiency change in the last minutes of close games.

It is built for **NBA fans, fantasy players and analysts** who want answers backed by numbers and sample sizes instead of hot takes. It writes SQL over about 4.3 million play-by-play events, shows every query it ran, compares against a non-clutch baseline, and says so when the data cannot answer a question (for example shot locations, or anything after June 2023). Betting and odds questions are out of scope on purpose.

**Clutch time** (used everywhere): 4th quarter or overtime, 5:00 or less left, score within 5 points going into the play.

## Data

- **Source:** the Kaggle dataset [wyattowalsh/basketball](https://www.kaggle.com/datasets/wyattowalsh/basketball) ("NBA Database"), a SQLite file built from stats.nba.com.
- **Coverage used:** 2015-16 to 2022-23, regular season and playoffs. 10,187 games in the game table, of which 9,276 have play-by-play (4,313,409 events). About 80 MB as Parquet, committed in `data/`, so deploying needs no download.
- **Tables:** `play_by_play` (one row per event), `game`, `other_stats` (box-score extras such as largest lead), `line_score`, `officials`, `team`, `team_history`, `player`.

### How to load it

```
# 1. Download nba.sqlite from the Kaggle link above into data/raw/nba.sqlite (2.2 GB, git-ignored)
uv run python build/prep_data.py        # SQLite -> data/*.parquet (2015-16 .. 2022-23)
uv run python build/build_context.py    # generates context/ (schema, glossary, teams, verified examples)
```

At run time the app uses only the committed Parquet files and `context/`. DuckDB reads them in memory, read-only.

### Conventions and quirks the agent has to know

- The raw `score` column is `VISITOR - HOME`, `scoremargin` is `HOME - VISITOR` (with the text `TIE`), and both are filled in only on scoring events. The `plays` view fixes this with a running maximum of the score and gives `home_score`, `away_score`, `home_margin`. Reconstructed final scores match the official score in all 9,276 games.
- The clock counts down (`M:SS`). Quarters are 12:00, overtimes 5:00.
- `season_id` is a type digit plus the start year (`22022` is the 2022-23 regular season, `42022` its playoffs).
- Event codes are decoded to names (`MADE_SHOT`, `MISSED_SHOT`, `FREE_THROW`, `TURNOVER`, ...).
- Points per play are parsed from the text description and differ from the official score in about 4% of games, so score state always uses the score columns.

### Limits (the agent is told these and is expected to say so)

- No shot x/y locations (only distance in feet, missing for some dunks and tips), no tracking, defenders, lineups, shot clock or possessions.
- Nothing after June 2023 or before 2015-16. 2019-20 and 2020-21 are shortened or odd seasons, so rates are safer than counts.
- Small samples: a single player's clutch FGA is usually under 800 over eight seasons. Differences of a few points are noise, and the agent is prompted to say so.
- Causal questions are answered as associations only.

## How it works

### Offline build (`build/`)

| Step | What it does |
|---|---|
| `prep_data.py` | Exports the 8 seasons from SQLite to per-season Parquet, drops unused columns, keeps only matching games in the side tables. |
| `context/views.sql` | Helper views (saved queries, no copied data): `plays` (parsed clock, running score, margin before each play, decoded event type, acting team, shot kind and distance, `is_clutch`), `clutch_plays`, `games`, `game_swings` (biggest deficit of the eventual winner, comeback flags, lead changes), `player_shooting`, `team_game_clutch`, plus passthrough views. |
| `build_context.py` | Generates `context/schema.md`, `glossary.md` (decoded values, conventions, limits, with numbers computed from the data) and `teams.md`. |
| `build/examples.py` | 14 verified question → SQL examples. The build **executes every example and aborts if one errors or returns no rows**, so the agent never sees a broken example. |

### Agent (`app.py`, `tools.py`)

- **Model:** Gemini (`vertex_ai/gemini-3.5-flash`) through LiteLLM on Vertex AI.
- **Tools:** `run_sql` (one read-only SELECT over the helper views, 200 rows max, 60 s timeout, a blocklist for file and system functions), `get_context` (schema, glossary, teams, examples) and `search_examples` (top 3 verified examples by keyword overlap).
- **Loop:** at most 12 tool rounds, then a forced final answer. Failed model calls retry automatically (Vertex returns 429 under bursts).
- **Prompt rules** (the "analyst discipline" that the plain agent lacks): never state a number from memory, sample size next to every rate, always compare against the non-clutch baseline, say when a gap is within noise, separate outcome from predictor, label untested explanations as hypotheses, and put the "this data cannot answer that" statement in the first sentence.
- **API:** `POST /chat` returns `{response, session_id, tool_calls}` where `tool_calls` lists every tool call with its arguments and full result. Sessions are in memory.
- **Frontend (`index.html`):** a scoreboard-style page that explains the project, offers example questions (including two that cannot be answered), renders answers as tables and a bar chart, and shows each SQL query and its result in an expandable card.
- **Deploy:** Google Cloud Run (us-east1) with continuous deploy from this repo's `main` branch (buildpacks plus `Procfile`), 4 GiB memory, 900 s request timeout, max one instance, IAP authentication.

## Sample queries

For each query, the right column is the live agent. The left column is **the same model with no tools and no system prompt**. Full traces are in [`eval/traces/`](eval/traces/) (`<id>_bare.json` and `<id>_agent.json`).

### 1. Highest clutch effective FG% (minimum 150 clutch FGA, 2015-16 to 2022-23)

- **Source tables:** `play_by_play` (clutch shots), `player` (names), via the `plays` and `player_shooting` views.
- **Expected answer:** Rudy Gobert, 68.8% eFG% on 189 clutch attempts (66.0% outside clutch time).

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "Nikola Jokić ... ~61.5% ... 713 attempts." (invented; Jokić has 522 clutch FGA and 50.1% in this data) | Rudy Gobert, **68.8% on 189 FGA**, vs 66.0% non-clutch (+2.8, within noise). Table of the next nine players with sample sizes, shot distance, and the league clutch average (48.6%). Notes that the leaders are rim-finishers and that a +7.9 point gap for one player on 200 shots is within noise. |

### 2. How often a team with a 10+ point lead after three quarters wins (all games, 2015-16 to 2022-23)

- **Source tables:** `play_by_play` (period-3 end margin), `game` (winner), via `games` and `plays`.
- **Expected answer:** 95.2%, 4,172 of 4,381 games.

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "approximately **92.7%** ... roughly **3,150 wins and 250 losses** out of approximately 3,400 occurrences", plus a story about the "3-point revolution" lowering this from 95-96% before 2015. | **95.2% (4,172 of 4,381)**, split by lead size: 10-14 points 90.5% (1,781 games), 15-19 points 96.9% (1,210), 20+ points 99.9% (1,390). Names the only two 20+ comebacks (Toronto over Dallas, 2019-12-22; Atlanta over Cleveland, 2017-04-09). |

### 3. Best clutch net points, 2022-23 regular season

- **Source tables:** `play_by_play`, `game`, via `team_game_clutch`.
- **Expected answer:** Miami Heat, +70 net points over 49 games with clutch time (479 for, 409 against).

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "The **Milwaukee Bucks** ... 28-13, 334 points scored, 255 allowed, **+79**." (invented) | **Miami, +70 over 49 clutch games** (479 for, 409 against). Next: Philadelphia +60, New Orleans +55, Sacramento +48. Also notes that New Orleans leads per game (+1.72 over 32 games) and that points are parsed from text and can differ from box scores in about 4% of games. |

The model alone gives confident, specific and wrong numbers in all three cases (and different wrong numbers each run). It has no way to look at the data.

## Where the plain `run_sql` agent fails

The "plain agent" is the same model and loop with **only** `run_sql` over the raw tables: no schema docs, no decoded values, no helper views, no verified examples, and a one-line prompt. It was given 30 tool rounds (vs 12 for the full agent) so a failure is not just a step budget. Traces: [`eval/traces/`](eval/traces/).

### Failure 1: "Which team lost the most 2022-23 regular-season games after leading by 15 or more points?"

- **Plain agent** ([trace](eval/traces/blown15_2022_plain.json)): 29 queries, no answer. It discovered that `other_stats.largest_lead_home/away` do not line up with the home and away teams in `game`, started rebuilding leads from `scoremargin` (a text column that is empty on non-scoring plays), and ended with "What We Could Not Establish" and an unexecuted query. (In an earlier run of the same setup it guessed "Dallas, 11" from memory instead.)
- **NBA Clutch Agent** ([trace](eval/traces/blown15_2022_agent.json)): 5 queries, correct. **Atlanta and Washington tied with 8 blown leads of 15+** (Washington 8 of 28 leads, Atlanta 8 of 35), and the league baseline: 116 blown of 789 such leads (14.7%). It used the pre-built `game_swings` view, which already handles score smoothing and who the eventual winner was.
- **Why:** the helper views and decoded conventions turn a 29-query exploration into a 5-query answer.

### Failure 2: "How did the Boston Celtics perform in clutch time in the 2023-24 season?"

- **Plain agent** ([trace](eval/traces/out_of_range_plain.json)): 22 queries. It noticed the data ends in June 2023, then wrote a section headed "External Data" with a **fabricated** 2023-24 line: "21-12 (.636) ... clutch net rating +14.3 ... 6-0 in the playoffs", with game details from the Pacers series. None of it comes from the database.
- **NBA Clutch Agent** ([trace](eval/traces/out_of_range_agent.json)): 10 queries. Its **first sentence** says "This dataset does not include the 2023-24 season", then it answers with the 2022-23 Celtics, clearly labelled as a proxy (clutch eFG% 49.2% on 239 FGA in the regular season, 22-11 in clutch games), with sample sizes and a noise caveat.
- **Why:** the system prompt and glossary state the data limits and require the "cannot answer" statement first. The plain agent has nothing telling it not to fill the gap from memory.

## Honest limits of the agent

- Answers vary between runs (LLM sampling). The prompt reduces, but does not eliminate, overclaiming. For example an answer may still call a +7.9 point gap a "rise" before noting it is within noise.
- Points-per-play are parsed from text (about 4% of games differ from official totals), so score-state questions use the score columns.
- Answers take 15-90 seconds. A shared Vertex quota can return 429s under bursts; the agent retries.
- Nothing is cached between sessions; sessions live in memory on one instance.

## Run locally and deploy

```
uv sync
gcloud auth application-default login      # Vertex AI access (project ieor-4570-f26-kd3070)
uv run python app.py                       # http://127.0.0.1:8000
```

Re-run the comparison traces (needs the same credentials):

```
uv run python eval/compare.py --modes bare,agent clutch_efg q3_lead_hold team_clutch_net
uv run python eval/compare.py --modes plain,agent blown15_2022 out_of_range
```

Deploy: Cloud Run service `nba-clutch-agent` is connected to this GitHub repo (branch `main`, buildpacks, `Procfile`: `web: uvicorn app:app --host 0.0.0.0 --port $PORT`). Every push to `main` builds and deploys a new revision. Settings: 4 GiB memory, 2 CPU, 900 s request timeout, max 1 instance, `DUCKDB_MEMORY=3GB`, IAP.

## Repo layout

```
app.py              FastAPI app, agent loop, system prompt, /chat
tools.py            run_sql, get_context, search_examples (+ plain baseline tools)
index.html          frontend
build/              offline build: prep_data.py, build_context.py, examples.py
context/            generated schema/glossary/teams/examples + views.sql
data/               Parquet files (committed)
eval/               compare.py and saved traces
Procfile, pyproject.toml, uv.lock, submission.json
```
