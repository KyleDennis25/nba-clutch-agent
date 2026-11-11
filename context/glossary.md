# Glossary, conventions and limits

## Coverage
- Seasons 2015-16 to 2022-23, regular season + playoffs. 9,276 games with play-by-play (4,313,409 events) out of 10,187 games in `games`. The most recent data is June 2023; nothing after the 2022-23 season exists.
- A few games per season are missing play-by-play. 2019-20 and 2020-21 are shortened/odd seasons (COVID bubble/short schedule): compare totals across seasons carefully, use rates not counts.
- Games with pbp per season:  2015-16 Playoffs 73; 2015-16 Regular 1121; 2016-17 Playoffs 74; 2016-17 Regular 1129; 2017-18 Playoffs 72; 2017-18 Regular 1128; 2018-19 Playoffs 78; 2018-19 Regular 1122; 2019-20 Playoffs 76; 2019-20 Regular 963; 2020-21 Playoffs 77; 2020-21 Regular 988; 2021-22 Playoffs 82; 2021-22 Regular 1113; 2022-23 Playoffs 74; 2022-23 Regular 1106

## Key conventions
- Raw feed: `score` is 'VISITOR - HOME' and `scoremargin` is HOME - VISITOR ('TIE' = 0). The `plays` view already fixes this: use home_score, away_score, home_margin.
- Team in `plays`: acting_team/acting_side. Home team = games.home_team. To get a team's margin: `CASE WHEN acting_side='HOME' THEN home_margin ELSE -home_margin END` (or join games and compare with the team).
- Period 1-4 are 12:00 quarters; 5+ are 5:00 overtimes. Clock counts DOWN (`secs_left_period`).
- season_id in raw data = type digit + start year ('22022' = 2022-23 regular season). Views expose season_start_year, season_label, season_type instead.
- Team abbreviations are stable in this window (BKN, CHA, NOP, OKC, ...). See teams.md.

## Clutch definition (used by is_clutch)
Clutch play = 4th quarter or overtime, at most 5:00 left in that period, and the score within 5 points (either way) going INTO the play (|home_margin_before| <= 5). There are 201,140 clutch plays in 4,678 games. Because the window is evaluated play by play, a game can enter and leave clutch time. Always compare clutch vs non-clutch (is_clutch FALSE) and report sample sizes (FGA, games).

## Event types (plays.event_type / eventmsgtype)
| event_type | code | rows | notes |
|---|---|---|---|
| MADE_SHOT | 1 | 746,063 | field goal made; player=shooter, player2=assister |
| MISSED_SHOT | 2 | 871,613 | field goal missed; player3=blocker |
| FREE_THROW | 3 | 421,569 | free throw (made unless description has MISS) |
| REBOUND | 4 | 967,951 | player=rebounder; team rebounds have no player |
| TURNOVER | 5 | 261,023 | player=who turned it over, player2=stealer |
| FOUL | 6 | 384,270 | player=fouler, player2=fouled |
| VIOLATION | 7 | 16,030 | e.g. delay of game, kicked ball |
| SUBSTITUTION | 8 | 428,018 | player=sub out, player2=sub in |
| TIMEOUT | 9 | 107,744 | acting_side = team calling it |
| JUMP_BALL | 10 | 16,065 |  |
| EJECTION | 11 | 580 |  |
| PERIOD_START | 12 | 37,695 |  |
| PERIOD_END | 13 | 37,695 |  |
| INSTANT_REPLAY | 18 | 17,093 | replay review |

## Shot descriptions
shot_kind and shot_distance_ft are parsed from the play text. FG% = fgm/fga; eFG% = (fgm + 0.5*fg3m)/fga; TS% = pts/(2*(fga+0.44*fta)). Free throws are event_type FREE_THROW (not counted in fga).

## Limits (say so when asked)
- NO shot x/y locations (only distance in feet, missing for some dunks/tips) and no shot-clock, tracking, defender, lineup/on-court, or possession data. Defense can only be inferred from blocks, steals, opponent scoring.
- No play-by-play after June 2023. No betting/odds data (out of scope).
- points_scored is parsed from descriptions; per-game sums differ from the official score in ~4% of games (usually by 2-3 points). Use home_score/away_score/home_margin for score state. Final scores reconstructed from the running score match the official score in all games.
- Clock and event order in the feed have rare glitches (late-added rows); running score uses the running maximum.
- Small samples: single-season clutch FGA is often < 100 per player; warn and prefer multi-season pooling.
- Causal questions (what 'causes' a blown lead) can only be answered as associations.
