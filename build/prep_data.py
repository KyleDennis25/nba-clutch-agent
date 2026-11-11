"""Offline step 1: export recent seasons from the 2.2 GB SQLite file to Parquet.
Run: uv run python build/prep_data.py
"""
import duckdb, pathlib

RAW = "data/raw/nba.sqlite"
OUT = pathlib.Path("data")
# 2015-16 .. 2022-23, regular season (2) + playoffs (4)
SEASONS = [f"{t}{y}" for y in range(2015, 2023) for t in (2, 4)]
IN_SEASONS = ",".join(f"'{s}'" for s in SEASONS)
DROP_PBP = ("wctimestring, video_available_flag, person1type, person2type, person3type, "
            "player1_team_city, player1_team_nickname, player2_team_city, "
            "player2_team_nickname, player3_team_city, player3_team_nickname")

con = duckdb.connect()
con.execute(f"ATTACH '{RAW}' AS nba (TYPE sqlite, READ_ONLY)")
con.execute(f"CREATE TEMP TABLE games AS SELECT * FROM nba.game WHERE season_id IN ({IN_SEASONS})")


def dump(sql, name):
    path = OUT / f"{name}.parquet"
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd)")
    print(f"{name:28s} {path.stat().st_size/1e6:7.1f} MB")


# play_by_play: one file per season so each stays well under 100 MB
for s in SEASONS:
    dump(f"""SELECT p.* EXCLUDE ({DROP_PBP}) FROM nba.play_by_play p
             JOIN games g USING (game_id) WHERE g.season_id = '{s}'
             ORDER BY game_id, eventnum""", f"play_by_play_{s}")

dump("SELECT * FROM games", "game")
for t in ("other_stats", "line_score", "officials"):
    dump(f"SELECT * FROM nba.{t} WHERE game_id IN (SELECT game_id FROM games)", t)
for t in ("team", "team_history", "player"):
    dump(f"SELECT * FROM nba.{t}", t)
