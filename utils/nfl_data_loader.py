"""Reads from Snowflake NFL_SEASON.PUBLIC, plus the app-side game-by-game sync.

Snowflake is the source of truth for teams, venues, the season schedule, byes
and standings. Live scores, play-by-play, injuries and per-team season stats
still come straight from ESPN (see nfl_football_api / nfl_injuries_api /
nfl_stats_api). Every query is parameterized; no user input is formatted into SQL.
"""
import logging
import threading
import time

import pandas as pd
import streamlit as st

from utils.snowflake_connector import get_connection, lower_columns, run_query

_LOG = logging.getLogger(__name__)

CONFERENCES = ("AFC", "NFC")
DB = "NFL_SEASON.PUBLIC"
SYNC_INTERVAL_SECONDS = 120
CACHE_TTL = 300


# ---------------------------------------------------------------- reads

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_teams():
    """32 teams: id, names, abbreviation, colors, logo, conference, division."""
    return lower_columns(run_query(f"""
        SELECT TEAM_ID, TEAM_NAME, TEAM_NICKNAME, CITY, ABBREVIATION, CONFERENCE, DIVISION,
               COLOR, ALT_COLOR, LOGO_URL
        FROM {DB}.NFL_TEAMS
        ORDER BY TEAM_NAME
    """, ttl=CACHE_TTL))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_venues():
    """Venues with coordinates, home teams (non-neutral games), and the next scheduled game there."""
    return lower_columns(run_query(f"""
        WITH home AS (
            SELECT m.VENUE_ID,
                   ARRAY_AGG(DISTINCT t.ABBREVIATION) WITHIN GROUP (ORDER BY t.ABBREVIATION) AS HOME_TEAMS,
                   ARRAY_AGG(DISTINCT t.CONFERENCE) AS CONFERENCES
            FROM {DB}.NFL_MATCHES m
            JOIN {DB}.NFL_TEAMS t ON t.TEAM_ID = m.HOME_TEAM_ID
            WHERE NOT COALESCE(m.NEUTRAL_SITE, FALSE)
            GROUP BY m.VENUE_ID
        ),
        games AS (
            SELECT m.VENUE_ID,
                   COUNT(*) AS GAMES,
                   MIN(IFF(m.STATUS = 'STATUS_SCHEDULED' AND m.MATCH_DATE >= SYSDATE(), m.MATCH_DATE, NULL)) AS NEXT_GAME_UTC
            FROM {DB}.NFL_MATCHES m
            JOIN {DB}.NFL_TEAMS h ON h.TEAM_ID = m.HOME_TEAM_ID
            GROUP BY m.VENUE_ID
        ),
        next_game AS (
            SELECT m.VENUE_ID, a.ABBREVIATION || ' @ ' || h.ABBREVIATION AS NEXT_MATCHUP
            FROM {DB}.NFL_MATCHES m
            JOIN games g ON g.VENUE_ID = m.VENUE_ID AND g.NEXT_GAME_UTC = m.MATCH_DATE
            JOIN {DB}.NFL_TEAMS h ON h.TEAM_ID = m.HOME_TEAM_ID
            JOIN {DB}.NFL_TEAMS a ON a.TEAM_ID = m.AWAY_TEAM_ID
            QUALIFY ROW_NUMBER() OVER (PARTITION BY m.VENUE_ID ORDER BY m.MATCH_ID) = 1
        )
        SELECT v.VENUE_ID, v.VENUE_NAME, v.CITY, v.STATE, v.ZIP_CODE, v.COUNTRY, v.INDOOR,
               v.LATITUDE, v.LONGITUDE,
               ARRAY_TO_STRING(COALESCE(home.HOME_TEAMS, ARRAY_CONSTRUCT()), ',') AS HOME_TEAMS,
               ARRAY_TO_STRING(COALESCE(home.CONFERENCES, ARRAY_CONSTRUCT()), ',') AS CONFERENCES,
               COALESCE(games.GAMES, 0) AS GAMES,
               games.NEXT_GAME_UTC, next_game.NEXT_MATCHUP
        FROM {DB}.NFL_VENUES v
        LEFT JOIN home ON home.VENUE_ID = v.VENUE_ID
        LEFT JOIN games ON games.VENUE_ID = v.VENUE_ID
        LEFT JOIN next_game ON next_game.VENUE_ID = v.VENUE_ID
        ORDER BY v.VENUE_NAME
    """, ttl=CACHE_TTL))


_MATCH_SELECT = f"""
    SELECT m.MATCH_ID, m.SEASON, m.SEASON_TYPE, m.WEEK, m.MATCH_DATE, m.STATUS,
           m.NEUTRAL_SITE, m.BROADCASTS, m.HOME_SCORE, m.AWAY_SCORE,
           m.HOME_TEAM_ID, h.TEAM_NAME AS HOME_TEAM_NAME, h.ABBREVIATION AS HOME_ABBR, h.LOGO_URL AS HOME_LOGO,
           m.AWAY_TEAM_ID, a.TEAM_NAME AS AWAY_TEAM_NAME, a.ABBREVIATION AS AWAY_ABBR, a.LOGO_URL AS AWAY_LOGO,
           m.VENUE_ID, v.VENUE_NAME, v.CITY AS VENUE_CITY
    FROM {DB}.NFL_MATCHES m
    JOIN {DB}.NFL_TEAMS h ON h.TEAM_ID = m.HOME_TEAM_ID   -- inner joins drop TBD postseason placeholders
    JOIN {DB}.NFL_TEAMS a ON a.TEAM_ID = m.AWAY_TEAM_ID
    LEFT JOIN {DB}.NFL_VENUES v ON v.VENUE_ID = m.VENUE_ID
"""


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_matches(season=None, week=None):
    """Season schedule (all statuses), optionally filtered by season and week."""
    sql = _MATCH_SELECT + " WHERE (? IS NULL OR m.SEASON = ?) AND (? IS NULL OR m.WEEK = ?) ORDER BY m.MATCH_DATE"
    return lower_columns(run_query(sql, params=[season, season, week, week], ttl=CACHE_TTL))


@st.cache_data(ttl=60, show_spinner=False)
def load_upcoming_matches(days=7, limit=8):
    """Scheduled games kicking off in the next `days` days (MATCH_DATE is stored as UTC)."""
    sql = _MATCH_SELECT + """
        WHERE m.STATUS = 'STATUS_SCHEDULED'
          AND m.MATCH_DATE >= SYSDATE()
          AND m.MATCH_DATE < DATEADD(day, ?, SYSDATE())
        ORDER BY m.MATCH_DATE
        LIMIT ?
    """
    return lower_columns(run_query(sql, params=[int(days), int(limit)], ttl=60))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_standings(conference=None):
    """Conference-ranked standings from the NFL_CONFERENCE_STANDINGS view (lower-case columns)."""
    if conference is not None:
        conference = conference.upper()
        if conference not in CONFERENCES:
            raise ValueError(f"conference must be one of {CONFERENCES}, got {conference!r}")
    sql = f"""
        SELECT * FROM {DB}.NFL_CONFERENCE_STANDINGS
        WHERE (? IS NULL OR CONFERENCE = ?)
        ORDER BY CONFERENCE, CONFERENCE_RANK, TEAM_NAME
    """
    return lower_columns(run_query(sql, params=[conference, conference], ttl=CACHE_TTL))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_byes(season, week):
    """Teams on bye for a season week, with team details."""
    sql = f"""
        SELECT b.SEASON, b.BYE_WEEK, t.TEAM_ID, t.TEAM_NAME, t.TEAM_NICKNAME, t.CITY, t.ABBREVIATION,
               t.COLOR, t.ALT_COLOR, t.LOGO_URL
        FROM {DB}.NFL_TEAM_BYES b
        JOIN {DB}.NFL_TEAMS t ON t.TEAM_ID = b.TEAM_ID
        WHERE b.SEASON = ? AND b.BYE_WEEK = ?
        ORDER BY t.TEAM_NAME
    """
    return lower_columns(run_query(sql, params=[int(season), int(week)], ttl=CACHE_TTL))


def split_standings_by_conference(df: pd.DataFrame) -> dict:
    """{'AFC': df, 'NFC': df} for rendering side-by-side tables."""
    return {conf: df[df["conference"] == conf].reset_index(drop=True) for conf in CONFERENCES}


# ---------------------------------------------------------------- game-by-game sync

@st.cache_resource
def _sync_state():
    """Process-wide: one sync at a time across all sessions, at most every SYNC_INTERVAL_SECONDS."""
    return {"lock": threading.Lock(), "last_run": 0.0, "last_result": None}


def maybe_sync_results():
    """Push this week's results to Snowflake; refresh standings when a game newly goes final.

    Cheap to call on every rerun: it returns immediately unless the interval has
    passed and no other session is already syncing.
    """
    from utils.nfl_snowflake_sync import sync_results

    state = _sync_state()
    if time.time() - state["last_run"] < SYNC_INTERVAL_SECONDS:
        return state["last_result"]
    if not state["lock"].acquire(blocking=False):
        return state["last_result"]
    try:
        state["last_run"] = time.time()
        result = sync_results(get_connection().raw_connection)
        state["last_result"] = result
        if result.get("new_finals"):
            # New finals change the schedule and the standings view: drop cached reads.
            for fn in (load_standings, load_matches, load_upcoming_matches, load_venues, load_byes):
                fn.clear()
            _LOG.info("Synced %d new final(s) to Snowflake: %s", len(result["new_finals"]), result["new_finals"])
        return result
    except Exception as exc:
        _LOG.warning("Snowflake result sync failed: %s", exc)
        return state["last_result"]
    finally:
        state["lock"].release()
