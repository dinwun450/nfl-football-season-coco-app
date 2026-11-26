"""Vertical NFL playoff bracket rendered as static HTML/CSS for st.html.

A bracket is a list of sections, each with rounds of games:

    [{"title": "AFC", "accent": "#d50a0a", "rounds": [
        {"title": "Wild Card", "games": [
            {"top": team_or_placeholder, "bottom": team_or_placeholder, "winner": team_id},
        ]},
    ]}]

A team slot is a dict with seed, team_id, team_name, abbreviation, logo_url,
record and optional note (e.g. "BYE"). A placeholder is {"label": "TBD"}.
"""
import html

import pandas as pd

# NFL format: seed 1 gets a bye; 2v7, 3v6, 4v5 in the Wild Card round.
WILD_CARD_PAIRS = [(2, 7), (3, 6), (4, 5)]
CONFERENCE_ACCENTS = {"AFC": "#d50a0a", "NFC": "#013369", "Super Bowl": "#c9a227"}

# Class names are prefixed because st.html injects into the page, not an iframe.
_CSS = """
<style>
  .nflbr { font-family: 'Segoe UI', Arial, sans-serif; color: #fff; background: #0b1a2e;
    border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 14px; }
  .nflbr h4 { margin: 0; font-size: 15px; color: #fff; letter-spacing: .5px; }
  .nflbr-note { font-size: 11px; color: #9fb3c8; margin-top: 2px; }
  .nflbr-section { border-radius: 10px; padding: 10px; background: #13263f; border-top: 4px solid var(--accent); }
  .nflbr-round { margin-top: 10px; }
  .nflbr-round-title { font-size: 11px; text-transform: uppercase; color: #9fb3c8; margin-bottom: 4px; }
  .nflbr-games { display: flex; flex-direction: column; gap: 6px; }
  .nflbr-game { background: #1b3352; border-radius: 6px; overflow: hidden; }
  .nflbr-slot { display: flex; align-items: center; gap: 8px; padding: 5px 8px; font-size: 13px; }
  .nflbr-slot + .nflbr-slot { border-top: 1px solid #0b1a2e; }
  .nflbr-slot img { width: 20px; height: 20px; }
  .nflbr-seed { width: 16px; color: #9fb3c8; font-size: 11px; text-align: right; }
  .nflbr-name { flex: 1; }
  .nflbr-rec { font-size: 11px; color: #9fb3c8; }
  .nflbr-tbd { color: #6c7f95; font-style: italic; }
  .nflbr-tag { font-size: 11px; color: #ffd166; }
  .nflbr-win { background: #24507f; font-weight: 600; }
  .nflbr-win .nflbr-name::after { content: ' \\2713'; color: #7bd389; }
  .nflbr-lose { opacity: .5; }
  .nflbr-champ { text-align: center; font-size: 15px; font-weight: 700; color: #ffd166; padding-top: 8px; }
</style>
"""


def _e(value):
    return html.escape("" if value is None else str(value))


def placeholder(label="TBD"):
    return {"label": label}


def make_game(top, bottom, winner=None):
    return {"top": top, "bottom": bottom, "winner": winner}


def _slot_html(slot, winner):
    if not slot or "team_id" not in slot:
        label = (slot or {}).get("label", "TBD")
        return f'<div class="nflbr-slot"><span class="nflbr-seed"></span><span class="nflbr-name nflbr-tbd">{_e(label)}</span></div>'
    state = ""
    if winner is not None:
        state = " nflbr-win" if winner == slot["team_id"] else " nflbr-lose"
    logo = f'<img src="{_e(slot["logo_url"])}" alt="">' if slot.get("logo_url") else ""
    tag = f'<span class="nflbr-tag">{_e(slot["note"])}</span>' if slot.get("note") else ""
    return (
        f'<div class="nflbr-slot{state}"><span class="nflbr-seed">{_e(slot.get("seed"))}</span>{logo}'
        f'<span class="nflbr-name">{_e(slot.get("team_name"))}</span>{tag}'
        f'<span class="nflbr-rec">{_e(slot.get("record"))}</span></div>'
    )


def _game_html(game):
    winner = game.get("winner")
    return f'<div class="nflbr-game">{_slot_html(game.get("top"), winner)}{_slot_html(game.get("bottom"), winner)}</div>'


def build_bracket_html(sections, title="Playoff picture", note="", champion=None):
    """Return the full bracket HTML (CSS included)."""
    parts = [_CSS, '<div class="nflbr">', f"<div><h4>{_e(title)}</h4>"]
    if note:
        parts.append(f'<div class="nflbr-note">{_e(note)}</div>')
    parts.append("</div>")
    for section in sections:
        accent = section.get("accent") or CONFERENCE_ACCENTS.get(section["title"], "#8d99ae")
        parts.append(f'<div class="nflbr-section" style="--accent:{_e(accent)}"><h4>{_e(section["title"])}</h4>')
        for rnd in section["rounds"]:
            games = "".join(_game_html(g) for g in rnd["games"])
            parts.append(
                f'<div class="nflbr-round"><div class="nflbr-round-title">{_e(rnd["title"])}</div>'
                f'<div class="nflbr-games">{games}</div></div>'
            )
        parts.append("</div>")
    if champion:
        parts.append(f'<div class="nflbr-champ">Super Bowl champion: {_e(champion.get("team_name"))}</div>')
    parts.append("</div>")
    return "".join(parts)


def team_slot(row, note=""):
    """Build a team slot from a standings row (dict or pandas Series)."""
    seed = row.get("playoff_seed")
    return {
        "seed": int(seed) if pd.notna(seed) else None,  # Snowflake returns nullable Int64
        "team_id": int(row["team_id"]),
        "team_name": row["team_name"],
        "abbreviation": row["abbreviation"],
        "logo_url": row.get("logo_url"),
        "record": row.get("record"),
        "note": note,
    }
