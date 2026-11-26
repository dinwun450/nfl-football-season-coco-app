"""HTML football field for plays, rendered with st.html.

Field orientation is fixed per game: the away team's end zone is on the
left, the home team's on the right. Positions are in yards from the left
goal line (0-100).
"""
import html

FIELD_CSS = """
<style>
  .nflf { font-family: 'Segoe UI', Arial, sans-serif; color: #fff; }
  .nflf-head { display: flex; justify-content: space-between; align-items: baseline;
    gap: 12px; margin-bottom: 6px; }
  .nflf-dd { font-size: 18px; font-weight: 700; }
  .nflf-meta { font-size: 12px; color: #9fb3c8; }
  .nflf-field { position: relative; height: 150px; border-radius: 8px; overflow: hidden;
    display: grid; grid-template-columns: 8.33% 1fr 8.33%; border: 2px solid #fff; }
  .nflf-ez { display: flex; align-items: center; justify-content: center;
    writing-mode: vertical-rl; font-weight: 800; letter-spacing: 3px; font-size: 18px;
    color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,.5); }
  .nflf-ez.left { transform: rotate(180deg); }
  .nflf-turf { position: relative;
    background: repeating-linear-gradient(90deg, #2e7d32 0 10%, #388e3c 10% 20%); }
  .nflf-yl { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(255,255,255,.55); }
  .nflf-num { position: absolute; bottom: 6px; transform: translateX(-50%);
    font-size: 13px; font-weight: 700; color: rgba(255,255,255,.85); }
  .nflf-num.top { top: 6px; bottom: auto; transform: translateX(-50%) rotate(180deg); }
  .nflf-los { position: absolute; top: 0; bottom: 0; width: 3px; background: #2f6fed;
    transform: translateX(-50%); }
  .nflf-fd { position: absolute; top: 0; bottom: 0; width: 3px; background: #ffd400;
    transform: translateX(-50%); }
  .nflf-gain { position: absolute; top: 50%; height: 6px; margin-top: -3px; border-radius: 3px;
    opacity: .85; }
  .nflf-ball { position: absolute; top: 50%; width: 18px; height: 11px; margin-top: -6px;
    border-radius: 50%; background: #8b4513; border: 1px solid #fff; transform: translateX(-50%);
    box-shadow: 0 0 6px rgba(0,0,0,.6); }
  .nflf-text { margin-top: 8px; font-size: 13px; color: #dce6f0; line-height: 1.35; }
  .nflf-legend { margin-top: 4px; font-size: 11px; color: #9fb3c8; }
  .nflf-legend b.los { color: #6b9bff; } .nflf-legend b.fd { color: #ffd400; }

  /* Compact rows for the play-by-play list */
  .nflf-list { display: flex; flex-direction: column; gap: 10px; max-height: 640px;
    overflow-y: auto; padding-right: 4px; }
  .nflf-row { display: grid; grid-template-columns: 74px 1fr; gap: 10px;
    padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,.08); }
  .nflf-time { font-size: 12px; color: #9fb3c8; font-variant-numeric: tabular-nums; }
  .nflf-time b { display: block; color: #fff; font-size: 13px; }
  .nflf-row .nflf-dd { font-size: 14px; }
  .nflf-row .nflf-text { margin: 2px 0 6px; font-size: 12px; }
  .nflf-row .nflf-field { height: 44px; border-width: 1px; border-radius: 5px; }
  .nflf-row .nflf-ez { font-size: 10px; letter-spacing: 1px; }
  .nflf-row .nflf-num { font-size: 9px; bottom: 2px; }
  .nflf-row .nflf-num.top { display: none; }
  .nflf-row .nflf-ball { width: 12px; height: 8px; margin-top: -4px; }
  .nflf-row .nflf-gain { height: 4px; margin-top: -2px; }
  .nflf-score { color: #ffd166; font-weight: 700; }
</style>
"""


def _e(value):
    return html.escape("" if value is None else str(value))


def _color(team, fallback):
    color = (team or {}).get("color")
    return f"#{color}" if color and not str(color).startswith("#") else (color or fallback)


def field_position(yards_to_endzone, offense_is_home):
    """Yards from the left (away) goal line. Away attacks right, home attacks left."""
    if yards_to_endzone is None:
        return None
    return float(yards_to_endzone) if offense_is_home else 100.0 - float(yards_to_endzone)


def _pct(yards):
    """Turf-relative percentage for a 0-100 yard position."""
    return max(0.0, min(100.0, yards))


def _field_html(play, home, away):
    """The field strip only: end zones, yard lines, and this play's markers."""
    offense_is_home = play.get("team_id") == (home or {}).get("team_id")
    direction = -1 if offense_is_home else 1
    start = field_position(play.get("start_yards_to_endzone"), offense_is_home)
    end_team = play.get("end_team_id") or play.get("team_id")
    end = field_position(play.get("end_yards_to_endzone"), end_team == (home or {}).get("team_id"))
    distance = play.get("distance") or 0

    marks = []
    for yard in range(10, 100, 10):
        number = yard if yard <= 50 else 100 - yard
        marks.append(
            f'<div class="nflf-yl" style="left:{yard}%"></div>'
            f'<div class="nflf-num" style="left:{yard}%">{number}</div>'
            f'<div class="nflf-num top" style="left:{yard}%">{number}</div>'
        )

    overlays = []
    if start is not None:
        overlays.append(f'<div class="nflf-los" style="left:{_pct(start)}%" title="Line of scrimmage"></div>')
        if play.get("down") and distance:
            first_down = start + direction * distance
            if 0 < first_down < 100:  # no marker on goal-to-go
                overlays.append(f'<div class="nflf-fd" style="left:{_pct(first_down)}%" title="First down"></div>')
        if end is not None and end != start:
            left, right = sorted((_pct(start), _pct(end)))
            gain_color = "#7bd389" if (end - start) * direction > 0 else "#ff6b6b"
            overlays.append(
                f'<div class="nflf-gain" style="left:{left}%;width:{right - left}%;background:{gain_color}"></div>'
            )
        ball = end if end is not None else start
        overlays.append(f'<div class="nflf-ball" style="left:{_pct(ball)}%" title="Ball after the play"></div>')

    return (
        '<div class="nflf-field">'
        f'<div class="nflf-ez left" style="background:{_e(_color(away, "#444"))}">{_e((away or {}).get("abbreviation"))}</div>'
        f'<div class="nflf-turf">{"".join(marks)}{"".join(overlays)}</div>'
        f'<div class="nflf-ez" style="background:{_e(_color(home, "#444"))}">{_e((home or {}).get("abbreviation"))}</div>'
        "</div>"
    )


def _offense_abbr(play, home, away):
    is_home = play.get("team_id") == (home or {}).get("team_id")
    return ((home if is_home else away) or {}).get("abbreviation")


def build_field_html(play, home, away, situation=None):
    """Full-size field for one play (e.g. the current play of a live game).

    play: dict from get_game_plays (start/end spots, label, text, clock, period).
    home/away: team dicts with team_id, abbreviation and color.
    situation: current down & distance (the next snap), shown as the heading so it
    matches the score banner; the play's own starting down goes in the meta line.
    """
    # The play's clock is when it was snapped, not the current game clock.
    meta = f'Last play &middot; snapped Q{_e(play.get("period"))} {_e(play.get("clock"))}'
    if situation and play.get("label"):
        meta += f' on {_e(play["label"])}'
    meta += f' &middot; {_e(_offense_abbr(play, home, away))} ball'
    if play.get("type"):
        meta += f' &middot; {_e(play["type"])}'
    return (
        FIELD_CSS
        + '<div class="nflf">'
        + f'<div class="nflf-head"><span class="nflf-dd">{_e(situation or play.get("label"))}</span>'
        + f'<span class="nflf-meta">{meta}</span></div>'
        + _field_html(play, home, away)
        + f'<div class="nflf-text">{_e(play.get("text"))}</div>'
        + '<div class="nflf-legend"><b class="los">|</b> line of scrimmage &nbsp; '
        + '<b class="fd">|</b> first down &nbsp; bar = yards gained or lost</div>'
        + "</div>"
    )


def build_play_list_html(plays, home, away):
    """Scrollable play-by-play: event time, situation, description, and a compact field per play.

    Built as one HTML block so long games (170+ plays) stay cheap to render.
    """
    rows = []
    for play in plays:
        label = _e(play.get("label"))
        if play.get("scoring_play"):
            label += ' <span class="nflf-score">&middot; Score</span>'
        rows.append(
            '<div class="nflf-row">'
            f'<div class="nflf-time"><b>Q{_e(play.get("period"))} {_e(play.get("clock"))}</b>'
            f'{_e(_offense_abbr(play, home, away))} ball</div>'
            f'<div><div class="nflf-dd">{label}</div>'
            f'<div class="nflf-text">{_e(play.get("text"))}</div>'
            f'{_field_html(play, home, away)}</div>'
            "</div>"
        )
    return FIELD_CSS + f'<div class="nflf"><div class="nflf-list">{"".join(rows)}</div></div>'
