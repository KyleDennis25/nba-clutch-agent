# Schema (DuckDB views; query these, never raw files)

All tables below are read-only views. Prefer `plays`, `games`, `game_swings`, `player_shooting`, `team_game_clutch`.


## plays
MAIN TABLE. One row per play-by-play event with parsed clock, running score, decoded event type, shot details and is_clutch.

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| eventnum | BIGINT | order key within a game (a few late-added rows are out of order; sort by period, secs_left_period DESC, eventnum) |
| game_date | DATE |  |
| season_start_year | INTEGER |  |
| season_label | VARCHAR |  |
| season_type | VARCHAR |  |
| home_team | VARCHAR |  |
| away_team | VARCHAR |  |
| period | BIGINT | 1-4 = quarters, 5+ = overtimes |
| secs_left_period | INTEGER | seconds left in the period (quarters 720 long, OT 300 long) |
| secs_left_game | BIGINT | seconds left in regulation (period<=4); in OT it is seconds left in that OT period |
| home_score | INTEGER | home points AFTER this event |
| away_score | INTEGER | away points AFTER this event |
| home_margin | INTEGER | home_score - away_score AFTER this event (positive = home leading) |
| home_margin_before | INTEGER | margin going INTO this event |
| event_type | VARCHAR | decoded event, see glossary |
| eventmsgtype | BIGINT |  |
| eventmsgactiontype | BIGINT |  |
| acting_side | VARCHAR | 'HOME'/'AWAY' = team of the player who did the event (NULL for period start/end, replay) |
| acting_team | VARCHAR | team abbreviation of acting_side |
| player_id | VARCHAR | main player of the event (shooter, rebounder, turnover committer, fouler) |
| player_name | VARCHAR | e.g. 'Stephen Curry' (full name); NULL for team events like team rebounds |
| player2_id | VARCHAR |  |
| player2_name | VARCHAR | assister (made shot), fouled player (foul), stealer (turnover) |
| player3_id | VARCHAR |  |
| player3_name | VARCHAR | blocker (missed shot) |
| description | VARCHAR | raw play text from the feed |
| is_three | BOOLEAN | TRUE for 3-point attempts (made or missed); NULL for non-shot events |
| points_scored | INTEGER | points from this event parsed from text (see limits: not exact in ~4% of games) |
| shot_kind | VARCHAR | three_pointer | two_point_jumper | layup | dunk | hook | tip_in | other (shots only) |
| shot_distance_ft | INTEGER | feet from basket parsed from text; NULL for many dunks/tips |
| is_clutch | BOOLEAN | TRUE when period>=4, <=300 secs left in the period, and |home_margin_before|<=5 |

## clutch_plays
plays filtered to is_clutch = TRUE (same columns as plays).


## games
One row per game (note: ~9% of games here have no play-by-play; use plays/game_swings for anything event-based).

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| game_date | DATE |  |
| season_start_year | INTEGER | 2022 = the 2022-23 season |
| season_label | VARCHAR | e.g. '2022-23' |
| season_type | VARCHAR | 'Regular Season' or 'Playoffs' |
| home_team_id | VARCHAR |  |
| home_team | VARCHAR |  |
| away_team_id | VARCHAR |  |
| away_team | VARCHAR |  |
| pts_home | INTEGER |  |
| pts_away | INTEGER |  |
| home_won | BOOLEAN | TRUE if home team won |
| winner | VARCHAR | winning team abbreviation |
| loser | VARCHAR | losing team abbreviation |

## game_swings
One row per game (with play-by-play): largest leads/deficits, comeback flags, lead changes.

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| game_date | DATE |  |
| season_start_year | INTEGER |  |
| season_label | VARCHAR |  |
| season_type | VARCHAR |  |
| home_team | VARCHAR |  |
| away_team | VARCHAR |  |
| pts_home | INTEGER |  |
| pts_away | INTEGER |  |
| winner | VARCHAR |  |
| loser | VARCHAR |  |
| home_max_lead | INTEGER | home team's biggest lead |
| away_max_lead | INTEGER | away team's biggest lead |
| winner_max_deficit | INTEGER | biggest deficit the eventual winner faced = biggest lead the loser blew |
| comeback_10 | BOOLEAN | winner trailed by 10+ at some point (15/20 similar) |
| comeback_15 | BOOLEAN |  |
| comeback_20 | BOOLEAN |  |
| lead_changes | BIGINT | from other_stats (official count) |
| times_tied | BIGINT | from other_stats |

## player_shooting
Per player x season x season_type x is_clutch: FGA/FGM/3PA/3PM/FTA/FTM/pts from play-by-play.

| column | type | notes |
|---|---|---|
| player_id | VARCHAR |  |
| player_name | VARCHAR |  |
| season_start_year | INTEGER |  |
| season_label | VARCHAR |  |
| season_type | VARCHAR |  |
| is_clutch | BOOLEAN | TRUE row = clutch plays only; FALSE row = all other plays |
| games | BIGINT | distinct games in which the player had at least one shot/FT in this split |
| fga | BIGINT |  |
| fgm | BIGINT |  |
| fg3a | BIGINT |  |
| fg3m | BIGINT |  |
| fta | BIGINT |  |
| ftm | BIGINT |  |
| pts | HUGEINT | sum of points_scored (approximate, see limits) |

## team_game_clutch
Per team x game: points for/against during clutch plays (only games with at least one clutch play).

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| season_start_year | INTEGER |  |
| season_label | VARCHAR |  |
| season_type | VARCHAR |  |
| team | VARCHAR |  |
| opponent | VARCHAR |  |
| is_home | BOOLEAN | TRUE if team was the home team |
| clutch_pts_for | HUGEINT | points the team scored on clutch plays |
| clutch_pts_against | HUGEINT | points the opponent scored on clutch plays |

## other_stats
Official box extras per game: team_id/abbr home & away, pts_paint, pts_fb (fast break), pts_2nd_chance, largest_lead, lead_changes, times_tied, turnovers (total_turnovers_*, team_turnovers_*), team_rebounds, pts_off_to (points off turnovers).

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| league_id | VARCHAR |  |
| team_id_home | VARCHAR |  |
| team_abbreviation_home | VARCHAR |  |
| team_city_home | VARCHAR |  |
| pts_paint_home | BIGINT |  |
| pts_2nd_chance_home | BIGINT |  |
| pts_fb_home | BIGINT |  |
| largest_lead_home | BIGINT |  |
| lead_changes | BIGINT |  |
| times_tied | BIGINT |  |
| team_turnovers_home | BIGINT |  |
| total_turnovers_home | BIGINT |  |
| team_rebounds_home | BIGINT |  |
| pts_off_to_home | BIGINT |  |
| team_id_away | VARCHAR |  |
| team_abbreviation_away | VARCHAR |  |
| team_city_away | VARCHAR |  |
| pts_paint_away | BIGINT |  |
| pts_2nd_chance_away | BIGINT |  |
| pts_fb_away | BIGINT |  |
| largest_lead_away | BIGINT |  |
| team_turnovers_away | BIGINT |  |
| total_turnovers_away | BIGINT |  |
| team_rebounds_away | BIGINT |  |
| pts_off_to_away | BIGINT |  |

## line_score
Points by quarter and OT per game: pts_qtr1_home .. pts_qtr4_home, pts_ot1_home.., same for _away.

| column | type | notes |
|---|---|---|
| game_date_est | TIMESTAMP |  |
| game_sequence | BIGINT |  |
| game_id | VARCHAR |  |
| team_id_home | VARCHAR |  |
| team_abbreviation_home | VARCHAR |  |
| team_city_name_home | VARCHAR |  |
| team_nickname_home | VARCHAR |  |
| team_wins_losses_home | VARCHAR |  |
| pts_qtr1_home | VARCHAR |  |
| pts_qtr2_home | VARCHAR |  |
| pts_qtr3_home | VARCHAR |  |
| pts_qtr4_home | VARCHAR |  |
| pts_ot1_home | BIGINT |  |
| pts_home | DOUBLE |  |
| team_id_away | VARCHAR |  |
| team_abbreviation_away | VARCHAR |  |
| team_city_name_away | VARCHAR |  |
| team_nickname_away | VARCHAR |  |
| team_wins_losses_away | VARCHAR |  |
| pts_qtr1_away | BIGINT |  |
| pts_qtr2_away | VARCHAR |  |
| pts_qtr3_away | VARCHAR |  |
| pts_qtr4_away | BIGINT |  |
| pts_ot1_away | BIGINT |  |
| pts_away | DOUBLE |  |

## officials
game_id, official_id, first_name, last_name, jersey_num (referees per game).

| column | type | notes |
|---|---|---|
| game_id | VARCHAR |  |
| official_id | VARCHAR |  |
| first_name | VARCHAR |  |
| last_name | VARCHAR |  |
| jersey_num | VARCHAR |  |

## teams
30 teams: id, full_name, abbreviation, nickname, city, state, year_founded.

| column | type | notes |
|---|---|---|
| id | VARCHAR |  |
| full_name | VARCHAR |  |
| abbreviation | VARCHAR |  |
| nickname | VARCHAR |  |
| city | VARCHAR |  |
| state | VARCHAR |  |
| year_founded | DOUBLE |  |

## players
id, full_name, first_name, last_name, is_active (join to plays.player_id = players.id).

| column | type | notes |
|---|---|---|
| id | VARCHAR |  |
| full_name | VARCHAR |  |
| first_name | VARCHAR |  |
| last_name | VARCHAR |  |
| is_active | BIGINT |  |
