"""ESPN -> Snowflake sync for NFL_SEASON.PUBLIC (pure Python, no external access integration).

Runs from the Streamlit app (via st.connection("snowflake").raw_connection) or
from the command line (python -m utils.load_nfl_season). All writes are idempotent
MERGEs, so re-running is safe.

Tables written:
    NFL_TEAMS, NFL_VENUES, NFL_MATCHES, NFL_TEAM_BYES, NFL_TEAM_STANDINGS
NFL_CONFERENCE_STANDINGS is a view over NFL_TEAM_STANDINGS + NFL_TEAMS, so it
updates whenever the standings table does.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
REQUEST_TIMEOUT = 15
REGULAR_SEASON, POSTSEASON = 2, 3
REGULAR_WEEKS = range(1, 19)
POSTSEASON_WEEKS = range(1, 6)
FINAL_STATUSES = {"STATUS_FINAL", "STATUS_FINAL_OVERTIME"}

# ESPN venue records carry no coordinates; these seed NFL_VENUES.LATITUDE/LONGITUDE
# (keyed by ESPN venue id). Existing coordinates in Snowflake are never overwritten
# with NULL, so venues can also be corrected directly in the table.
VENUE_COORDINATES = {
    3970: (33.5276, -112.2626),   # State Farm Stadium
    5348: (33.7554, -84.4008),    # Mercedes-Benz Stadium
    3814: (39.2780, -76.6227),    # M&T Bank Stadium
    11938: (42.7738, -78.7870),   # Highmark Stadium
    3628: (35.2258, -80.8528),    # Bank of America Stadium
    3933: (41.8623, -87.6167),    # Soldier Field
    3874: (39.0955, -84.5161),    # Paycor Stadium
    3679: (41.5061, -81.6995),    # Huntington Bank Field
    3687: (32.7473, -97.0945),    # AT&T Stadium
    3937: (39.7439, -105.0201),   # Empower Field at Mile High
    3727: (42.3400, -83.0456),    # Ford Field
    3798: (44.5013, -88.0622),    # Lambeau Field
    3891: (29.6847, -95.4107),    # NRG (Reliant) Stadium
    3812: (39.7601, -86.1639),    # Lucas Oil Stadium
    3712: (30.3239, -81.6373),    # EverBank Stadium
    3622: (39.0489, -94.4839),    # Arrowhead Stadium
    6501: (36.0909, -115.1833),   # Allegiant Stadium
    7065: (33.9535, -118.3392),   # SoFi Stadium
    3948: (25.9580, -80.2389),    # Hard Rock Stadium
    5239: (44.9736, -93.2575),    # U.S. Bank Stadium
    3738: (42.0909, -71.2643),    # Gillette Stadium
    3493: (29.9511, -90.0812),    # Caesars Superdome
    3839: (40.8135, -74.0745),    # MetLife Stadium
    3806: (39.9008, -75.1675),    # Lincoln Financial Field
    3752: (40.4468, -80.0158),    # Acrisure Stadium
    4738: (37.4030, -121.9700),   # Levi's Stadium
    3673: (47.5952, -122.3316),   # Lumen Field
    3886: (27.9759, -82.5033),    # Raymond James Stadium
    3810: (36.1665, -86.7713),    # Nissan Stadium
    3719: (38.9077, -76.8645),    # Northwest Stadium
    # International series
    8219: (19.3029, -99.1505),    # Estadio Banorte, Mexico City
    11930: (48.2188, 11.6247),    # FC Bayern Munich Stadium
    11931: (-22.9122, -43.2302),  # Maracana, Rio de Janeiro
    9119: (-37.8200, 144.9834),   # Melbourne Cricket Ground
    1353: (40.4531, -3.6883),     # Santiago Bernabeu, Madrid
    1781: (48.9245, 2.3602),      # Stade de France
    5534: (51.6043, -0.0664),     # Tottenham Hotspur Stadium
    2455: (51.5560, -0.2796),     # Wembley Stadium
}


# ---------------------------------------------------------------- ESPN fetch

def _get(url, params=None):
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_naive(iso):
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def fetch_standings():
    """Rows for NFL_TEAM_STANDINGS plus (conference, division) per team."""
    data = _get(STANDINGS_URL, params={"level": 3})
    season = _int((data.get("season") or {}).get("year"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for conference in data.get("children", []):
        for division in conference.get("children", []):
            for entry in division.get("standings", {}).get("entries", []):
                stats = {s.get("name"): s for s in entry.get("stats", [])}

                def value(name, default=0):
                    v = (stats.get(name) or {}).get("value")
                    return default if v is None else v

                def display(name):
                    return (stats.get(name) or {}).get("displayValue")

                rows.append({
                    "TEAM_ID": _int(entry["team"]["id"]),
                    "SEASON": season,
                    "CONFERENCE": conference.get("abbreviation"),
                    "DIVISION": division.get("name"),
                    "WINS": int(value("wins")),
                    "LOSSES": int(value("losses")),
                    "TIES": int(value("ties")),
                    "WIN_PCT": float(value("winPercent", 0.0)),
                    "POINTS_FOR": int(value("pointsFor")),
                    "POINTS_AGAINST": int(value("pointsAgainst")),
                    "POINT_DIFFERENTIAL": int(value("pointDifferential")),
                    "PLAYOFF_SEED": int(value("playoffSeed")) or None,
                    "STREAK": display("streak"),
                    "HOME_RECORD": display("Home"),
                    "ROAD_RECORD": display("Road"),
                    "DIVISION_RECORD": display("vs. Div."),
                    "CONFERENCE_RECORD": display("vs. Conf."),
                    "UPDATED_AT": now,
                })
    return season, rows


def fetch_teams(standings_rows):
    """Rows for NFL_TEAMS; conference/division come from the standings feed."""
    groups = {r["TEAM_ID"]: (r["CONFERENCE"], r["DIVISION"]) for r in standings_rows}
    data = _get(f"{SITE}/teams")
    rows = []
    for item in (data.get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", []):
        team = item.get("team", {})
        team_id = _int(team.get("id"))
        conference, division = groups.get(team_id, (None, None))
        rows.append({
            "TEAM_ID": team_id,
            "TEAM_NAME": team.get("displayName"),
            "TEAM_NICKNAME": team.get("name"),
            "CITY": team.get("location"),
            "COLOR": team.get("color"),
            "ALT_COLOR": team.get("alternateColor"),
            "LOGO_URL": next((l.get("href") for l in team.get("logos", [])), None),
            "ABBREVIATION": team.get("abbreviation"),
            "CONFERENCE": conference,
            "DIVISION": division,
        })
    return rows


def _parse_scoreboard(data, season):
    """(match rows, venue rows, bye rows) from one scoreboard payload."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    week = _int((data.get("week") or {}).get("number"))
    season_type = _int((data.get("season") or {}).get("type"))
    matches, venues = [], {}
    for event in data.get("events", []):
        for comp in event.get("competitions", []):
            teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            venue = comp.get("venue") or {}
            venue_id = _int(venue.get("id"))
            if venue_id:
                address = venue.get("address") or {}
                lat_lon = VENUE_COORDINATES.get(venue_id, (None, None))
                venues[venue_id] = {
                    "VENUE_ID": venue_id,
                    "VENUE_NAME": venue.get("fullName"),
                    "CITY": address.get("city"),
                    "STATE": address.get("state"),
                    "ZIP_CODE": address.get("zipCode"),
                    "COUNTRY": address.get("country"),
                    "INDOOR": venue.get("indoor"),
                    "LATITUDE": lat_lon[0],
                    "LONGITUDE": lat_lon[1],
                }
            status = ((comp.get("status") or event.get("status") or {}).get("type") or {}).get("name")
            broadcasts = ", ".join(n for b in comp.get("broadcasts", []) for n in b.get("names", []))
            matches.append({
                "MATCH_ID": _int(event.get("id")),
                "SEASON": _int((event.get("season") or {}).get("year")) or season,
                "SEASON_TYPE": _int((event.get("season") or {}).get("type")) or season_type,
                "WEEK": _int((event.get("week") or {}).get("number")) or week,
                "HOME_TEAM_ID": _int((home.get("team") or {}).get("id") or home.get("id")),
                "AWAY_TEAM_ID": _int((away.get("team") or {}).get("id") or away.get("id")),
                "VENUE_ID": venue_id,
                "MATCH_DATE": _utc_naive(event.get("date")),
                "NEUTRAL_SITE": bool(comp.get("neutralSite")),
                "STATUS": status,
                "HOME_SCORE": _int(home.get("score")),
                "AWAY_SCORE": _int(away.get("score")),
                "BROADCASTS": broadcasts or None,
                "UPDATED_AT": now,
            })
    byes = []
    if season_type == REGULAR_SEASON:
        byes = [
            {"SEASON": season, "TEAM_ID": _int(t.get("id")), "BYE_WEEK": week}
            for t in (data.get("week") or {}).get("teamsOnBye", [])
        ]
    return matches, list(venues.values()), byes


def fetch_schedule(season, include_postseason=True):
    """Every regular-season (and posted postseason) game for a season."""
    requests_to_make = [(REGULAR_SEASON, w) for w in REGULAR_WEEKS]
    if include_postseason:
        requests_to_make += [(POSTSEASON, w) for w in POSTSEASON_WEEKS]

    def one(args):
        season_type, week = args
        return _get(f"{SITE}/scoreboard", params={"week": week, "seasontype": season_type, "season": season, "limit": 100})

    with ThreadPoolExecutor(max_workers=6) as pool:
        payloads = list(pool.map(one, requests_to_make))

    matches, venues, byes = {}, {}, {}
    for payload in payloads:
        m, v, b = _parse_scoreboard(payload, season)
        matches.update({r["MATCH_ID"]: r for r in m})
        venues.update({r["VENUE_ID"]: r for r in v})
        byes.update({r["TEAM_ID"]: r for r in b})
    return list(matches.values()), list(venues.values()), list(byes.values())


def fetch_current_week(season):
    """Games on ESPN's current scoreboard (cheap; used for game-by-game refresh)."""
    return _parse_scoreboard(_get(f"{SITE}/scoreboard", params={"limit": 100}), season)


# ---------------------------------------------------------------- Snowflake writes

TABLE_KEYS = {
    "NFL_TEAMS": ["TEAM_ID"],
    "NFL_VENUES": ["VENUE_ID"],
    "NFL_MATCHES": ["MATCH_ID"],
    "NFL_TEAM_BYES": ["SEASON", "TEAM_ID"],
    "NFL_TEAM_STANDINGS": ["TEAM_ID"],
}
# Columns that keep their Snowflake value when the incoming value is NULL.
KEEP_EXISTING = {"NFL_VENUES": {"LATITUDE", "LONGITUDE"}}


def upsert(conn, table, rows):
    """MERGE rows (list of dicts with identical keys) into NFL_SEASON.PUBLIC.<table>."""
    if not rows:
        return 0
    if table not in TABLE_KEYS:
        raise ValueError(f"Unknown table {table}")
    cols = list(rows[0].keys())
    keys = TABLE_KEYS[table]
    target = f"NFL_SEASON.PUBLIC.{table}"
    stage = f"NFL_SEASON.PUBLIC.TMP_{table}_SYNC"
    keep = KEEP_EXISTING.get(table, set())

    cur = conn.cursor()
    try:
        cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {stage} LIKE {target}")
        placeholders = ", ".join(["?"] * len(cols))
        cur.executemany(
            f"INSERT INTO {stage} ({', '.join(cols)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in cols) for r in rows],
        )
        on = " AND ".join(f"t.{k} = s.{k}" for k in keys)
        updates = ", ".join(
            f"t.{c} = COALESCE(s.{c}, t.{c})" if c in keep else f"t.{c} = s.{c}"
            for c in cols if c not in keys
        )
        cur.execute(
            f"MERGE INTO {target} t USING {stage} s ON {on} "
            f"WHEN MATCHED THEN UPDATE SET {updates} "
            f"WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})"
        )
        affected = cur.rowcount
        cur.execute(f"DROP TABLE IF EXISTS {stage}")
        return affected
    finally:
        cur.close()


def final_match_ids(conn):
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT MATCH_ID FROM NFL_SEASON.PUBLIC.NFL_MATCHES WHERE STATUS IN ('STATUS_FINAL', 'STATUS_FINAL_OVERTIME')"
        )
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


# ---------------------------------------------------------------- entry points

def sync_all(conn, include_postseason=True):
    """Full load: teams, venues, full schedule, byes, standings."""
    season, standings = fetch_standings()
    teams = fetch_teams(standings)
    matches, venues, byes = fetch_schedule(season, include_postseason)
    counts = {
        "NFL_TEAMS": upsert(conn, "NFL_TEAMS", teams),
        "NFL_VENUES": upsert(conn, "NFL_VENUES", venues),
        "NFL_MATCHES": upsert(conn, "NFL_MATCHES", matches),
        "NFL_TEAM_BYES": upsert(conn, "NFL_TEAM_BYES", byes),
        "NFL_TEAM_STANDINGS": upsert(conn, "NFL_TEAM_STANDINGS", standings),
    }
    return {"season": season, "rows": counts}


def sync_results(conn):
    """Game-by-game refresh: upsert this week's games and byes; refresh standings only if a game newly went final."""
    payload = _get(f"{SITE}/scoreboard", params={"limit": 100})
    season = _int((payload.get("season") or {}).get("year"))
    matches, venues, byes = _parse_scoreboard(payload, season)
    known_finals = final_match_ids(conn)
    new_finals = sorted(
        m["MATCH_ID"] for m in matches
        if m["STATUS"] in FINAL_STATUSES and m["MATCH_ID"] not in known_finals
    )
    upsert(conn, "NFL_VENUES", venues)
    upsert(conn, "NFL_MATCHES", matches)
    upsert(conn, "NFL_TEAM_BYES", byes)
    standings_updated = False
    if new_finals:
        _, standings = fetch_standings()
        upsert(conn, "NFL_TEAM_STANDINGS", standings)
        standings_updated = True
    return {"games": len(matches), "new_finals": new_finals, "standings_updated": standings_updated}
