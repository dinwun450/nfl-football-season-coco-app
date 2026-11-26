import html
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.nfl_bracket_preview import render_bracket_preview
from utils.nfl_data_loader import load_upcoming_matches
from utils.snowflake_connector import snowflake_available
from utils.nfl_field import build_field_html, build_play_list_html
from utils.nfl_stats_api import get_standings
from utils.nfl_football_api import (
    LIVE_REFRESH_SECONDS,
    get_bye_teams,
    get_completed_matches,
    get_current_week,
    get_game_plays,
    get_live_matches,
    get_upcoming_matches,
)

# Clock events with no snap; they carry no meaningful field position.
NON_PLAYS = {"End Period", "End of Half", "End of Game", "Two-minute warning", "Timeout", "Official Timeout"}
UPCOMING_LIMIT = 8

st.title("NFL season overview")
st.caption(f"Live and recent results from ESPN. Live games refresh every {LIVE_REFRESH_SECONDS} seconds.")


def _live_game(match):
    away, home = match["away_team"] or {}, match["home_team"] or {}
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            for i, team in enumerate((away, home)):
                if i:
                    st.markdown("@", width="content")
                if team.get("logo_url"):
                    st.image(team["logo_url"], width=36)
                score = team.get("score") if team.get("score") is not None else "-"
                st.markdown(f"**{team.get('abbreviation')}** &nbsp; :orange[**{score}**]", width="content")
            st.space("stretch")
            st.badge(
                match["status_detail"] or match["status"],
                icon=":material/radio_button_checked:",
                color="red",
            )

        plays = [p for p in get_game_plays(match["match_id"]) if p["type"] not in NON_PLAYS]
        if not plays:
            st.caption("Play-by-play isn't available yet.")
            return

        # Current situation is always visible; the full log is collapsible.
        st.html(build_field_html(plays[0], home, away))
        # Label stays constant so the open/closed state survives each refresh.
        with st.expander("Play-by-play", icon=":material/format_list_bulleted:"):
            st.caption(f"{len(plays)} plays, most recent first")
            st.html(build_play_list_html(plays, home, away))


_BYE_CSS = """
<style>
  .nflbye { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px;
    font-family: 'Segoe UI', Arial, sans-serif; margin-bottom: 6px; }
  .nflbye-card { position: relative; overflow: hidden; display: flex; align-items: center; gap: 10px;
    padding: 10px 12px; border-radius: 10px; color: #fff;
    background: linear-gradient(120deg, var(--c1) 0%, var(--c1) 55%, var(--c2) 140%);
    box-shadow: 0 2px 10px rgba(0,0,0,.25); }
  .nflbye-card img { width: 42px; height: 42px; flex: none; padding: 3px; border-radius: 50%;
    background: rgba(255,255,255,.92); }
  .nflbye-name { font-weight: 700; font-size: 14px; line-height: 1.15; text-shadow: 0 1px 2px rgba(0,0,0,.45); }
  .nflbye-meta { font-size: 11px; opacity: .9; margin-top: 2px; text-shadow: 0 1px 2px rgba(0,0,0,.45); }
  .nflbye-tag { position: absolute; top: 6px; right: 8px; font-size: 9px; font-weight: 800;
    letter-spacing: 1px; padding: 1px 6px; border-radius: 4px; background: rgba(0,0,0,.35); }
</style>
"""


def _bye_cards_html(byes, by_id):
    """Team-colored cards: logo, name, record and division for each team on bye."""
    e = html.escape
    cards = []
    for team in byes:
        row = by_id.get(team["team_id"], {})
        c1 = f"#{team.get('color') or '13263f'}"
        c2 = f"#{team.get('alt_color') or '0b1a2e'}"
        meta = " \u00b7 ".join(x for x in (row.get("record"), row.get("division")) if x)
        logo = f'<img src="{e(team["logo_url"])}" alt="">' if team.get("logo_url") else ""
        cards.append(
            f'<div class="nflbye-card" style="--c1:{e(c1)};--c2:{e(c2)}">{logo}'
            f'<div><div class="nflbye-name">{e(team.get("team_name") or str(team["team_id"]))}</div>'
            f'<div class="nflbye-meta">{e(meta)}</div></div>'
            '<span class="nflbye-tag">BYE</span></div>'
        )
    return _BYE_CSS + f'<div class="nflbye">{"".join(cards)}</div>'


@st.fragment(run_every="10m")
def bye_section():
    """Re-checks the current week every 10 minutes so an open page rolls over on its own."""
    season, current_week = get_current_week()
    if current_week is None:
        st.info("Bye weeks only happen during the regular season.")
        return
    standings = get_standings()
    by_id = standings.set_index("team_id").to_dict("index") if not standings.empty else {}
    for label, week in (("This week", current_week), ("Next week", current_week + 1)):
        if week > 18:
            continue
        byes = get_bye_teams(week=week, season=season)
        st.caption(f"{label} \u00b7 Week {week}")
        if not byes:
            st.markdown(":gray[All 32 teams play.]")
            continue
        st.html(_bye_cards_html(byes, by_id))


@st.fragment(run_every=LIVE_REFRESH_SECONDS)
def live_section():
    st.subheader("Live games")
    live = get_live_matches()
    if not live:
        st.info("No teams are playing right now.", icon=":material/sports_football:")
        return
    for match in live:
        _live_game(match)


def _countdown(kickoff, now):
    seconds = int((kickoff - now).total_seconds())
    if seconds <= 0:
        return "Kicking off"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days}d {hours:02d}h {minutes:02d}m {secs:02d}s" if days else f"{hours:02d}h {minutes:02d}m {secs:02d}s"


_UPCOMING_CSS = """
<style>
  .nflup { display: flex; flex-direction: column; gap: 8px; font-family: 'Segoe UI', Arial, sans-serif; }
  .nflup-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 12px;
    background: #13263f; border-radius: 10px; padding: 10px 14px; color: #fff; }
  .nflup-teams { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; }
  .nflup-teams img { width: 28px; height: 28px; }
  .nflup-at { color: #9fb3c8; font-weight: 400; }
  .nflup-meta { font-size: 12px; color: #9fb3c8; margin-top: 3px; }
  .nflup-cd { text-align: right; }
  .nflup-cd b { display: block; font-size: 18px; color: #ffd166; font-variant-numeric: tabular-nums; }
  .nflup-cd span { font-size: 11px; color: #9fb3c8; }
</style>
"""


def _upcoming_html(matches, now):
    e = html.escape
    rows = []
    for m in matches:
        away, home = m["away_team"] or {}, m["home_team"] or {}
        kickoff = datetime.fromisoformat(m["utc_iso"])
        logos = [
            f'<img src="{e(t["logo_url"])}" alt="">' if t.get("logo_url") else "" for t in (away, home)
        ]
        meta = [f"{m['date_display']} · {m['time_et_display']}"]
        if m["venue"].get("venue_name"):
            meta.append(m["venue"]["venue_name"])
        if m.get("broadcasts"):
            meta.append(", ".join(m["broadcasts"]))
        rows.append(
            '<div class="nflup-row"><div>'
            f'<div class="nflup-teams">{logos[0]}{e(away.get("abbreviation") or "")}'
            f'<span class="nflup-at">@</span>{logos[1]}{e(home.get("abbreviation") or "")}</div>'
            f'<div class="nflup-meta">{e(" · ".join(meta))}</div></div>'
            f'<div class="nflup-cd"><b>{e(_countdown(kickoff, now))}</b><span>until kickoff</span></div>'
            "</div>"
        )
    return _UPCOMING_CSS + f'<div class="nflup">{"".join(rows)}</div>'


def _snowflake_upcoming():
    """Scheduled games from NFL_SEASON.PUBLIC.NFL_MATCHES in the shape _upcoming_html expects."""
    if not snowflake_available():
        return None
    try:
        df = load_upcoming_matches(days=7, limit=UPCOMING_LIMIT)
    except Exception:
        return None
    matches = []
    for row in df.to_dict("records"):
        kickoff = pd.Timestamp(row["match_date"]).tz_localize("UTC")  # stored as UTC (TIMESTAMP_NTZ)
        local = kickoff.tz_convert("America/New_York")
        matches.append({
            "utc_iso": kickoff.isoformat(),
            "date_display": local.strftime("%b %d, %Y"),
            "time_et_display": local.strftime("%I:%M %p ET").lstrip("0"),
            "away_team": {"abbreviation": row["away_abbr"], "logo_url": row["away_logo"]},
            "home_team": {"abbreviation": row["home_abbr"], "logo_url": row["home_logo"]},
            "venue": {"venue_name": row["venue_name"]},
            "broadcasts": [b.strip() for b in (row["broadcasts"] or "").split(",") if b.strip()],
        })
    return matches


@st.fragment(run_every="1s")
def upcoming_section():
    """Ticks every second; the schedule comes from Snowflake (60s cache), ESPN as fallback."""
    st.subheader("Upcoming games")
    upcoming = _snowflake_upcoming()
    if upcoming is None:
        upcoming = [m for m in get_upcoming_matches() if m["utc_iso"]][:UPCOMING_LIMIT]
    if not upcoming:
        st.info("No games are scheduled in the next 7 days.", icon=":material/event_busy:")
        return
    st.html(_upcoming_html(upcoming, datetime.now(timezone.utc)))


def _completed_frame(matches):
    rows = []
    for m in matches:
        away, home = m["away_team"] or {}, m["home_team"] or {}
        rows.append({
            "Date": m["date_display"],
            "Week": m["week"],
            "Away logo": away.get("logo_url"),
            "Away": away.get("team_name"),
            "Away score": away.get("score"),
            "Home score": home.get("score"),
            "Home": home.get("team_name"),
            "Home logo": home.get("logo_url"),
            "Result": m["status"],
        })
    return pd.DataFrame(rows)


live_section()
upcoming_section()

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Completed games (last 7 days)")
    completed = get_completed_matches()
    if completed:
        st.dataframe(
            _completed_frame(completed),
            hide_index=True,
            column_config={
                "Away logo": st.column_config.ImageColumn("", width="small"),
                "Home logo": st.column_config.ImageColumn("", width="small"),
                "Week": st.column_config.NumberColumn(format="%d"),
            },
        )
    else:
        st.info("No games have finished in the last 7 days.")

    st.subheader("Teams on bye")
    bye_section()

with right:
    st.subheader("Bracket preview")
    render_bracket_preview()
