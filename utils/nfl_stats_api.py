from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import streamlit as st

ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
ESPN_TEAM_STATS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/{season}/types/{seasontype}/teams/{team_id}/statistics"
)
REQUEST_TIMEOUT = 10

# (display label, ESPN category, ESPN stat name, higher_is_better)
TEAM_STAT_FIELDS = [
    ("Points per game", "scoring", "totalPointsPerGame", True),
    ("Total yards per game", "passing", "yardsPerGame", True),
    ("Passing yards per game", "passing", "netPassingYardsPerGame", True),
    ("Rushing yards per game", "rushing", "rushingYardsPerGame", True),
    ("Third down %", "miscellaneous", "thirdDownConvPct", True),
    ("Red zone scoring %", "miscellaneous", "redzoneScoringPct", True),
    ("Sacks (defense)", "defensive", "sacks", True),
    ("Takeaways", "miscellaneous", "totalTakeaways", True),
    ("Giveaways", "miscellaneous", "totalGiveaways", False),
    ("Turnover differential", "miscellaneous", "turnOverDifferential", True),
    ("Penalty yards", "general", "totalPenaltyYards", False),
    ("Field goal %", "kicking", "fieldGoalPct", True),
]
STAT_LABELS = [f[0] for f in TEAM_STAT_FIELDS]
HIGHER_IS_BETTER = {f[0]: f[3] for f in TEAM_STAT_FIELDS}


def _get_json(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Failed to fetch data from ESPN: {exc}")
        return {}


def _stats_by_name(entry):
    return {s.get("name"): s for s in entry.get("stats", [])}


def _value(stats, name, default=None):
    value = (stats.get(name) or {}).get("value")
    return default if value is None else value


def _display(stats, name):
    return (stats.get(name) or {}).get("displayValue")


STANDINGS_COLUMNS = [
    "team_id", "season", "conference", "division", "team_name", "team_nickname", "abbreviation", "logo_url",
    "color", "alt_color", "in_playoff_position", "wins", "losses", "ties", "win_pct", "points_for", "points_against",
    "point_differential", "playoff_seed", "streak", "record", "home_record", "road_record",
    "division_record", "conference_record", "conference_rank", "division_rank", "updated_at",
]


def get_standings():
    """One row per team with conference, division, record, seed, points and ranks.

    Source: Snowflake NFL_SEASON.PUBLIC.NFL_CONFERENCE_STANDINGS (kept current
    game by game). Falls back to ESPN if Snowflake is unreachable or empty.
    """
    from utils.nfl_data_loader import load_standings
    from utils.snowflake_connector import snowflake_available

    if snowflake_available():
        try:
            df = load_standings()
            if not df.empty:
                df = df.reindex(columns=STANDINGS_COLUMNS)
                df["playoff_seed"] = df["playoff_seed"].astype("Int64")
                return df.sort_values(["conference", "conference_rank"]).reset_index(drop=True)
        except Exception as exc:
            st.warning(f"Snowflake standings unavailable, using ESPN: {exc}")
    return _espn_standings()


@st.cache_data(ttl=1800)
def _espn_standings():
    """ESPN fallback with the same columns as get_standings()."""
    data = _get_json(ESPN_STANDINGS_URL, params={"level": 3})
    season = (data.get("season") or {}).get("year")
    rows = []
    for conference in data.get("children", []):
        conf = conference.get("abbreviation")
        for division in conference.get("children", []):
            for entry in division.get("standings", {}).get("entries", []):
                team = entry.get("team", {})
                stats = _stats_by_name(entry)
                rows.append({
                    "team_id": int(team["id"]),
                    "season": season,
                    "conference": conf,
                    "division": division.get("name"),
                    "team_name": team.get("displayName"),
                    "team_nickname": team.get("name"),
                    "abbreviation": team.get("abbreviation"),
                    "logo_url": next((l.get("href") for l in team.get("logos", [])), None),
                    "color": team.get("color"),
                    "alt_color": team.get("alternateColor"),
                    "wins": int(_value(stats, "wins", 0)),
                    "losses": int(_value(stats, "losses", 0)),
                    "ties": int(_value(stats, "ties", 0)),
                    "win_pct": float(_value(stats, "winPercent", 0.0)),
                    "points_for": int(_value(stats, "pointsFor", 0)),
                    "points_against": int(_value(stats, "pointsAgainst", 0)),
                    "point_differential": int(_value(stats, "pointDifferential", 0)),
                    "playoff_seed": int(_value(stats, "playoffSeed", 0)) or None,
                    "streak": _display(stats, "streak"),
                    "record": _display(stats, "overall"),
                    "home_record": _display(stats, "Home"),
                    "road_record": _display(stats, "Road"),
                    "division_record": _display(stats, "vs. Div."),
                    "conference_record": _display(stats, "vs. Conf."),
                })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Same ordering as the nfl_conference_standings view in setup.sql.
    df = df.sort_values(
        ["conference", "playoff_seed", "win_pct", "point_differential", "points_for"],
        ascending=[True, True, False, False, False],
        na_position="last",
    )
    df["conference_rank"] = df.groupby("conference").cumcount() + 1
    df["in_playoff_position"] = df["playoff_seed"].between(1, 7)
    df["division_rank"] = (
        df.sort_values(["playoff_seed", "win_pct", "point_differential"],
                       ascending=[True, False, False], na_position="last")
        .groupby("division")
        .cumcount() + 1
    )
    return df.reindex(columns=STANDINGS_COLUMNS).reset_index(drop=True)


def _parse_team_stats(payload):
    categories = {
        c.get("name"): {s.get("name"): s.get("value") for s in c.get("stats", [])}
        for c in (payload.get("splits") or {}).get("categories", [])
    }
    return {
        label: categories.get(category, {}).get(name)
        for label, category, name, _ in TEAM_STAT_FIELDS
    }


@st.cache_data(ttl=3600)
def get_team_stats(team_ids, season, seasontype=2):
    """Season stats per team (rows) for the labels in TEAM_STAT_FIELDS (columns)."""
    def fetch(team_id):
        url = ESPN_TEAM_STATS_URL.format(season=season, seasontype=seasontype, team_id=team_id)
        return team_id, _parse_team_stats(_get_json(url))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(fetch, team_ids))
    df = pd.DataFrame.from_dict(results, orient="index")
    df.index.name = "team_id"
    return df.reindex(columns=STAT_LABELS)
