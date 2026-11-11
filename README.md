# NBA Clutch Agent
Text2SQL data-exploration agent over NBA play-by-play. Columbia MSDS Agentic AI, Project 2.
Live demo: <deploy_url>  ·  Author: kd3070

## What it explores & who it's for
Crunch-time questions: who is clutch, how comebacks and blown leads happen,
how late-game shot choices change. For NBA fans, fantasy players and analysts
who want evidence-backed answers (numbers + sample sizes), not hot takes.

## Data
Source: Kaggle "NBA Database" (wyattowalsh/basketball), built from stats.nba.com.
Seasons used: 2019-20 to 2022-23, regular season + playoffs. <TODO coverage numbers>
How to load: <TODO: download link, build/prep_data.py → data/*.parquet>
Conventions: <TODO score is visitor-first; scoremargin = home − visitor; clock format; season_id>
Limits: <TODO no shot locations, no tracking, some games missing, shortened seasons>

## How it works
Offline build (build/): <TODO> → context/ (schema docs, decoded values, views, verified examples).
Agent (app.py, tools.py): <TODO tools, max turns, model>

## Sample queries
### 1. <TODO>   Table: <TODO>   Expected: <TODO>
| No tools, no system prompt | NBA Clutch Agent |
|---|---|
| <TODO> | <TODO> |

(repeat for 2 and 3)

## Where the plain run_sql agent fails
### Failure 1: <TODO>   (plain trace / my agent's trace)
### Failure 2: <TODO>

## Run locally / Deploy
<TODO: uv run uvicorn app:app, Cloud Run continuous deploy from GitHub>
