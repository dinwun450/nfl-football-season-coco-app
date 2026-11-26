import html
import os
import sys

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.nfl_data_loader import load_teams, load_venues
from utils.snowflake_connector import snowflake_available

US_CENTER = (39.5, -97.5)
WORLD_CENTER = (30.0, -40.0)
CONFERENCE_COLORS = {"AFC": "#d50a0a", "NFC": "#013369"}
INTERNATIONAL_COLOR = "#c9a227"
SHARED_OFFSET = 0.0012  # degrees; separates the two tenants of a shared stadium

st.title("Stadium map")
st.caption("Venues from Snowflake NFL_SEASON.PUBLIC.NFL_VENUES. Click a marker for details and the next game.")

if not snowflake_available():
    st.error("Can't reach Snowflake, so venues can't be loaded. Check .streamlit/secrets.toml.")
    st.stop()

venues = load_venues().dropna(subset=["latitude", "longitude"])
teams = load_teams().set_index("abbreviation").to_dict("index")
venues["tenants"] = venues["home_teams"].fillna("").map(lambda s: [t for t in s.split(",") if t])
venues["international"] = venues["tenants"].map(len) == 0

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    conference = st.segmented_control(
        "Conference", ["All", "AFC", "NFC"], default="All", key="venue_conference"
    ) or "All"
    roof = st.segmented_control(
        "Roof", ["All", "Indoor", "Outdoor"], default="All", key="venue_roof"
    ) or "All"
    show_international = st.toggle("International series", value=True, key="venue_international")


def _visible_tenants(row):
    if conference == "All":
        return row["tenants"]
    return [t for t in row["tenants"] if teams.get(t, {}).get("conference") == conference]


view = venues.copy()
view["shown_tenants"] = view.apply(_visible_tenants, axis=1)
keep = view["shown_tenants"].map(len) > 0
if show_international and conference == "All":
    keep |= view["international"]
view = view[keep]
if roof != "All":
    view = view[view["indoor"].fillna(False) == (roof == "Indoor")]

focus = st.selectbox("Zoom to stadium", ["All stadiums"] + view["venue_name"].tolist(), key="venue_focus")
focused = view[view["venue_name"] == focus].iloc[0] if focus != "All stadiums" else None


def _next_game_text(row):
    if pd.isna(row["next_game_utc"]):
        return None
    kickoff = pd.Timestamp(row["next_game_utc"]).tz_localize("UTC").tz_convert("America/New_York")
    return f"{row['next_matchup']} \u00b7 {kickoff:%b %d, %I:%M %p} ET"


def _popup_html(row):
    e = html.escape
    place = ", ".join(x for x in (row["city"], row["state"] or row["country"]) if x)
    if row["tenants"]:
        home = ", ".join(e(teams.get(t, {}).get("team_name", t)) for t in row["tenants"])
    else:
        home = "International series"
    lines = [
        f"<b>{e(row['venue_name'])}</b>",
        e(place),
        f"Home of: {home}",
        f"Roof: {'Indoor' if row['indoor'] else 'Outdoor'} \u00b7 {int(row['games'])} games this season",
    ]
    next_game = _next_game_text(row)
    if next_game:
        lines.append(f"Next: {e(next_game)}")
    return "<br>".join(lines)


if focused is not None:
    center, zoom = (focused["latitude"], focused["longitude"]), 13
elif show_international and view["international"].any():
    center, zoom = WORLD_CENTER, 2
else:
    center, zoom = US_CENTER, 4
fmap = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")  # CARTO tiles need an API key

for _, row in view.iterrows():
    popup_html = _popup_html(row)
    markers = row["shown_tenants"] or [None]  # None = international venue
    for i, abbr in enumerate(markers):
        if abbr is None:
            color, tooltip = INTERNATIONAL_COLOR, f"{row['venue_name']} (international)"
        else:
            team = teams.get(abbr, {})
            color = CONFERENCE_COLORS.get(team.get("conference"), "#8d99ae")
            tooltip = f"{team.get('team_name', abbr)} - {row['venue_name']}"
        # Shared stadiums (SoFi, MetLife) host one AFC and one NFC team.
        offset = (i - (len(markers) - 1) / 2) * SHARED_OFFSET
        folium.CircleMarker(
            location=(row["latitude"], row["longitude"] + offset),
            radius=8,
            color="white",
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.95,
            tooltip=tooltip,
            # One Popup per marker: Folium can't attach a single Popup to two markers.
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(fmap)

st.markdown(":red[\u25cf] AFC &nbsp;&nbsp; :blue[\u25cf] NFC &nbsp;&nbsp; :orange[\u25cf] International series")

# returned_objects=[] keeps panning and zooming from rerunning the page.
st_folium(fmap, height=560, use_container_width=True, returned_objects=[], key="venue_map")

st.subheader("Stadiums")
table = pd.DataFrame({
    "Logo": view["tenants"].map(lambda t: teams.get(t[0], {}).get("logo_url") if t else None),
    "Stadium": view["venue_name"],
    "Location": view.apply(lambda r: ", ".join(x for x in (r["city"], r["state"] or r["country"]) if x), axis=1),
    "Teams": view["tenants"].map(lambda t: ", ".join(t) or "International"),
    "Roof": view["indoor"].map(lambda v: "Indoor" if v else "Outdoor"),
    "Games": view["games"].astype(int),
    "Next game": view.apply(_next_game_text, axis=1),
})
if table.empty:
    st.info("No stadiums match the current filters.")
else:
    st.dataframe(
        table,
        hide_index=True,
        column_config={"Logo": st.column_config.ImageColumn("", width="small")},
    )
