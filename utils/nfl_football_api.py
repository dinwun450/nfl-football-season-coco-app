import logging
import streamlit as st
import requests
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytz

ESPN_SITE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
ESPN_API_URL = f"{ESPN_SITE_URL}/scoreboard"
ESPN_TEAMS_URL = f"{ESPN_SITE_URL}/teams"
ESPN_SUMMARY_URL = f"{ESPN_SITE_URL}/summary"

ET_TZ = pytz.timezone("America/New_York")
REQUEST_TIMEOUT = 10
# One refresh cadence for every live surface (banner, live cards, play-by-play).
LIVE_REFRESH_SECONDS = 15

LIVE_STATUSES = {
    "STATUS_IN_PROGRESS",
    "STATUS_HALFTIME",
    "STATUS_END_PERIOD",
    "STATUS_OVERTIME",
    "STATUS_DELAYED",
}
UPCOMING_STATUSES = {"STATUS_SCHEDULED"}
FINAL_STATUSES = {"STATUS_FINAL", "STATUS_FINAL_OVERTIME"}


def _get_date_range():
    """Seven-day radius around today (ET)."""
    today = datetime.now(ET_TZ).date()
    return today - timedelta(days=7), today + timedelta(days=7)


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _request_scoreboard(dates=None, week=None, seasontype=None, season=None):
    """Uncached scoreboard request; returns {} on failure."""
    params = {"limit": 1000}
    if dates:
        params["dates"] = dates
    if week:
        params["week"] = week
    if seasontype:
        params["seasontype"] = seasontype
    if season:
        params["season"] = season
    try:
        response = requests.get(ESPN_API_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        st.error(f"Failed to reach ESPN API: {exc}")
        return {}
    if response.status_code != 200:
        st.error(f"Failed to fetch data from ESPN API. Status code: {response.status_code}")
        return {}
    return response.json()


@st.cache_data(ttl=LIVE_REFRESH_SECONDS)
def _fetch_scoreboard(dates=None, week=None, seasontype=None, season=None):
    return _request_scoreboard(dates=dates, week=week, seasontype=seasontype, season=season)


def _fetch_window_events():
    """All events in the seven-day radius from the shared snapshot.

    Every caller in the same LIVE_REFRESH_SECONDS slot (score banner, live
    cards, upcoming list) gets the identical snapshot, so clocks and scores
    never disagree across the app.
    """
    return _window_snapshot(int(time.time() // LIVE_REFRESH_SECONDS))


@st.cache_data(ttl=LIVE_REFRESH_SECONDS * 4, max_entries=4, show_spinner=False)
def _window_snapshot(slot):
    """Fetch the window once per time slot (slot is only the cache key).

    ESPN's documented `dates=YYYYMMDD-YYYYMMDD` range currently returns no
    events, so each day is fetched individually and de-duplicated by event id.
    """
    start_date, end_date = _get_date_range()
    days = [
        (start_date + timedelta(days=i)).strftime("%Y%m%d")
        for i in range((end_date - start_date).days + 1)
    ]
    # Uncached per-day requests: one consistent fetch per slot, not 15 caches
    # expiring at different moments.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda d: _request_scoreboard(dates=d), days))
    events = {}
    for data in results:
        for event in data.get("events", []):
            events[event.get("id")] = event
    return list(events.values())


def _normalize_team(competitor):
    """Map an ESPN competitor to the nfl_teams columns (+ game-level score/record)."""
    if not competitor:
        return None
    team = competitor.get("team", {})
    logo = team.get("logo") or next((l.get("href") for l in team.get("logos", [])), None)
    records = competitor.get("records") or []
    return {
        "team_id": _to_int(team.get("id") or competitor.get("id")),
        "team_name": team.get("displayName"),
        "team_nickname": team.get("name") or team.get("shortDisplayName"),
        "city": team.get("location"),
        "color": team.get("color"),
        "alt_color": team.get("alternateColor"),
        "logo_url": logo,
        "abbreviation": team.get("abbreviation"),
        "score": _to_int(competitor.get("score")),
        "record": records[0].get("summary") if records else None,
    }


def _normalize_venue(competition):
    """Map an ESPN venue to the nfl_venues columns."""
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}
    return {
        "venue_id": _to_int(venue.get("id")),
        "venue_name": venue.get("fullName"),
        "city": address.get("city"),
        "state": address.get("state"),
        "zip_code": address.get("zipCode"),
    }


def _map_status(status_name, period):
    if status_name == "STATUS_IN_PROGRESS":
        return "In Progress"
    if status_name == "STATUS_OVERTIME":
        return "Overtime"
    if status_name == "STATUS_HALFTIME":
        return "Halftime"
    if status_name == "STATUS_END_PERIOD":
        return f"End of Q{period}"
    if status_name == "STATUS_FINAL":
        return "Final"
    if status_name == "STATUS_DELAYED":
        return "Delayed"
    if status_name == "STATUS_SCHEDULED":
        return "Scheduled"
    if status_name == "STATUS_POSTPONED":
        return "Postponed"
    if status_name == "STATUS_CANCELED":
        return "Canceled"
    return status_name


def normalize_espn(event, competition=None, status=None):
    """Flatten an ESPN scoreboard event into a dict aligned with setup.sql.

    Top-level keys mirror nfl_matches; `home_team`/`away_team` mirror nfl_teams
    and `venue` mirrors nfl_venues. Extra keys are for display only.
    """
    competition = competition or (event.get("competitions") or [{}])[0]
    status = status or competition.get("status") or event.get("status") or {}
    status_type = status.get("type", {})

    competitors = competition.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    home_team = _normalize_team(home)
    away_team = _normalize_team(away)
    venue = _normalize_venue(competition)

    status_name = status_type.get("name")
    period = status.get("period", 0)

    match_date = None
    date_display = ""
    time_et_display = ""
    utc_iso = ""
    event_date = event.get("date", "")
    if event_date:
        try:
            utc_dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
            utc_iso = utc_dt.isoformat()
            # TIMESTAMP_NTZ: store naive UTC
            match_date = utc_dt.astimezone(pytz.utc).replace(tzinfo=None)
            et_dt = utc_dt.astimezone(ET_TZ)
            date_display = et_dt.strftime("%b %d, %Y")
            # %-I is not portable (fails on Windows)
            time_et_display = et_dt.strftime("%I:%M %p ET").lstrip("0")
        except ValueError:
            pass

    situation = competition.get("situation") or {}
    broadcasts = [n for b in competition.get("broadcasts", []) for n in b.get("names", [])]

    return {
        # nfl_matches
        "match_id": _to_int(event.get("id")),
        "week": _to_int((event.get("week") or {}).get("number")),
        "home_team_id": home_team["team_id"] if home_team else None,
        "away_team_id": away_team["team_id"] if away_team else None,
        "venue_id": venue["venue_id"],
        "match_date": match_date,
        # related entities
        "home_team": home_team,
        "away_team": away_team,
        "venue": venue,
        # display / live state
        "name": event.get("name"),
        "short_name": event.get("shortName"),
        "season": _to_int((event.get("season") or {}).get("year")),
        "season_type": _to_int((event.get("season") or {}).get("type")),
        "status_name": status_name,
        "status": _map_status(status_name, period),
        "status_detail": status_type.get("shortDetail") or status_type.get("detail"),
        "completed": bool(status_type.get("completed")),
        "clock": status.get("displayClock", "0:00"),
        "quarter": period,
        "down_distance": situation.get("downDistanceText"),
        "possession_team_id": _to_int(situation.get("possession")),
        "is_red_zone": bool(situation.get("isRedZone")),
        "broadcasts": broadcasts,
        "utc_iso": utc_iso,
        "date_display": date_display,
        "time_et_display": time_et_display,
    }


def _normalize_events(events, statuses):
    matches = []
    for event in events:
        for competition in event.get("competitions", []):
            status = competition.get("status") or event.get("status") or {}
            if status.get("type", {}).get("name") in statuses:
                matches.append(normalize_espn(event, competition, status))
    return sorted(matches, key=lambda m: m["utc_iso"])


def get_live_matches():
    """Games in progress: schedule from the shared snapshot, state from each game's summary."""
    return [_with_summary_state(m) for m in _normalize_events(_fetch_window_events(), LIVE_STATUSES)]


def get_completed_matches():
    """Final games from the past seven days, most recent first."""
    matches = _normalize_events(_fetch_window_events(), FINAL_STATUSES)
    return sorted(matches, key=lambda m: m["utc_iso"], reverse=True)


def get_upcoming_matches():
    """Scheduled games within the next seven days."""
    now = datetime.now(pytz.utc)
    _, end_date = _get_date_range()
    cutoff = ET_TZ.localize(datetime.combine(end_date, datetime.max.time())).astimezone(pytz.utc)
    matches = _normalize_events(_fetch_window_events(), UPCOMING_STATUSES)
    return [
        m for m in matches
        if not m["utc_iso"] or now <= datetime.fromisoformat(m["utc_iso"]) <= cutoff
    ]


@st.cache_data(ttl=86400)
def _get_all_teams():
    try:
        response = requests.get(ESPN_TEAMS_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        st.error(f"Failed to fetch NFL teams: {exc}")
        return {}
    leagues = response.json().get("sports", [{}])[0].get("leagues", [{}])
    teams = {}
    for item in leagues[0].get("teams", []):
        normalized = _normalize_team({"team": item.get("team", {})})
        normalized.pop("score", None)
        normalized.pop("record", None)
        teams[normalized["team_id"]] = normalized
    return teams


@st.cache_data(ttl=21600, show_spinner=False)
def _season_calendar():
    """Regular-season weeks from ESPN: [(week, start_utc, end_utc)], plus the season year."""
    data = _request_scoreboard()
    season = _to_int((data.get("season") or {}).get("year"))
    weeks = []
    for group in (data.get("leagues") or [{}])[0].get("calendar", []):
        if str(group.get("value")) != "2":  # regular season only
            continue
        for entry in group.get("entries", []):
            try:
                weeks.append((
                    _to_int(entry.get("value")),
                    datetime.fromisoformat(entry["startDate"].replace("Z", "+00:00")),
                    datetime.fromisoformat(entry["endDate"].replace("Z", "+00:00")),
                ))
            except (KeyError, ValueError):
                continue
    return season, weeks


@st.cache_data(ttl=600, show_spinner=False)
def _week_is_complete(season, week):
    """True once every game of a regular-season week is final (e.g. after Monday night)."""
    data = _request_scoreboard(week=week, seasontype=2, season=season)
    statuses = [
        (comp.get("status") or event.get("status") or {}).get("type", {}).get("name")
        for event in data.get("events", [])
        for comp in event.get("competitions", [])
    ]
    return bool(statuses) and all(s in FINAL_STATUSES for s in statuses)


def get_current_week(now=None):
    """(season, week) of the current regular-season week, else (season, None).

    Starts from ESPN's calendar boundaries (weeks officially roll over Wednesday
    ~3 AM ET), then advances to the next week as soon as every game of the
    calendar week is final, so the app flips after Monday Night Football.
    """
    now = now or datetime.now(pytz.utc)
    season, weeks = _season_calendar()
    week_numbers = {w for w, _, _ in weeks}
    for week, start, end in weeks:
        if start <= now <= end:
            if week + 1 in week_numbers and _week_is_complete(season, week):
                return season, week + 1
            return season, week
    return season, None


def get_bye_teams(week=None, season=None, seasontype=2):
    """Teams on BYE for a week (defaults to the current calendar week).

    Returns rows shaped like nfl_team_byes (team_id, bye_week) plus team details.
    The week is part of the cache key, so the list refreshes the moment a new
    week starts.
    """
    if week is None:
        cal_season, week = get_current_week()
        season = season or cal_season
        if week is None:
            return []  # outside the regular season: no byes
    snowflake_byes = _snowflake_bye_teams(week, season)
    if snowflake_byes is not None:
        return snowflake_byes
    return _bye_teams_for_week(week, season, seasontype)


def _snowflake_bye_teams(week, season):
    """Byes from NFL_SEASON.PUBLIC.NFL_TEAM_BYES, or None to fall back to ESPN.

    A week whose games cover all 32 teams is a genuine "no byes" week (returns []).
    """
    from utils.nfl_data_loader import load_byes, load_matches
    from utils.snowflake_connector import snowflake_available

    if not season or not snowflake_available():
        return None
    try:
        byes = load_byes(season, week)
        if byes.empty:
            games = load_matches(season, week)
            playing = set(games["home_team_id"]) | set(games["away_team_id"])
            if len(playing) < 32:
                return None  # week not loaded, or bye rows missing: ask ESPN
        cols = ["team_id", "team_name", "team_nickname", "city", "color", "alt_color", "logo_url", "abbreviation", "bye_week"]
        return byes[cols].to_dict("records")
    except Exception as exc:
        logging.getLogger(__name__).warning("Snowflake byes failed for %s week %s, using ESPN: %r", season, week, exc)
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _bye_teams_for_week(week, season, seasontype):
    """Uses ESPN's `week.teamsOnBye` when present, otherwise derives byes as teams
    absent from that week's scoreboard.
    """
    data = _request_scoreboard(week=week, seasontype=seasontype, season=season)
    if not data:
        return []
    week_info = data.get("week") or {}
    bye_week = _to_int(week_info.get("number"), week)
    if (data.get("season") or {}).get("type") != 2:
        return []  # BYEs only exist in the regular season

    all_teams = _get_all_teams()
    bye_ids = [_to_int(t.get("id")) for t in week_info.get("teamsOnBye", [])]
    if not bye_ids and all_teams:
        playing = {
            _to_int(c.get("team", {}).get("id") or c.get("id"))
            for e in data.get("events", [])
            for comp in e.get("competitions", [])
            for c in comp.get("competitors", [])
        }
        bye_ids = [tid for tid in all_teams if tid not in playing]

    byes = []
    for tid in bye_ids:
        team = all_teams.get(tid, {"team_id": tid})
        byes.append({**team, "team_id": tid, "bye_week": bye_week})
    return sorted(byes, key=lambda t: t.get("team_name") or "")


def _normalize_play(play, drive_team):
    start = play.get("start") or {}
    end = play.get("end") or {}
    play_type = (play.get("type") or {}).get("text")
    # e.g. "2nd & 6 at KC 38" / "3rd & 3 at 50"; kickoffs and PATs have no down.
    label = start.get("downDistanceText") or (
        f"{play_type} at {start['possessionText']}" if start.get("possessionText") else play_type
    )
    return {
        "id": play.get("id"),
        "sequence": _to_int(play.get("sequenceNumber"), 0),
        "period": _to_int((play.get("period") or {}).get("number")),
        "clock": (play.get("clock") or {}).get("displayValue"),
        "type": play_type,
        "text": play.get("text"),
        "label": label,
        # Down & distance for the next snap (e.g. "1st & 10 at DAL 25").
        "next_down_distance": end.get("downDistanceText"),
        "down": _to_int(start.get("down")),
        "distance": _to_int(start.get("distance")),
        "team_id": _to_int((start.get("team") or {}).get("id")) or drive_team,
        # ESPN reports 0 for non-plays (timeouts, two-minute warning); use the end spot.
        "start_yards_to_endzone": start.get("yardsToEndzone") or end.get("yardsToEndzone"),
        "end_yards_to_endzone": end.get("yardsToEndzone"),
        # End spot is measured from the team in possession after the play (turnovers flip it).
        "end_team_id": _to_int((end.get("team") or {}).get("id")),
        "scoring_play": bool(play.get("scoringPlay")),
    }


def get_game_plays(event_id):
    """Play-by-play for one game, most recent play first (same time slot as the scoreboard)."""
    return _game_summary(event_id, int(time.time() // LIVE_REFRESH_SECONDS))["plays"]


def _with_summary_state(match):
    """Overlay clock, scores and possession from the game's summary payload.

    The scoreboard and summary endpoints update at different moments; taking a
    live game's state from the same payload as its plays keeps the score banner,
    live card and last play on one moment in time.
    """
    summary = _game_summary(match["match_id"], int(time.time() // LIVE_REFRESH_SECONDS))
    status = summary["status"]
    if not status:
        return match
    status_type = status.get("type", {})
    period = status.get("period", match["quarter"])
    match = {**match,
             "status_name": status_type.get("name", match["status_name"]),
             "status": _map_status(status_type.get("name"), period),
             "status_detail": status_type.get("shortDetail") or status_type.get("detail") or match["status_detail"],
             "clock": status.get("displayClock", match["clock"]),
             "quarter": period,
             "possession_team_id": summary["possession_team_id"] or match["possession_team_id"]}
    for side in ("home_team", "away_team"):
        team = match[side]
        if team and team["team_id"] in summary["scores"]:
            match[side] = {**team, "score": summary["scores"][team["team_id"]]}
    last = summary["plays"][0] if summary["plays"] else None
    if last and last.get("next_down_distance"):
        match["down_distance"] = last["next_down_distance"]
    return match


@st.cache_data(ttl=LIVE_REFRESH_SECONDS * 4, max_entries=64, show_spinner=False)
def _game_summary(event_id, slot):
    """One summary fetch per game per slot: plays plus the game state at that moment."""
    empty = {"plays": [], "status": None, "scores": {}, "possession_team_id": None}
    try:
        response = requests.get(ESPN_SUMMARY_URL, params={"event": event_id}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        st.error(f"Failed to fetch play-by-play: {exc}")
        return empty
    data = response.json()
    competition = ((data.get("header") or {}).get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    drives = data.get("drives") or {}
    all_drives = list(drives.get("previous") or [])
    current = drives.get("current")
    if current and current.get("id") not in {d.get("id") for d in all_drives}:
        all_drives.append(current)

    plays, seen = [], set()
    for drive in all_drives:
        drive_team = _to_int((drive.get("team") or {}).get("id"))
        for play in drive.get("plays") or []:
            if play.get("id") in seen:
                continue
            seen.add(play.get("id"))
            plays.append(_normalize_play(play, drive_team))
    return {
        "plays": sorted(plays, key=lambda p: p["sequence"], reverse=True),
        "status": competition.get("status"),
        "scores": {_to_int(c.get("id")): _to_int(c.get("score")) for c in competitors},
        "possession_team_id": next((_to_int(c.get("id")) for c in competitors if c.get("possession")), None),
    }
