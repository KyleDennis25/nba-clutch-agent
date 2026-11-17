# NBA Clutch Agent

A Text2SQL agent that explores NBA play-by-play data, with a focus on crunch time. Columbia MSDS Agentic AI, Project 2. Author: kd3070.

**Live demo:** https://nba-clutch-agent-425887394975.us-east1.run.app (Columbia sign-in required)

## What it does and who it is for

Ask what happens inside NBA games and the agent writes SQL over about 4.3 million play-by-play events, shows every query it ran, and answers with numbers and sample sizes. Three themes:

1. **Clutch performance:** who shoots well late in close games, which teams win them, and how much is real versus noise.
2. **Comebacks and blown leads:** how often big leads are lost.
3. **Late-game shot choices:** how shot mix and efficiency change in crunch time.

**Target user:** NBA fans, fantasy players and analysts who want evidence instead of hot takes. The agent compares every clutch number against a non-clutch baseline, flags differences that are within noise, and says so when the data cannot answer (for example shot locations, or any game after June 2023). Betting questions are out of scope on purpose.

**Clutch time** (used everywhere): 4th quarter or overtime, 5:00 or less left, score within 5 points.

**Why the model needs the data:** play-by-play aggregates are not something a language model remembers. In all three sample queries below, the same model with no tools gave confident, specific, wrong numbers.

## Data

- **Source:** Kaggle [wyattowalsh/basketball](https://www.kaggle.com/datasets/wyattowalsh/basketball), a SQLite database built from stats.nba.com.
- **Used:** 2015-16 to 2022-23, regular season and playoffs. 10,187 games, 9,276 of them with play-by-play (4,313,409 events). Stored as 76 MB of Parquet in `data/` (committed, so the deploy ships its data).
- **Tables:** `play_by_play`, `game`, `other_stats`, `line_score`, `officials`, `team`, `team_history`, `player`.

**How to load it:**

```
# download nba.sqlite from the Kaggle link into data/raw/nba.sqlite (2.2 GB, git-ignored)
uv run python build/prep_data.py        # SQLite -> data/*.parquet
uv run python build/build_context.py    # generates context/ (schema, glossary, teams, verified examples)
```

**Quirks the agent has to know** (all documented in `context/glossary.md`): the raw `score` column is `VISITOR - HOME` and only filled on scoring plays, `scoremargin` is `HOME - VISITOR` or the text `TIE`, the clock counts down, and `season_id` is a type digit plus start year (`22022` is the 2022-23 regular season).

**Limits:** no shot locations (only distance in feet), tracking, lineups or shot clock. Nothing after June 2023. Points per play are parsed from text and differ from official totals in about 4% of games, so score state uses the score columns.

## How it works

**Offline build** (`build/`, output in `context/`):

| Step | Output |
|---|---|
| `prep_data.py` | Per-season Parquet files. |
| `context/views.sql` | Helper views (saved queries, no copied data): `plays` (parsed clock, running score, margin before each play, decoded event type, shot kind and distance, `is_clutch`), `games`, `game_swings` (biggest comeback of each winner), `player_shooting`, `team_game_clutch`. |
| `build_context.py` | `schema.md`, `glossary.md` (decoded values and limits, with numbers computed from the data), `teams.md`. |
| `build/examples.py` | 14 verified question to SQL examples. The build **runs every example and fails if one errors or returns no rows**. |

**Agent** (`app.py`, `tools.py`): Gemini (`gemini-3.5-flash`) via LiteLLM on Vertex AI, max 12 tool rounds then a forced final answer. Tools: `run_sql` (one read-only SELECT, 200 rows, 60 s timeout), `get_context` (schema, glossary, teams, examples) and `search_examples` (closest verified examples). `POST /chat` returns `{response, session_id, tool_calls}`, and `tool_calls` holds every tool call with its arguments and full result. The prompt requires sample sizes, a baseline comparison, noise caveats, no untested explanations, and an up-front "the data cannot show this" when it cannot.

**Frontend** (`index.html`): explains the project, offers example questions (two are deliberately unanswerable), renders answers as tables and a bar chart, and shows each SQL query and its result in an expandable card.

**Deploy:** Cloud Run (us-east1) with continuous deploy from `main` (buildpacks, `Procfile`), 4 GiB memory, 900 s timeout, max 1 instance, IAP sign-in.

## Three sample queries

Left: **the same model with no tools and no system prompt.** Right: the live agent. Full traces are in [`eval/traces/`](eval/traces/) (`<id>_bare.json`, `<id>_agent.json`).

### 1. Who has the highest clutch eFG% (minimum 150 clutch attempts, 2015-16 to 2022-23)?

Expected: **Rudy Gobert, 68.8% on 189 attempts** (66.0% outside clutch time). Source: `play_by_play` and `player`, through the `plays` and `player_shooting` views.

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "Nikola Jokic ... ~61.5% ... 713 attempts." Wrong: Jokic has 522 clutch attempts and 50.1% in this data. | **Gobert, 68.8% on 189 attempts**, vs 66.0% otherwise (+2.8, within noise). Table of the next nine players with sample sizes, and the league clutch average (48.6%). Notes the leaders are rim finishers. |

### 2. How often does a team with a 10+ point lead after three quarters win?

Expected: **95.2% (4,172 of 4,381 games).** Source: `play_by_play` (score at the end of period 3) and `game` (winner), through `plays` and `games`.

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "approximately **92.7%** ... roughly **3,150 wins and 250 losses** out of approximately 3,400." Invented counts. | **95.2% (4,172 of 4,381).** By lead size: 10-14 points 90.5% (1,781 games), 15-19 points 96.9% (1,210), 20+ points 99.9% (1,390). Names the only two comebacks from 20+ down. |

### 3. Which team had the best clutch net points in the 2022-23 regular season?

Expected: **Miami Heat, +70 over 49 games** (479 for, 409 against). Source: `play_by_play` and `game`, through `team_game_clutch`.

| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| "The **Milwaukee Bucks** ... 28-13, 334 scored, 255 allowed, **+79**." Invented. | **Miami, +70 over 49 clutch games.** Next: Philadelphia +60, New Orleans +55, Sacramento +48. Notes New Orleans leads per game (+1.72 over 32 games). |

## Two questions the plain `run_sql` agent gets wrong

The plain agent is the same model and loop with **only** `run_sql` over the raw tables: no schema docs, no helper views, no examples, a one-line prompt. It got 30 tool rounds (vs 12 for our agent) so the failure is not a step budget. Both traces are summarized below and saved in full in `eval/traces/`.

### Failure 1: "Which team lost the most 2022-23 regular-season games after leading by 15 or more points?"

- **Plain agent: no answer after 29 queries.** It found that `other_stats` home and away columns do not line up with `game`, tried to rebuild leads from the text column `scoremargin`, and ended with "What We Could Not Establish". (An earlier run guessed "Dallas, 11" from memory.)
- **Our agent: correct in 5 queries.** **Atlanta and Washington tied with 8 blown leads** (Washington 8 of 28 leads, Atlanta 8 of 35). League baseline: 116 blown of 789 leads of 15+ (14.7%).
- **Why:** the pre-built `game_swings` view already knows each game's winner and the biggest deficit they overcame.

<details><summary>Trace: plain agent (29 calls, no answer)</summary>

1-4: `SHOW TABLES`, `DESCRIBE game`, `DESCRIBE other_stats`, find the season id.
5-11: join `game` to `other_stats`, discover home and away teams are swapped in about half the games.
12-16: build a per-team lead query, count games (1,230 regular-season games).
17-26: `DESCRIBE play_by_play`, `line_score`, count which games have which data.
27-29: read `scoremargin` text values, then `MAX(TRY_CAST(scoremargin AS INTEGER))` on a single game.
Final: a methods summary and an unexecuted SQL block. No team named. Full trace: [blown15_2022_plain.json](eval/traces/blown15_2022_plain.json)
</details>

<details><summary>Trace: NBA Clutch Agent (5 calls, correct)</summary>

1. `search_examples("blown lead 15 points 2022-23")` finds the verified blown-lead example.
2. `run_sql` on `game_swings`: losers after leading by 15+, 2022-23 regular season, top 10.
3. `run_sql` listing the 16 games behind the top teams (sanity check).
4-5. `run_sql` for leads per team and the league baseline (789 leads, 116 blown).
Answer: Atlanta and Washington, 8 each, with denominators. Full trace: [blown15_2022_agent.json](eval/traces/blown15_2022_agent.json)
</details>

### Failure 2: "How did the Boston Celtics perform in clutch time in the 2023-24 season?"

- **Plain agent: fabricated.** It noticed the data ends in June 2023, then wrote a section called "External Data" with an invented line: "21-12 (.636), clutch net rating +14.3, 6-0 in the playoffs", with game details from the Pacers series. None of it is in the database.
- **Our agent: refuses first, then gives a labeled proxy.** Its first sentence says "This dataset does not include the 2023-24 season". It then reports the 2022-23 Celtics (clutch eFG% 49.2% on 239 attempts, 22-11 in clutch games) with sample sizes and a noise caveat.
- **Why:** the prompt and glossary state the data limits and require the "cannot answer" statement first.

<details><summary>Trace: plain agent (22 calls, fabricated answer)</summary>

1-7: list tables, describe columns, find the latest game date (June 2023).
8-10: look up the Celtics team id (one binder error, then fixed).
11-18: count 2022-23 Celtics games, inspect the clock format and `scoremargin`.
19-22: build a clutch-games query for 2022-23.
Final: correctly says the data stops at 2022-23, then adds "2023-24 external data" (record, net rating, playoff games) from memory. Full trace: [out_of_range_plain.json](eval/traces/out_of_range_plain.json)
</details>

<details><summary>Trace: NBA Clutch Agent (10 calls, correct)</summary>

1. `run_sql` on the seasons present (ends at 2022-23).
2. Look up the Celtics id.
3. `search_examples("team clutch performance fg% efg%")`.
4-5. `run_sql` on `team_game_clutch`: clutch games, points for and against, wins, regular season and playoffs.
6-7. `run_sql`: clutch vs non-clutch FG% and eFG%.
8-10. `run_sql`: individual players (Tatum, Brown), three-point split.
Answer starts: "This dataset does not include the 2023-24 season", then the labeled 2022-23 proxy. Full trace: [out_of_range_agent.json](eval/traces/out_of_range_agent.json)
</details>

## Known limits

- Answers vary between runs, and the prompt reduces but does not remove overclaiming (for example calling a gap a "rise" before noting it is within noise).
- Answers take 15 to 90 seconds. Vertex can return rate-limit errors under bursts, so the agent retries.
- Sessions live in memory on one instance.

## Run locally and re-run the comparisons

```
uv sync
gcloud auth application-default login      # Vertex AI access
uv run python app.py                       # http://127.0.0.1:8000
uv run python eval/compare.py --modes bare,agent clutch_efg q3_lead_hold team_clutch_net
uv run python eval/compare.py --modes plain,agent blown15_2022 out_of_range
```

Repo root: `app.py`, `tools.py`, `index.html`, `Procfile`, `pyproject.toml`, `uv.lock`, `submission.json`, plus `build/`, `context/`, `data/`, `eval/`.
