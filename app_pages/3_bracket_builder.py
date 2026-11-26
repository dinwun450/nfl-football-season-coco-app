import os
import sys

import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.nfl_bracket_html import (
    WILD_CARD_PAIRS,
    build_bracket_html,
    make_game,
    placeholder,
)
from utils.nfl_bracket_preview import get_playoff_seeds

PICK_PREFIX = "pick_"

st.title("Bracket builder")
st.caption(
    "Seeds 1-7 come from the current standings. Pick a winner for each game; "
    "the 1 seed plays the lowest remaining seed in the Divisional round."
)

seeds = get_playoff_seeds()
if len(seeds.get("AFC", {})) < 7 or len(seeds.get("NFC", {})) < 7:
    st.warning("Playoff seeds aren't available yet, so the bracket can't be built.")
    st.stop()


def _clear_picks():
    for key in [k for k in st.session_state if str(k).startswith(PICK_PREFIX)]:
        del st.session_state[key]


with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    favor_seeds = st.toggle(
        "Pre-fill with higher seeds", key="favor_seeds", on_change=_clear_picks,
        help="Starts every game with the better seed picked. You can still change any pick.",
    )
    st.button("Reset picks", icon=":material/restart_alt:", on_click=_clear_picks)


def pick(round_key, top, bottom):
    """Winner picker for one game. Keyed by the matchup, so it resets if teams change."""
    if "team_id" not in top or "team_id" not in bottom:
        return None
    teams = {top["team_id"]: top, bottom["team_id"]: bottom}
    better = min(teams.values(), key=lambda t: t["seed"])["team_id"]
    choice = st.segmented_control(
        f"{top['abbreviation']} vs {bottom['abbreviation']}",
        list(teams),
        format_func=lambda tid: f"({teams[tid]['seed']}) {teams[tid]['abbreviation']}",
        default=better if favor_seeds else None,
        # Mode is part of the key so toggling pre-fill recreates the widget with its new default.
        key=f"{PICK_PREFIX}{'fav_' if favor_seeds else ''}{round_key}_{top['team_id']}_{bottom['team_id']}",
    )
    return teams.get(choice)


def conference_bracket(conf, by_seed):
    """Render this conference's pickers; return (bracket section, champion slot)."""
    st.markdown(f"**{conf}**")

    st.caption("Wild Card")
    wc_games, wc_winners = [], []
    for a, b in WILD_CARD_PAIRS:
        top, bottom = by_seed[a], by_seed[b]
        winner = pick(f"{conf}_wc", top, bottom)
        wc_games.append(make_game(top, bottom, winner and winner["team_id"]))
        wc_winners.append(winner)

    one_seed = {**by_seed[1], "note": "BYE"}
    st.caption("Divisional")
    if all(wc_winners):
        remaining = sorted(wc_winners, key=lambda t: t["seed"])
        div_pairs = [(one_seed, remaining[2]), (remaining[0], remaining[1])]
    else:
        div_pairs = [
            (one_seed, placeholder("Lowest remaining seed")),
            (placeholder("Wild Card winner"), placeholder("Wild Card winner")),
        ]
        st.caption(":gray[Pick every Wild Card game to unlock this round.]")
    div_games, div_winners = [], []
    for top, bottom in div_pairs:
        winner = pick(f"{conf}_div", top, bottom)
        div_games.append(make_game(top, bottom, winner and winner["team_id"]))
        div_winners.append(winner)

    st.caption(f"{conf} championship")
    if all(div_winners):
        top, bottom = sorted(div_winners, key=lambda t: t["seed"])
    else:
        top, bottom = placeholder("Divisional winner"), placeholder("Divisional winner")
    champion = pick(f"{conf}_cc", top, bottom)

    section = {
        "title": conf,
        "rounds": [
            {"title": "Wild Card", "games": wc_games},
            {"title": "Divisional", "games": div_games},
            {"title": f"{conf} championship", "games": [make_game(top, bottom, champion and champion["team_id"])]},
        ],
    }
    return section, champion


picks_col, bracket_col = st.columns([2, 3], gap="large")

with picks_col:
    with st.container(border=True):
        afc_section, afc_champ = conference_bracket("AFC", seeds["AFC"])
    with st.container(border=True):
        nfc_section, nfc_champ = conference_bracket("NFC", seeds["NFC"])
    with st.container(border=True):
        st.markdown("**Super Bowl**")
        sb_top = {**afc_champ, "note": "AFC"} if afc_champ else placeholder("AFC champion")
        sb_bottom = {**nfc_champ, "note": "NFC"} if nfc_champ else placeholder("NFC champion")
        if not (afc_champ and nfc_champ):
            st.caption(":gray[Pick both conference champions to unlock the Super Bowl.]")
        sb_winner = pick("sb", sb_top, sb_bottom)

with bracket_col:
    if sb_winner:
        st.success(f"Your Super Bowl champion: {sb_winner['team_name']}", icon=":material/emoji_events:")
    sections = [
        afc_section,
        nfc_section,
        {"title": "Super Bowl", "rounds": [{"title": "Final", "games": [
            make_game(sb_top, sb_bottom, sb_winner and sb_winner["team_id"]),
        ]}]},
    ]
    st.html(build_bracket_html(
        sections,
        title="Your bracket",
        note="Built from current standings seeds.",
        champion=sb_winner,
    ))
