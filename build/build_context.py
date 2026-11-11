"""Offline step 2: build the context/ docs the agent reads to write correct SQL.
Run: uv run python build/build_context.py
Writes context/schema.md, context/glossary.md, context/teams.md (numbers are computed live from the data).
"""
import json
import pathlib
import sys
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
CTX = ROOT / "context"
DATA = ROOT / "data"

con = duckdb.connect()
con.execute((CTX / "views.sql").read_text().replace("{DATA}", str(DATA)))

# Hand-written column notes (only columns whose meaning isn't obvious from the name).
NOTES = {
    "games": {
        "season_start_year": "2022 = the 2022-23 season", "season_label": "e.g. '2022-23'",
        "season_type": "'Regular Season' or 'Playoffs'", "home_won": "TRUE if home team won",
        "winner": "winning team abbreviation", "loser": "losing team abbreviation",
    },
    "plays": {
        "eventnum": "order key within a game (a few late-added rows are out of order; sort by period, secs_left_period DESC, eventnum)",
        "period": "1-4 = quarters, 5+ = overtimes",
        "secs_left_period": "seconds left in the period (quarters 720 long, OT 300 long)",
        "secs_left_game": "seconds left in regulation (period<=4); in OT it is seconds left in that OT period",
        "home_score": "home points AFTER this event", "away_score": "away points AFTER this event",
        "home_margin": "home_score - away_score AFTER this event (positive = home leading)",
        "home_margin_before": "margin going INTO this event",
        "event_type": "decoded event, see glossary",
        "acting_side": "'HOME'/'AWAY' = team of the player who did the event (NULL for period start/end, replay)",
        "acting_team": "team abbreviation of acting_side",
        "player_id": "main player of the event (shooter, rebounder, turnover committer, fouler)",
        "player_name": "e.g. 'Stephen Curry' (full name); NULL for team events like team rebounds",
        "player2_name": "assister (made shot), fouled player (foul), stealer (turnover)",
        "player3_name": "blocker (missed shot)",
        "description": "raw play text from the feed",
        "is_three": "TRUE for 3-point attempts (made or missed); NULL for non-shot events",
        "points_scored": "points from this event parsed from text (see limits: not exact in ~4% of games)",
        "shot_kind": "three_pointer | two_point_jumper | layup | dunk | hook | tip_in | other (shots only)",
        "shot_distance_ft": "feet from basket parsed from text; NULL for many dunks/tips",
        "is_clutch": "TRUE when period>=4, <=300 secs left in the period, and |home_margin_before|<=5",
    },
    "player_shooting": {
        "is_clutch": "TRUE row = clutch plays only; FALSE row = all other plays",
        "games": "distinct games in which the player had at least one shot/FT in this split",
        "pts": "sum of points_scored (approximate, see limits)",
    },
    "team_game_clutch": {
        "clutch_pts_for": "points the team scored on clutch plays", "clutch_pts_against": "points the opponent scored on clutch plays",
        "is_home": "TRUE if team was the home team",
    },
    "game_swings": {
        "winner_max_deficit": "biggest deficit the eventual winner faced = biggest lead the loser blew",
        "comeback_10": "winner trailed by 10+ at some point (15/20 similar)",
        "home_max_lead": "home team's biggest lead", "away_max_lead": "away team's biggest lead",
        "lead_changes": "from other_stats (official count)", "times_tied": "from other_stats",
    },
}
VIEW_INTRO = {
    "games": "One row per game (note: ~9% of games here have no play-by-play; use plays/game_swings for anything event-based).",
    "plays": "MAIN TABLE. One row per play-by-play event with parsed clock, running score, decoded event type, shot details and is_clutch.",
    "clutch_plays": "plays filtered to is_clutch = TRUE (same columns as plays).",
    "player_shooting": "Per player x season x season_type x is_clutch: FGA/FGM/3PA/3PM/FTA/FTM/pts from play-by-play.",
    "team_game_clutch": "Per team x game: points for/against during clutch plays (only games with at least one clutch play).",
    "game_swings": "One row per game (with play-by-play): largest leads/deficits, comeback flags, lead changes.",
    "teams": "30 teams: id, full_name, abbreviation, nickname, city, state, year_founded.",
    "players": "id, full_name, first_name, last_name, is_active (join to plays.player_id = players.id).",
    "other_stats": "Official box extras per game: team_id/abbr home & away, pts_paint, pts_fb (fast break), pts_2nd_chance, largest_lead, lead_changes, times_tied, turnovers (total_turnovers_*, team_turnovers_*), team_rebounds, pts_off_to (points off turnovers).",
    "line_score": "Points by quarter and OT per game: pts_qtr1_home .. pts_qtr4_home, pts_ot1_home.., same for _away.",
    "officials": "game_id, official_id, first_name, last_name, jersey_num (referees per game).",
}
ORDER = ["plays", "clutch_plays", "games", "game_swings", "player_shooting", "team_game_clutch",
         "other_stats", "line_score", "officials", "teams", "players"]


def schema_md():
    out = ["# Schema (DuckDB views; query these, never raw files)\n",
           "All tables below are read-only views. Prefer `plays`, `games`, `game_swings`, `player_shooting`, `team_game_clutch`.\n"]
    for v in ORDER:
        out.append(f"\n## {v}\n{VIEW_INTRO.get(v, '')}\n")
        if v == "clutch_plays":
            continue
        out.append("| column | type | notes |\n|---|---|---|")
        for name, typ, *_ in con.execute(f"DESCRIBE {v}").fetchall():
            if v in ("line_score",) and ("_ot" in name and not name.endswith(("ot1_home", "ot1_away"))):
                continue  # skip ot2..ot10 clutter
            out.append(f"| {name} | {typ} | {NOTES.get(v, {}).get(name, '')} |")
    return "\n".join(out) + "\n"


def glossary_md():
    n_games, n_pbp, n_plays = con.execute(
        "SELECT (SELECT count(*) FROM games), (SELECT count(*) FROM game_swings), (SELECT count(*) FROM plays)").fetchone()
    cl_plays, cl_games = con.execute("SELECT count(*), count(DISTINCT game_id) FROM clutch_plays").fetchone()
    seasons = con.execute("""SELECT season_label, season_type, count(*) FROM game_swings
                             GROUP BY ALL ORDER BY 1, 2""").fetchall()
    events = con.execute("""SELECT event_type, eventmsgtype, count(*) FROM plays GROUP BY ALL ORDER BY 2""").fetchall()
    ev_note = {
        "MADE_SHOT": "field goal made; player=shooter, player2=assister", "MISSED_SHOT": "field goal missed; player3=blocker",
        "FREE_THROW": "free throw (made unless description has MISS)", "REBOUND": "player=rebounder; team rebounds have no player",
        "TURNOVER": "player=who turned it over, player2=stealer", "FOUL": "player=fouler, player2=fouled",
        "VIOLATION": "e.g. delay of game, kicked ball", "SUBSTITUTION": "player=sub out, player2=sub in",
        "TIMEOUT": "acting_side = team calling it", "JUMP_BALL": "", "EJECTION": "", "PERIOD_START": "", "PERIOD_END": "",
        "INSTANT_REPLAY": "replay review",
    }
    out = ["# Glossary, conventions and limits\n",
           "## Coverage",
           f"- Seasons 2015-16 to 2022-23, regular season + playoffs. {n_pbp:,} games with play-by-play "
           f"({n_plays:,} events) out of {n_games:,} games in `games`. The most recent data is June 2023; "
           "nothing after the 2022-23 season exists.",
           "- A few games per season are missing play-by-play. 2019-20 and 2020-21 are shortened/odd seasons "
           "(COVID bubble/short schedule): compare totals across seasons carefully, use rates not counts.",
           "- Games with pbp per season:  " + "; ".join(f"{s} {t.split()[0]} {c}" for s, t, c in seasons),
           "\n## Key conventions",
           "- Raw feed: `score` is 'VISITOR - HOME' and `scoremargin` is HOME - VISITOR ('TIE' = 0). "
           "The `plays` view already fixes this: use home_score, away_score, home_margin.",
           "- Team in `plays`: acting_team/acting_side. Home team = games.home_team. "
           "To get a team's margin: `CASE WHEN acting_side='HOME' THEN home_margin ELSE -home_margin END` "
           "(or join games and compare with the team).",
           "- Period 1-4 are 12:00 quarters; 5+ are 5:00 overtimes. Clock counts DOWN (`secs_left_period`).",
           "- season_id in raw data = type digit + start year ('22022' = 2022-23 regular season). "
           "Views expose season_start_year, season_label, season_type instead.",
           "- Team abbreviations are stable in this window (BKN, CHA, NOP, OKC, ...). See teams.md.",
           "\n## Clutch definition (used by is_clutch)",
           "Clutch play = 4th quarter or overtime, at most 5:00 left in that period, and the score within 5 points "
           "(either way) going INTO the play (|home_margin_before| <= 5). "
           f"There are {cl_plays:,} clutch plays in {cl_games:,} games. "
           "Because the window is evaluated play by play, a game can enter and leave clutch time. "
           "Always compare clutch vs non-clutch (is_clutch FALSE) and report sample sizes (FGA, games).",
           "\n## Event types (plays.event_type / eventmsgtype)",
           "| event_type | code | rows | notes |\n|---|---|---|---|"]
    out += [f"| {e} | {c} | {n:,} | {ev_note.get(e, '')} |" for e, c, n in events]
    out += ["\n## Shot descriptions",
            "shot_kind and shot_distance_ft are parsed from the play text. FG% = fgm/fga; eFG% = (fgm + 0.5*fg3m)/fga; "
            "TS% = pts/(2*(fga+0.44*fta)). Free throws are event_type FREE_THROW (not counted in fga).",
            "\n## Limits (say so when asked)",
            "- NO shot x/y locations (only distance in feet, missing for some dunks/tips) and no shot-clock, tracking, "
            "defender, lineup/on-court, or possession data. Defense can only be inferred from blocks, steals, opponent scoring.",
            "- No play-by-play after June 2023. No betting/odds data (out of scope).",
            "- points_scored is parsed from descriptions; per-game sums differ from the official score in ~4% of games "
            "(usually by 2-3 points). Use home_score/away_score/home_margin for score state. "
            "Final scores reconstructed from the running score match the official score in all games.",
            "- Clock and event order in the feed have rare glitches (late-added rows); running score uses the running maximum.",
            "- Small samples: single-season clutch FGA is often < 100 per player; warn and prefer multi-season pooling.",
            "- Causal questions (what 'causes' a blown lead) can only be answered as associations."]
    return "\n".join(out) + "\n"


def teams_md():
    rows = con.execute("SELECT abbreviation, full_name, id FROM teams ORDER BY abbreviation").fetchall()
    out = ["# Teams (30 franchises, abbreviations stable across 2015-16 to 2022-23)\n",
           "Relocations before this window (SEA->OKC 2008, NJN->BKN 2012, NOH->NOP 2013, CHA again 2014) are not visible here.\n",
           "| abbr | team | team_id |\n|---|---|---|"]
    out += [f"| {a} | {n} | {i} |" for a, n, i in rows]
    return "\n".join(out) + "\n"


def run_examples():
    """Run every verified example; fail the build if one errors or returns no rows."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from examples import EXAMPLES
    results = []
    for e in EXAMPLES:
        sql = e["sql"].strip()
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(5)
        except Exception as ex:
            raise SystemExit(f"EXAMPLE FAILED: {e['id']}: {ex}")
        if not rows:
            raise SystemExit(f"EXAMPLE RETURNED NO ROWS: {e['id']}")
        results.append({**e, "sql": sql, "columns": cols, "sample_rows": [[str(v) for v in r] for r in rows]})
    return results


def examples_md(results):
    out = ["# Verified example queries (each was executed against the real data)\n"]
    for r in results:
        out.append(f"## {r['question']}\n(id: {r['id']}, topic: {r['topic']})\n\n```sql\n{r['sql']}\n```")
        out.append("Sample result: " + " | ".join(r["columns"]))
        out += ["  " + " | ".join(row) for row in r["sample_rows"][:3]]
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    for name, fn in [("schema.md", schema_md), ("glossary.md", glossary_md), ("teams.md", teams_md)]:
        text = fn()
        (CTX / name).write_text(text)
        print(f"{name:12s} {len(text):6d} chars  (~{len(text)//4} tokens)")
    results = run_examples()
    (CTX / "examples.json").write_text(json.dumps(results, indent=1))
    text = examples_md(results)
    (CTX / "examples.md").write_text(text)
    print(f"examples.md  {len(text):6d} chars  ({len(results)} examples, all executed OK)")
