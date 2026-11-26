"""League-wide NFL injury report from ESPN.

Endpoint documented at https://github.com/pseudo-r/Public-NFL-API:
    GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries
Returns every team's injury list (32 teams) in one request.
"""
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st

ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
REQUEST_TIMEOUT = 10
ET_TZ = pytz.timezone("America/New_York")

# Most to least severe; "Active" entries are news notes for healthy players.
STATUS_ORDER = ["Injured Reserve", "Out", "Doubtful", "Questionable", "Day-To-Day", "Suspension", "Active"]
DESIGNATED_STATUSES = [s for s in STATUS_ORDER if s != "Active"]

INJURY_COLUMNS = [
    "team_id", "team_name", "team_abbr", "team_logo", "player", "position", "headshot",
    "player_url", "status", "status_rank", "injury", "detail", "side", "location",
    "return_date", "updated", "short_comment", "long_comment",
]


def _clean(value):
    return None if value in (None, "", "Not Specified") else value


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ET_TZ).replace(tzinfo=None)
    except ValueError:
        return None


def _team_logo(team):
    logos = team.get("logos") or []
    return next((l.get("href") for l in logos if "default" in (l.get("rel") or [])), None) or (
        logos[0].get("href") if logos else None
    )


@st.cache_data(ttl=900, show_spinner=False)
def get_injury_report():
    """One row per injury entry across all 32 teams, most severe first."""
    try:
        response = requests.get(ESPN_INJURIES_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        st.error(f"Failed to fetch the injury report from ESPN: {exc}")
        return pd.DataFrame(columns=INJURY_COLUMNS)

    rows = []
    for team_block in payload.get("injuries", []):
        for item in team_block.get("injuries", []):
            athlete = item.get("athlete") or {}
            team = athlete.get("team") or {}
            details = item.get("details") or {}
            status = item.get("status") or "Unknown"
            return_date = _clean(details.get("returnDate"))
            rows.append({
                "team_id": int(team.get("id") or team_block.get("id") or 0),
                "team_name": team.get("displayName") or team_block.get("displayName"),
                "team_abbr": team.get("abbreviation"),
                "team_logo": _team_logo(team),
                "player": athlete.get("displayName"),
                "position": (athlete.get("position") or {}).get("abbreviation"),
                "headshot": (athlete.get("headshot") or {}).get("href"),
                "player_url": next((l.get("href") for l in athlete.get("links") or [] if l.get("href")), None),
                "status": status,
                "status_rank": STATUS_ORDER.index(status) if status in STATUS_ORDER else len(STATUS_ORDER),
                "injury": _clean(details.get("type")),
                "detail": _clean(details.get("detail")),
                "side": _clean(details.get("side")),
                "location": _clean(details.get("location")),
                "return_date": pd.to_datetime(return_date).date() if return_date else None,
                "updated": _parse_date(item.get("date")),
                "short_comment": item.get("shortComment"),
                "long_comment": item.get("longComment"),
            })

    df = pd.DataFrame(rows, columns=INJURY_COLUMNS)
    if df.empty:
        return df
    return df.sort_values(["status_rank", "team_name", "player"]).reset_index(drop=True)
