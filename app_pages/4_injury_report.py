import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.nfl_injuries_api import DESIGNATED_STATUSES, STATUS_ORDER, get_injury_report

STATUS_COLORS = {
    "Injured Reserve": "#7f1d1d",
    "Out": "#d50a0a",
    "Doubtful": "#f97316",
    "Questionable": "#facc15",
    "Day-To-Day": "#60a5fa",
    "Suspension": "#a78bfa",
    "Active": "#22c55e",
}

st.title("Injury report")
st.caption("League-wide injury designations for all 32 teams from ESPN. Refreshes every 15 minutes.")

report = get_injury_report()
if report.empty:
    st.error("The injury report is unavailable right now. Try again shortly.")
    st.stop()

# ---- Filters ----------------------------------------------------------------
statuses_present = [s for s in STATUS_ORDER if s in set(report["status"])]
statuses_present += sorted(set(report["status"]) - set(statuses_present))

with st.container(border=True):
    status_filter = st.pills(
        "Status",
        statuses_present,
        selection_mode="multi",
        default=[s for s in statuses_present if s in DESIGNATED_STATUSES],
        key="injury_status",
        help="'Active' entries are news notes for players without an injury designation.",
    )
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        teams = sorted(report["team_name"].dropna().unique())
        team_filter = st.multiselect("Teams", teams, placeholder="All teams", key="injury_teams")
        positions = sorted(report["position"].dropna().unique())
        position_filter = st.multiselect("Positions", positions, placeholder="All positions", key="injury_positions")
        search = st.text_input("Player", placeholder="Search by name", key="injury_search")

view = report[report["status"].isin(status_filter or [])]
if team_filter:
    view = view[view["team_name"].isin(team_filter)]
if position_filter:
    view = view[view["position"].isin(position_filter)]
if search:
    view = view[view["player"].str.contains(search, case=False, na=False, regex=False)]

# ---- Summary ----------------------------------------------------------------
counts = view["status"].value_counts()
metrics = st.columns(4)
for col, status in zip(metrics, ["Injured Reserve", "Out", "Doubtful", "Questionable"]):
    col.metric(status, int(counts.get(status, 0)))

updated = report["updated"].dropna().max()
if pd.notna(updated):
    st.caption(f"Latest update: {updated:%b %d, %Y %I:%M %p} ET \u00b7 {len(view)} of {len(report)} entries shown")

if view.empty:
    st.info("No players match the current filters.", icon=":material/healing:")
    st.stop()

# ---- Injuries by team chart -------------------------------------------------
by_team = view.groupby(["team_abbr", "status"]).size().reset_index(name="players")
order = by_team.groupby("team_abbr")["players"].sum().sort_values(ascending=False).index.tolist()
fig = px.bar(
    by_team,
    x="team_abbr",
    y="players",
    color="status",
    category_orders={"team_abbr": order, "status": STATUS_ORDER},
    color_discrete_map=STATUS_COLORS,
    labels={"team_abbr": "", "players": "Players", "status": "Status"},
    title="Injuries by team",
)
fig.update_layout(height=380, legend_title_text="", bargap=0.25)
st.plotly_chart(fig, key="injury_chart")

# ---- Detail -----------------------------------------------------------------
layout = st.segmented_control("View", ["By team", "All players"], default="By team", key="injury_view") or "By team"


def _injury_text(row):
    parts = [row["side"], row["injury"]]
    text = " ".join(p for p in parts if p)
    if row["detail"]:
        text = f"{text} ({row['detail']})" if text else row["detail"]
    return text or None


table = view.assign(injury_desc=view.apply(_injury_text, axis=1))
columns = {
    "headshot": st.column_config.ImageColumn("", width="small"),
    "player": st.column_config.TextColumn("Player"),
    "player_url": st.column_config.LinkColumn("Profile", display_text="ESPN"),
    "position": st.column_config.TextColumn("Pos", width="small"),
    "status": st.column_config.TextColumn("Status"),
    "injury_desc": st.column_config.TextColumn("Injury"),
    "return_date": st.column_config.DateColumn("Est. return", format="MMM D"),
    "updated": st.column_config.DatetimeColumn("Updated (ET)", format="MMM D, h:mm a"),
    "short_comment": st.column_config.TextColumn("Latest note", width="large"),
    "team_logo": st.column_config.ImageColumn("", width="small"),
    "team_abbr": st.column_config.TextColumn("Team", width="small"),
}
player_cols = ["headshot", "player", "position", "status", "injury_desc", "return_date", "updated", "short_comment", "player_url"]

if layout == "All players":
    st.dataframe(
        table,
        hide_index=True,
        column_order=["team_logo", "team_abbr"] + player_cols,
        column_config=columns,
        height=620,
    )
else:
    team_totals = table.groupby("team_name").size().sort_values(ascending=False)
    for team_name, total in team_totals.items():
        team_rows = table[table["team_name"] == team_name]
        severe = int(team_rows["status"].isin(["Injured Reserve", "Out"]).sum())
        label = f"{team_name} \u00b7 {total} listed \u00b7 {severe} out or on IR"
        with st.expander(label, icon=":material/personal_injury:"):
            st.dataframe(
                team_rows,
                hide_index=True,
                column_order=player_cols,
                column_config=columns,
            )
