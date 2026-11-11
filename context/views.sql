-- Helper views for the NBA Clutch Agent. {DATA} is replaced with the data/ directory path at load time.
-- Score/margin conventions in the raw feed: `score` is "VISITOR - HOME"; `scoremargin` = HOME - VISITOR ('TIE' = 0).

-- One row per game (2015-16 .. 2022-23, regular season + playoffs).
CREATE OR REPLACE VIEW games AS
SELECT g.game_id,
       CAST(g.game_date AS DATE)                                  AS game_date,
       CAST(substr(g.season_id, 2) AS INTEGER)                    AS season_start_year,
       CAST(substr(g.season_id, 2) AS INTEGER) || '-' ||
         right(CAST(CAST(substr(g.season_id, 2) AS INTEGER) + 1 AS VARCHAR), 2) AS season_label,
       g.season_type,                                             -- 'Regular Season' | 'Playoffs'
       g.team_id_home AS home_team_id, g.team_abbreviation_home AS home_team,
       g.team_id_away AS away_team_id, g.team_abbreviation_away AS away_team,
       CAST(g.pts_home AS INTEGER) AS pts_home, CAST(g.pts_away AS INTEGER) AS pts_away,
       g.pts_home > g.pts_away AS home_won,
       CASE WHEN g.pts_home > g.pts_away THEN g.team_abbreviation_home ELSE g.team_abbreviation_away END AS winner,
       CASE WHEN g.pts_home > g.pts_away THEN g.team_abbreviation_away ELSE g.team_abbreviation_home END AS loser
FROM read_parquet('{DATA}/game.parquet') g;

-- One row per play-by-play event with parsed clock, forward-filled score, decoded event type, shot details, is_clutch.
CREATE OR REPLACE VIEW plays AS
WITH b AS (
  SELECT p.game_id, p.eventnum, p.period, p.eventmsgtype, p.eventmsgactiontype,
         TRY_CAST(split_part(p.pctimestring, ':', 1) AS INTEGER) * 60
           + TRY_CAST(split_part(p.pctimestring, ':', 2) AS INTEGER)     AS secs_left_period,
         TRY_CAST(split_part(p.score, ' - ', 2) AS INTEGER)              AS h_raw,
         TRY_CAST(split_part(p.score, ' - ', 1) AS INTEGER)              AS a_raw,
         p.homedescription, p.visitordescription, p.neutraldescription,
         p.player1_id, p.player1_name, p.player2_id, p.player2_name, p.player3_id, p.player3_name,
         COALESCE(CAST(TRY_CAST(p.player1_team_id AS DOUBLE) AS BIGINT)::VARCHAR, p.player1_id) AS actor_team_id,
         g.game_date, g.season_start_year, g.season_label, g.season_type,
         g.home_team_id, g.home_team, g.away_team_id, g.away_team
  FROM read_parquet('{DATA}/play_by_play_*.parquet') p
  JOIN games g USING (game_id)
), f AS (
  SELECT *,
    COALESCE(MAX(h_raw) OVER w, 0) AS home_score,
    COALESCE(MAX(a_raw) OVER w, 0) AS away_score
  FROM b
  WINDOW w AS (PARTITION BY game_id ORDER BY period, secs_left_period DESC, eventnum ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
), s AS (
  SELECT *,
    home_score - away_score AS home_margin,
    LAG(home_score - away_score, 1, 0) OVER (PARTITION BY game_id ORDER BY period, secs_left_period DESC, eventnum) AS home_margin_before,
    CASE WHEN eventmsgtype IN (1, 2, 3) THEN
      CASE WHEN NULLIF(homedescription, '') IS NOT NULL AND homedescription NOT LIKE '%BLOCK%'
           THEN homedescription ELSE visitordescription END
    END AS shot_desc
  FROM f
)
SELECT game_id, eventnum, game_date, season_start_year, season_label, season_type,
  home_team, away_team, period,
  secs_left_period,
  CASE WHEN period <= 4 THEN (4 - period) * 720 + secs_left_period ELSE secs_left_period END AS secs_left_game,
  home_score, away_score, home_margin, home_margin_before,
  CASE eventmsgtype WHEN 1 THEN 'MADE_SHOT' WHEN 2 THEN 'MISSED_SHOT' WHEN 3 THEN 'FREE_THROW'
    WHEN 4 THEN 'REBOUND' WHEN 5 THEN 'TURNOVER' WHEN 6 THEN 'FOUL' WHEN 7 THEN 'VIOLATION'
    WHEN 8 THEN 'SUBSTITUTION' WHEN 9 THEN 'TIMEOUT' WHEN 10 THEN 'JUMP_BALL' WHEN 11 THEN 'EJECTION'
    WHEN 12 THEN 'PERIOD_START' WHEN 13 THEN 'PERIOD_END' WHEN 18 THEN 'INSTANT_REPLAY'
    ELSE 'OTHER' END AS event_type,
  eventmsgtype, eventmsgactiontype,
  CASE WHEN actor_team_id = home_team_id THEN 'HOME' WHEN actor_team_id = away_team_id THEN 'AWAY' END AS acting_side,
  CASE WHEN actor_team_id = home_team_id THEN home_team WHEN actor_team_id = away_team_id THEN away_team END AS acting_team,
  player1_id AS player_id, player1_name AS player_name,
  player2_id, player2_name,   -- assister on made shots, fouled player on fouls, stealer on turnovers
  player3_id, player3_name,   -- blocker on missed shots
  concat_ws(' | ', NULLIF(homedescription, ''), NULLIF(visitordescription, ''), NULLIF(neutraldescription, '')) AS description,
  -- shot / free-throw details (NULL for other events)
  CASE WHEN eventmsgtype IN (1, 2) THEN shot_desc LIKE '%3PT%' END                       AS is_three,
  CASE WHEN eventmsgtype = 1 THEN 3 - (NOT (shot_desc LIKE '%3PT%'))::INT
       WHEN eventmsgtype = 3 AND shot_desc NOT LIKE '%MISS%' THEN 1 ELSE 0 END           AS points_scored,
  CASE WHEN eventmsgtype IN (1, 2) THEN
    CASE WHEN shot_desc LIKE '%3PT%' THEN 'three_pointer'
         WHEN shot_desc ILIKE '%dunk%' THEN 'dunk'
         WHEN shot_desc ILIKE '%layup%' OR shot_desc ILIKE '%finger roll%' THEN 'layup'
         WHEN shot_desc ILIKE '%hook%' THEN 'hook'
         WHEN shot_desc ILIKE '%tip%' THEN 'tip_in'
         WHEN shot_desc ILIKE '%jump shot%' OR shot_desc ILIKE '%pullup%' OR shot_desc ILIKE '%fadeaway%'
              OR shot_desc ILIKE '%step back%' OR shot_desc ILIKE '%bank%' THEN 'two_point_jumper'
         ELSE 'other' END END AS shot_kind,
  TRY_CAST(NULLIF(regexp_extract(shot_desc, '(\d+)''', 1), '') AS INTEGER) AS shot_distance_ft,
  -- clutch = 4th quarter or OT, <= 5:00 left, score within 5 going into the play
  (period >= 4 AND secs_left_period <= 300 AND abs(home_margin_before) <= 5) AS is_clutch
FROM s;

CREATE OR REPLACE VIEW clutch_plays AS SELECT * FROM plays WHERE is_clutch;

-- Per player, season, season type, clutch vs not: shooting line from play-by-play.
CREATE OR REPLACE VIEW player_shooting AS
SELECT player_id, player_name, season_start_year, season_label, season_type, is_clutch,
  COUNT(DISTINCT game_id)                                      AS games,
  COUNT(*) FILTER (WHERE eventmsgtype IN (1, 2))               AS fga,
  COUNT(*) FILTER (WHERE eventmsgtype = 1)                     AS fgm,
  COUNT(*) FILTER (WHERE is_three)                             AS fg3a,
  COUNT(*) FILTER (WHERE is_three AND eventmsgtype = 1)        AS fg3m,
  COUNT(*) FILTER (WHERE eventmsgtype = 3)                     AS fta,
  COUNT(*) FILTER (WHERE eventmsgtype = 3 AND points_scored = 1) AS ftm,
  SUM(points_scored)                                           AS pts
FROM plays
WHERE eventmsgtype IN (1, 2, 3) AND player_id IS NOT NULL AND player_id <> '0'
GROUP BY ALL;

-- Per team per game: points scored/allowed during clutch plays (only games that had any clutch play).
CREATE OR REPLACE VIEW team_game_clutch AS
WITH c AS (
  SELECT game_id, season_start_year, season_label, season_type, home_team, away_team,
         SUM(points_scored) FILTER (WHERE acting_side = 'HOME') AS home_pts,
         SUM(points_scored) FILTER (WHERE acting_side = 'AWAY') AS away_pts
  FROM plays WHERE is_clutch GROUP BY ALL
)
SELECT game_id, season_start_year, season_label, season_type, home_team AS team, away_team AS opponent,
       TRUE AS is_home, COALESCE(home_pts, 0) AS clutch_pts_for, COALESCE(away_pts, 0) AS clutch_pts_against FROM c
UNION ALL
SELECT game_id, season_start_year, season_label, season_type, away_team, home_team,
       FALSE, COALESCE(away_pts, 0), COALESCE(home_pts, 0) FROM c;

-- One row per game: biggest holes and leads, comeback / blown-lead flags, lead changes.
CREATE OR REPLACE VIEW game_swings AS
WITH m AS (
  SELECT game_id, MAX(home_margin) AS max_home_margin, MIN(home_margin) AS min_home_margin
  FROM plays GROUP BY game_id
)
SELECT g.game_id, g.game_date, g.season_start_year, g.season_label, g.season_type,
  g.home_team, g.away_team, g.pts_home, g.pts_away, g.winner, g.loser,
  GREATEST(m.max_home_margin, 0)  AS home_max_lead,
  GREATEST(-m.min_home_margin, 0) AS away_max_lead,
  -- biggest deficit the eventual winner overcame (= biggest lead the loser blew)
  CASE WHEN g.home_won THEN GREATEST(-m.min_home_margin, 0) ELSE GREATEST(m.max_home_margin, 0) END AS winner_max_deficit,
  winner_max_deficit >= 10 AS comeback_10,
  winner_max_deficit >= 15 AS comeback_15,
  winner_max_deficit >= 20 AS comeback_20,
  o.lead_changes, o.times_tied
FROM games g
JOIN m USING (game_id)
LEFT JOIN read_parquet('{DATA}/other_stats.parquet') o USING (game_id);
