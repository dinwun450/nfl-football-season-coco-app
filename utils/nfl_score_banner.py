import html

import streamlit as st

from utils.nfl_football_api import (
    FINAL_STATUSES,
    LIVE_STATUSES,
    _fetch_window_events,
    _normalize_events,
)

SECONDS_PER_BUG = 6  # scroll speed: higher = slower

_CSS = """
<style>
  .nfl-banner { position: relative; overflow: hidden; height: 84px;
    background: #0b1a2e; border-radius: 10px; font-family: 'Segoe UI', Arial, sans-serif;
    color: #fff; display: flex; align-items: center; }
  .nfl-track { display: flex; gap: 12px; width: max-content; padding-left: 12px;
    animation: nfl-scroll var(--duration) linear infinite; }
  .nfl-banner:hover .nfl-track { animation-play-state: paused; }
  @keyframes nfl-scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
  .bug { display: flex; align-items: center; gap: 10px; min-width: 300px;
    background: #13263f; border-radius: 8px; padding: 6px 10px; }
  .bug.live { border-left: 4px solid #e63946; }
  .bug.final { border-left: 4px solid #8d99ae; }
  .teams { flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .team { display: flex; align-items: center; gap: 6px; font-size: 14px; }
  .team img { width: 22px; height: 22px; }
  .team .abbr { width: 40px; font-weight: 600; }
  .team .rec { font-size: 11px; color: #9fb3c8; }
  .team .score { margin-left: auto; font-size: 18px; font-weight: 700; }
  .team.loser { opacity: 0.55; }
  .possession::after { content: ' \\25C0'; color: #ffd166; font-size: 10px; }
  .state { display: flex; flex-direction: column; align-items: flex-end; min-width: 78px;
    font-size: 12px; color: #cfd8e3; text-align: right; }
  .state .tag { font-weight: 700; font-size: 11px; padding: 1px 6px; border-radius: 4px; }
  .live .tag { background: #e63946; color: #fff; }
  .final .tag { background: #8d99ae; color: #0b1a2e; }
  .redzone { color: #ff6b6b; font-weight: 600; }
  .empty { width: 100%; text-align: center; font-size: 16px; color: #9fb3c8; }
</style>
"""


def _e(value):
    return html.escape("" if value is None else str(value))


def get_banner_matches(include_finals=True):
    """Live games first, then finals from the past seven days (most recent first)."""
    events = _fetch_window_events()
    live = _normalize_events(events, LIVE_STATUSES)
    finals = _normalize_events(events, FINAL_STATUSES) if include_finals else []
    return live + sorted(finals, key=lambda m: m["utc_iso"], reverse=True)


def _team_row(team, is_final, other_score, possession_id):
    if not team:
        return ""
    classes = ["team"]
    if is_final and team["score"] is not None and other_score is not None and team["score"] < other_score:
        classes.append("loser")
    abbr_class = "abbr possession" if possession_id and possession_id == team["team_id"] else "abbr"
    logo = f'<img src="{_e(team["logo_url"])}" alt="">' if team.get("logo_url") else ""
    rec = f'<span class="rec">{_e(team["record"])}</span>' if team.get("record") else ""
    score = "" if team["score"] is None else team["score"]
    return (
        f'<div class="{" ".join(classes)}">{logo}'
        f'<span class="{abbr_class}">{_e(team["abbreviation"])}</span>{rec}'
        f'<span class="score">{_e(score)}</span></div>'
    )


def _score_bug(match):
    is_final = match["status_name"] in FINAL_STATUSES
    away, home = match["away_team"], match["home_team"]
    away_score = away["score"] if away else None
    home_score = home["score"] if home else None
    possession = None if is_final else match.get("possession_team_id")

    if is_final:
        tag, line1, line2 = "FINAL", match.get("date_display", ""), ""
        if match["status_name"] == "STATUS_FINAL_OVERTIME":
            tag = "FINAL/OT"
    else:
        tag = "LIVE"
        line1 = match.get("status_detail") or f'{match["clock"]} Q{match["quarter"]}'
        line2 = match.get("down_distance") or ""

    line2_class = "redzone" if match.get("is_red_zone") and not is_final else ""
    return (
        f'<div class="bug {"final" if is_final else "live"}">'
        f'<div class="teams">'
        f'{_team_row(away, is_final, home_score, possession)}'
        f'{_team_row(home, is_final, away_score, possession)}'
        f'</div><div class="state"><span class="tag">{_e(tag)}</span>'
        f'<span>{_e(line1)}</span><span class="{line2_class}">{_e(line2)}</span></div></div>'
    )


def build_score_banner_html(matches):
    """Return the banner HTML for the given normalized matches."""
    if not matches:
        return (
            _CSS + '<div class="nfl-banner"><div class="empty">'
            "No teams currently playing</div></div>"
        )
    bugs = "".join(_score_bug(m) for m in matches)
    # Track holds two copies so the -50% translate loops seamlessly.
    duration = max(len(matches) * SECONDS_PER_BUG, 12)
    return (
        _CSS + f'<div class="nfl-banner"><div class="nfl-track" style="--duration:{duration}s">'
        f"{bugs}{bugs}</div></div>"
    )


def render_score_banner(include_finals=True):
    """Render the rotating score banner in the current Streamlit app."""
    st.html(build_score_banner_html(get_banner_matches(include_finals)))
