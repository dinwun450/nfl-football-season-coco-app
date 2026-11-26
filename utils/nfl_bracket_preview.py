"""Read-only projected playoff bracket for the home page."""
import streamlit as st

from utils.nfl_bracket_html import (
    WILD_CARD_PAIRS,
    build_bracket_html,
    make_game,
    placeholder,
    team_slot,
)
from utils.nfl_stats_api import get_standings

PLAYOFF_TEAMS = 7


def get_playoff_seeds():
    """{'AFC': {seed: slot}, 'NFC': {seed: slot}} for seeds 1-7."""
    standings = get_standings()
    seeds = {}
    if standings.empty:
        return seeds
    in_field = standings[standings["playoff_seed"].between(1, PLAYOFF_TEAMS)]
    for conf, group in in_field.groupby("conference"):
        seeds[conf] = {int(r["playoff_seed"]): team_slot(r) for _, r in group.iterrows()}
    return seeds


def _projected_section(conf, by_seed):
    one_seed = by_seed.get(1)
    if one_seed:
        one_seed = {**one_seed, "note": "BYE"}
    return {
        "title": conf,
        "rounds": [
            {"title": "Wild Card", "games": [
                make_game(by_seed.get(a) or placeholder(), by_seed.get(b) or placeholder())
                for a, b in WILD_CARD_PAIRS
            ]},
            {"title": "Divisional", "games": [
                make_game(one_seed or placeholder(), placeholder("Lowest remaining seed")),
                make_game(placeholder("Wild Card winner"), placeholder("Wild Card winner")),
            ]},
            {"title": f"{conf} championship", "games": [
                make_game(placeholder("Divisional winner"), placeholder("Divisional winner")),
            ]},
        ],
    }


def render_bracket_preview():
    """Render the projected bracket: AFC, NFC, then the Super Bowl."""
    seeds = get_playoff_seeds()
    sections = [_projected_section(conf, seeds.get(conf, {})) for conf in ("AFC", "NFC")]
    sections.append({
        "title": "Super Bowl",
        "rounds": [{"title": "Final", "games": [
            make_game(placeholder("AFC champion"), placeholder("NFC champion")),
        ]}],
    })
    st.html(build_bracket_html(
        sections,
        title="Playoff picture",
        note="Projected from current standings. Updates as seeds change.",
    ))
