"""Verified question -> SQL examples. build_context.py runs each one and fails if it errors or returns no rows."""

EXAMPLES = [
    # ---------------- Q1: clutch performance, players and teams ----------------
    {
        "id": "clutch_fg_leaders",
        "topic": "players",
        "question": "Which players shoot best in clutch time (2015-16 to 2022-23, min 150 clutch FGA)?",
        "sql": """
SELECT player_name, SUM(fga) AS clutch_fga, SUM(fgm) AS clutch_fgm,
       ROUND(100.0 * SUM(fgm) / SUM(fga), 1) AS fg_pct,
       ROUND(100.0 * (SUM(fgm) + 0.5 * SUM(fg3m)) / SUM(fga), 1) AS efg_pct
FROM player_shooting
WHERE is_clutch
GROUP BY player_id, player_name
HAVING SUM(fga) >= 150
ORDER BY efg_pct DESC
LIMIT 10""",
    },
    {
        "id": "clutch_dropoff",
        "topic": "players",
        "question": "Which players get worse in clutch time compared to the rest of the game (biggest FG% drop, min 200 clutch FGA)?",
        "sql": """
WITH s AS (
  SELECT player_id, player_name,
         SUM(fga) FILTER (WHERE is_clutch) AS c_fga, SUM(fgm) FILTER (WHERE is_clutch) AS c_fgm,
         SUM(fga) FILTER (WHERE NOT is_clutch) AS n_fga, SUM(fgm) FILTER (WHERE NOT is_clutch) AS n_fgm
  FROM player_shooting GROUP BY player_id, player_name)
SELECT player_name, c_fga AS clutch_fga, ROUND(100.0 * c_fgm / c_fga, 1) AS clutch_fg_pct,
       n_fga AS other_fga, ROUND(100.0 * n_fgm / n_fga, 1) AS other_fg_pct,
       ROUND(100.0 * c_fgm / c_fga - 100.0 * n_fgm / n_fga, 1) AS diff_pts
FROM s WHERE c_fga >= 200 AND n_fga >= 2000
ORDER BY diff_pts ASC
LIMIT 10""",
    },
    {
        "id": "player_clutch_by_season",
        "topic": "players",
        "question": "How has a specific player (here Stephen Curry) shot in clutch vs non-clutch situations each season?",
        "sql": """
SELECT season_label, is_clutch, SUM(fga) AS fga, SUM(fgm) AS fgm,
       ROUND(100.0 * SUM(fgm) / SUM(fga), 1) AS fg_pct, SUM(fta) AS fta, SUM(ftm) AS ftm
FROM player_shooting
WHERE player_name = 'Stephen Curry' AND season_type = 'Regular Season'
GROUP BY season_label, is_clutch
ORDER BY season_label, is_clutch""",
    },
    {
        "id": "team_clutch_net",
        "topic": "teams",
        "question": "Which teams outscore opponents the most in clutch time (2022-23 regular season)?",
        "sql": """
SELECT team, COUNT(*) AS clutch_games, SUM(clutch_pts_for) AS pts_for, SUM(clutch_pts_against) AS pts_against,
       SUM(clutch_pts_for - clutch_pts_against) AS net_pts,
       ROUND(AVG(clutch_pts_for - clutch_pts_against), 2) AS net_per_game
FROM team_game_clutch
WHERE season_start_year = 2022 AND season_type = 'Regular Season'
GROUP BY team
ORDER BY net_pts DESC
LIMIT 10""",
    },
    {
        "id": "team_clutch_record",
        "topic": "teams",
        "question": "What is each team's win-loss record in games that had clutch time (2022-23 regular season)?",
        "sql": """
SELECT t.team, COUNT(*) AS clutch_games, SUM((g.winner = t.team)::INT) AS wins,
       COUNT(*) - SUM((g.winner = t.team)::INT) AS losses,
       ROUND(100.0 * SUM((g.winner = t.team)::INT) / COUNT(*), 1) AS win_pct
FROM team_game_clutch t JOIN games g USING (game_id)
WHERE t.season_start_year = 2022 AND t.season_type = 'Regular Season'
GROUP BY t.team
ORDER BY win_pct DESC, clutch_games DESC
LIMIT 10""",
    },
    {
        "id": "clutch_free_throws",
        "topic": "players",
        "question": "How does free-throw shooting change in clutch time, league-wide?",
        "sql": """
SELECT is_clutch, SUM(fta) AS fta, SUM(ftm) AS ftm, ROUND(100.0 * SUM(ftm) / SUM(fta), 2) AS ft_pct
FROM player_shooting
GROUP BY is_clutch ORDER BY is_clutch""",
    },
    # ---------------- Q2: comebacks and blown leads ----------------
    {
        "id": "comeback_rate_by_season",
        "topic": "comebacks",
        "question": "How often do teams come back from double-digit deficits to win, by season (regular season)?",
        "sql": """
SELECT season_label, COUNT(*) AS games, SUM(comeback_10::INT) AS wins_after_trailing_10,
       ROUND(100.0 * SUM(comeback_10::INT) / COUNT(*), 1) AS pct_10,
       SUM(comeback_20::INT) AS wins_after_trailing_20,
       ROUND(100.0 * SUM(comeback_20::INT) / COUNT(*), 2) AS pct_20
FROM game_swings
WHERE season_type = 'Regular Season'
GROUP BY season_label ORDER BY season_label""",
    },
    {
        "id": "blown_leads_by_team",
        "topic": "comebacks",
        "question": "Which teams have most often lost after leading by 15+ points (all seasons)?",
        "sql": """
SELECT loser AS team, COUNT(*) AS losses, SUM(comeback_15::INT) AS losses_after_leading_15,
       ROUND(100.0 * SUM(comeback_15::INT) / COUNT(*), 1) AS pct_of_losses
FROM game_swings
GROUP BY loser
ORDER BY losses_after_leading_15 DESC
LIMIT 10""",
    },
    {
        "id": "q3_lead_hold_rate",
        "topic": "comebacks",
        "question": "How often does a team that leads by 10+ after three quarters hold on to win, by lead size?",
        "sql": """
WITH q3 AS (SELECT game_id, home_margin AS m3 FROM plays WHERE event_type = 'PERIOD_END' AND period = 3),
lead AS (
  SELECT q.game_id, ABS(m3) AS lead_pts, (m3 > 0) = g.home_won AS held
  FROM q3 q JOIN games g USING (game_id) WHERE ABS(m3) >= 10)
SELECT CASE WHEN lead_pts >= 20 THEN '20+' WHEN lead_pts >= 15 THEN '15-19' ELSE '10-14' END AS lead_after_q3,
       COUNT(*) AS games, SUM(held::INT) AS held_on, ROUND(100.0 * AVG(held::INT), 1) AS hold_pct
FROM lead GROUP BY 1 ORDER BY 1""",
    },
    {
        "id": "blown_lead_predictors",
        "topic": "comebacks",
        "question": "Among teams leading by 10+ after Q3, do those that blow the lead commit more 4th-quarter turnovers/fouls and get outscored?",
        "sql": """
WITH q3 AS (SELECT game_id, home_margin AS m3 FROM plays WHERE event_type = 'PERIOD_END' AND period = 3),
lead AS (
  SELECT q.game_id, CASE WHEN m3 > 0 THEN 'HOME' ELSE 'AWAY' END AS leader_side,
         (m3 > 0) = g.home_won AS held
  FROM q3 q JOIN games g USING (game_id) WHERE ABS(m3) >= 10),
q4 AS (
  SELECT l.game_id, l.held,
    COUNT(*) FILTER (WHERE p.event_type = 'TURNOVER' AND p.acting_side = l.leader_side) AS leader_tov,
    COUNT(*) FILTER (WHERE p.event_type = 'FOUL' AND p.acting_side = l.leader_side) AS leader_fouls,
    COALESCE(SUM(p.points_scored) FILTER (WHERE p.acting_side = l.leader_side), 0) AS leader_pts,
    COALESCE(SUM(p.points_scored) FILTER (WHERE p.acting_side <> l.leader_side), 0) AS trailer_pts
  FROM lead l JOIN plays p ON p.game_id = l.game_id AND p.period = 4
  GROUP BY l.game_id, l.held, l.leader_side)
SELECT CASE WHEN held THEN 'held lead' ELSE 'blew lead' END AS outcome, COUNT(*) AS games,
       ROUND(AVG(leader_tov), 2) AS avg_q4_turnovers, ROUND(AVG(leader_fouls), 2) AS avg_q4_fouls,
       ROUND(AVG(leader_pts), 1) AS avg_q4_pts_leader, ROUND(AVG(trailer_pts), 1) AS avg_q4_pts_trailer
FROM q4 GROUP BY held ORDER BY held DESC""",
    },
    {
        "id": "biggest_scoring_runs",
        "topic": "comebacks",
        "question": "What are the biggest unanswered scoring runs in a single game (2022-23 regular season)?",
        "sql": """
WITH sc AS (
  SELECT p.game_id, p.acting_side, p.points_scored, p.period,
         ROW_NUMBER() OVER (PARTITION BY p.game_id ORDER BY p.period, p.secs_left_period DESC, p.eventnum) AS rn
  FROM plays p
  WHERE p.points_scored > 0 AND p.acting_side IS NOT NULL
    AND p.season_start_year = 2022 AND p.season_type = 'Regular Season'),
grp AS (
  SELECT *, rn - ROW_NUMBER() OVER (PARTITION BY game_id, acting_side ORDER BY rn) AS island FROM sc),
runs AS (
  SELECT game_id, acting_side, SUM(points_scored) AS run_pts, MIN(period) AS start_period
  FROM grp GROUP BY game_id, acting_side, island)
SELECT g.game_date, g.home_team, g.away_team,
       CASE r.acting_side WHEN 'HOME' THEN g.home_team ELSE g.away_team END AS run_team,
       r.run_pts, r.start_period
FROM runs r JOIN games g USING (game_id)
ORDER BY r.run_pts DESC LIMIT 10""",
    },
    # ---------------- Q3: shot choice late in close games ----------------
    {
        "id": "shot_mix_clutch",
        "topic": "shots",
        "question": "How does the shot mix and efficiency change in clutch time vs the rest of the game?",
        "sql": """
SELECT is_clutch, shot_kind, COUNT(*) AS fga,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY is_clutch), 1) AS share_of_fga,
       ROUND(100.0 * AVG((event_type = 'MADE_SHOT')::INT), 1) AS fg_pct
FROM plays
WHERE event_type IN ('MADE_SHOT', 'MISSED_SHOT')
GROUP BY is_clutch, shot_kind
ORDER BY is_clutch, fga DESC""",
    },
    {
        "id": "shot_distance_clutch",
        "topic": "shots",
        "question": "Do teams shoot from farther out in clutch time, and does it pay off (shot distance buckets)?",
        "sql": """
WITH shots AS (
  SELECT is_clutch, event_type,
         CASE WHEN shot_distance_ft <= 4 THEN 1 WHEN shot_distance_ft <= 14 THEN 2
              WHEN shot_distance_ft <= 22 THEN 3 ELSE 4 END AS bucket
  FROM plays
  WHERE event_type IN ('MADE_SHOT', 'MISSED_SHOT') AND shot_distance_ft IS NOT NULL)
SELECT is_clutch,
       CASE bucket WHEN 1 THEN '0-4 ft' WHEN 2 THEN '5-14 ft' WHEN 3 THEN '15-22 ft' ELSE '23+ ft' END AS distance,
       COUNT(*) AS fga,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY is_clutch), 1) AS share_of_fga,
       ROUND(100.0 * AVG((event_type = 'MADE_SHOT')::INT), 1) AS fg_pct
FROM shots
GROUP BY is_clutch, bucket
ORDER BY is_clutch, bucket""",
    },
    {
        "id": "final_minute_shooters",
        "topic": "shots",
        "question": "Who takes the most shots in the final 60 seconds of close games, and how do they shoot (2018-19 to 2022-23)?",
        "sql": """
SELECT player_name, COUNT(*) AS fga, SUM((event_type = 'MADE_SHOT')::INT) AS fgm,
       ROUND(100.0 * AVG((event_type = 'MADE_SHOT')::INT), 1) AS fg_pct,
       ROUND(100.0 * AVG(is_three::INT), 1) AS pct_threes
FROM clutch_plays
WHERE event_type IN ('MADE_SHOT', 'MISSED_SHOT') AND secs_left_period <= 60
  AND season_start_year BETWEEN 2018 AND 2022
GROUP BY player_id, player_name
ORDER BY fga DESC LIMIT 10""",
    },
]
