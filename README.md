# NFL Football Season

A Streamlit dashboard for the current NFL season: live scores and play-by-play, standings, stadiums, a playoff bracket builder and the league-wide injury report. Season data lives in Snowflake; live game data comes straight from ESPN.

## Features

- **Score banner** (every page): a rotating ticker of live games (clock, down and distance, possession, red zone) followed by finals from the past seven days. Pauses on hover.
- **Overview**
  - Live games: score, current situation, the last play drawn on a field, and a collapsible play-by-play log. Refreshes every 15 seconds.
  - Upcoming games for the next seven days and completed games from the last seven.
  - Teams on bye this week and next, as team-colored cards with record and division.
  - Projected playoff bracket from the current seeds.
- **Venue**: an interactive map of every stadium with home teams, indoor/outdoor, games played and the next game there, plus a stadium table.
- **Team Standings**: AFC/NFC standings grouped by conference or division, a points-for vs. points-against chart, and a head-to-head comparison of two teams' season stats.
- **Bracket Builder**: seeds 1–7 per conference from the current standings; pick winners round by round through the Super Bowl.
- **Injury Report**: injury designations for all 32 teams, with filters. Refreshes every 15 minutes.
- **Footer** on every page.

## How it works

```
ESPN APIs ──► utils/nfl_snowflake_sync.py ──MERGE──► Snowflake NFL_SEASON.PUBLIC
    │                                                      │
    │  live scores, plays, injuries, team stats            │  teams, venues, schedule,
    ▼                                                      ▼  byes, standings
                         Streamlit app (streamlit_app.py)
```

- **Snowflake is the source of truth** for teams, venues, the full schedule, bye weeks and standings (database `NFL_SEASON`, schema `PUBLIC`; see `setup.sql`). The view `NFL_CONFERENCE_STANDINGS` ranks teams by ESPN's playoff seed, which already applies the NFL tiebreakers.
- **Loading is plain Python**; no Snowflake tasks or external access integrations. `utils/load_nfl_season.py` does a full load, and the app itself runs a game-by-game refresh at most every 2 minutes while it's open. It upserts this week's games and byes, and refreshes standings only when a game newly goes final.
- **ESPN fallback**: standings and byes are read from Snowflake first and fall back to ESPN if Snowflake is unreachable or that data isn't loaded yet.
- **Live data is consistent across the app**: the scoreboard is fetched once per 15-second slot and shared by every view. Each live game's clock, score and possession come from the same ESPN response as its plays, so the banner, the live card and the last play always agree.
- **Caching**: reads use `st.cache_data` (5 minutes for Snowflake, 15 seconds for live ESPN data). Parameterized Snowflake queries bypass `st.connection().query()`'s cache, which ignores query parameters.

## Tech stack

- **Python 3.11+**, **Streamlit 1.51** (`st.navigation`, fragments for timed refreshes)
- **Snowflake** via `st.connection("snowflake")` / `snowflake-connector-python`
- **pandas**, **Plotly** (charts), **Folium** + `streamlit-folium` (stadium map)
- **ESPN public site APIs** (scoreboard, summary, standings, injuries, team stats) via `requests`

## Local development

1. **Create a virtual environment and install dependencies** (Windows PowerShell):

   ```powershell
   python -m venv venv
   venv\Scripts\python.exe -m pip install "streamlit==1.51.0" "plotly>=5.18.0" "pandas>=2.0.0" "snowflake-connector-python[pandas]>=3.12" "snowflake-snowpark-python>=1.14.0" "requests>=2.31.0" pytz "folium>=0.15.0" "streamlit-folium==0.27.2"
   ```

   Use a python.org Python for the venv. The Microsoft Store Python breaks the Snowflake connector, and the app then reports that it can't reach Snowflake.

2. **Configure Snowflake.** Create `.streamlit/secrets.toml` (git-ignored, never commit it):

   ```toml
   [connections.snowflake]
   account = "<account identifier>"
   user = "<user>"
   password = "<password>"
   warehouse = "<warehouse>"
   database = "NFL_SEASON"
   schema = "PUBLIC"
   client_session_keep_alive = true
   ```

3. **Create the schema** by running `setup.sql` in Snowflake (safe to re-run; existing data is kept).

4. **Load the season** from ESPN:

   ```powershell
   venv\Scripts\python.exe -m utils.load_nfl_season            # full load
   venv\Scripts\python.exe -m utils.load_nfl_season --results  # this week's results only
   ```

5. **Run the app**:

   ```powershell
   venv\Scripts\python.exe -m streamlit run streamlit_app.py
   ```

   It opens at http://localhost:8501. Without Snowflake the app still runs on ESPN data, except the Venue page, which needs Snowflake.

## Project layout

```
streamlit_app.py            Entrypoint: page config, CSS, navigation, score banner, sync, footer
app.css                     App-wide styles
setup.sql                   NFL_SEASON tables and the NFL_CONFERENCE_STANDINGS view
pyproject.toml              Dependencies
app_pages/
  0_overview.py             Live games, upcoming/completed games, byes, bracket preview
  1_venue_map.py            Stadium map and table
  2_standings.py            Standings, season chart, team comparison
  3_bracket_builder.py      Interactive playoff bracket
  4_injury_report.py        League-wide injury report
utils/
  snowflake_connector.py    Snowflake connection and parameterized queries
  nfl_data_loader.py        Snowflake reads (cached) and the throttled in-app sync
  nfl_snowflake_sync.py     ESPN fetch + MERGE upserts into NFL_SEASON
  load_nfl_season.py        CLI for full / results-only loads
  nfl_football_api.py       ESPN scoreboard, live state, play-by-play, current week, byes
  nfl_stats_api.py          Standings (Snowflake first, ESPN fallback) and team stats
  nfl_injuries_api.py       ESPN injury report
  nfl_score_banner.py       Rotating score banner
  nfl_field.py              Football field and play-by-play rendering
  nfl_bracket_html.py       Bracket HTML building blocks
  nfl_bracket_preview.py    Projected bracket from current seeds
  nfl_footer.py             Footer
```

Pages live in `app_pages/` rather than `pages/`, so Streamlit's automatic multipage mode can't run them without the entrypoint's CSS, banner and footer.

---

Data powered by Snowflake & made with <3 with CoCo. Built by [Dino Wun](https://www.linkedin.com/in/dinowun).
