import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.nfl_stats_api import HIGHER_IS_BETTER, STAT_LABELS, get_standings, get_team_stats

st.title("Team standings")

standings = get_standings()
if standings.empty:
    st.error("Standings are unavailable right now. Try again shortly.")
    st.stop()

season = int(standings["season"].dropna().iloc[0])
COMPARE_COLORS = ("#1f77b4", "#ff7f0e")  # fixed and distinct; many team colors clash (e.g. ARI vs ATL)

conference = st.segmented_control(
    "Conference", ["AFC", "NFC", "Both"], default="Both", key="standings_conference"
) or "Both"
view = standings if conference == "Both" else standings[standings["conference"] == conference]

# ---- Standings tables -------------------------------------------------------
st.subheader(f"{season} standings")
table_cols = {
    "logo_url": st.column_config.ImageColumn("", width="small"),
    "team_name": st.column_config.TextColumn("Team"),
    "playoff_seed": st.column_config.NumberColumn("Rank", format="%d", help="Conference rank; 1-7 are in playoff position"),
    "record": st.column_config.TextColumn("Record"),
    "win_pct": st.column_config.ProgressColumn("Win %", format="%.3f", min_value=0.0, max_value=1.0),
    "points_for": st.column_config.NumberColumn("PF"),
    "points_against": st.column_config.NumberColumn("PA"),
    "point_differential": st.column_config.NumberColumn("Diff", format="%+d"),
    "streak": st.column_config.TextColumn("Streak"),
    "home_record": st.column_config.TextColumn("Home"),
    "road_record": st.column_config.TextColumn("Road"),
    "division_record": st.column_config.TextColumn("Div"),
    "conference_record": st.column_config.TextColumn("Conf"),
}
group_by = st.segmented_control(
    "Group by", ["Conference", "Division"], default="Conference", key="standings_group"
) or "Conference"

for conf in sorted(view["conference"].unique()):
    conf_df = view[view["conference"] == conf]
    if group_by == "Conference":
        st.markdown(f"**{conf}**")
        st.dataframe(
            conf_df.sort_values("conference_rank"),
            hide_index=True,
            column_order=list(table_cols),
            column_config=table_cols,
        )
    else:
        cols = st.columns(2)
        for i, (division, div_df) in enumerate(conf_df.groupby("division")):
            with cols[i % 2]:
                st.markdown(f"**{division}**")
                st.dataframe(
                    div_df.sort_values("division_rank"),
                    hide_index=True,
                    column_order=["logo_url", "team_name", "record", "win_pct", "point_differential", "streak"],
                    column_config=table_cols,
                )

# ---- Charts -----------------------------------------------------------------
st.subheader("Season at a glance")
chart_left, chart_right = st.columns(2)

with chart_left:
    ranked = view.sort_values("win_pct")
    fig = px.bar(
        ranked,
        x="win_pct",
        y="abbreviation",
        color="division",
        orientation="h",
        hover_data={"team_name": True, "record": True, "win_pct": ":.3f", "abbreviation": False},
        labels={"win_pct": "Win %", "abbreviation": "", "division": "Division"},
        title="Win percentage",
    )
    fig.update_layout(height=max(420, 22 * len(ranked)), xaxis_range=[0, 1], legend_title_text="")
    st.plotly_chart(fig, key="win_pct_chart")

with chart_right:
    fig = px.scatter(
        view,
        x="points_for",
        y="points_against",
        text="abbreviation",
        color="conference",
        color_discrete_map={"AFC": "#d50a0a", "NFC": "#013369"},
        hover_data={"team_name": True, "record": True, "point_differential": True},
        labels={"points_for": "Points for", "points_against": "Points against", "conference": ""},
        title="Points for vs. against",
    )
    fig.update_traces(textposition="top center", marker_size=10)
    fig.add_hline(y=view["points_against"].mean(), line_dash="dot", line_color="gray")
    fig.add_vline(x=view["points_for"].mean(), line_dash="dot", line_color="gray")
    fig.update_yaxes(autorange="reversed")  # better defenses at the top
    fig.update_layout(height=520)
    st.plotly_chart(fig, key="points_chart")
    st.caption("Top-right is best: high scoring, few points allowed. Dotted lines are the averages.")

# ---- Team comparison --------------------------------------------------------
st.subheader("Compare teams")
team_names = standings.sort_values("team_name").set_index("team_id")["team_name"].to_dict()
ids = list(team_names)

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    team_a = st.selectbox("Team A", ids, index=0, format_func=team_names.get, key="compare_a")
    team_b = st.selectbox("Team B", ids, index=1, format_func=team_names.get, key="compare_b")

if team_a == team_b:
    st.warning("Pick two different teams to compare.")
    st.stop()

with st.spinner("Loading team stats..."):
    league = get_team_stats(tuple(ids), season)

if league.dropna(how="all").empty:
    st.error("Team stats are unavailable right now.")
    st.stop()

# League percentile per stat, flipped where lower is better (giveaways, penalties).
percentiles = league.rank(pct=True)
for label in STAT_LABELS:
    if not HIGHER_IS_BETTER[label]:
        percentiles[label] = 1 - percentiles[label] + 1 / len(league)

row_a, row_b = standings.set_index("team_id").loc[team_a], standings.set_index("team_id").loc[team_b]
summary = st.columns(2)
for col, row in zip(summary, (row_a, row_b)):
    with col, st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.image(row["logo_url"], width=48)
            st.markdown(f"### {row['team_name']}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Record", row["record"])
        seed = int(row["playoff_seed"]) if pd.notna(row["playoff_seed"]) else None
        m2.metric("Playoff seed", seed if seed and seed <= 7 else "Out", help=f"Conference rank: {seed or '-'}")
        m3.metric("Point diff", f"{int(row['point_differential']):+d}")

radar = go.Figure()
for team_id, color in zip((team_a, team_b), COMPARE_COLORS):
    values = (percentiles.loc[team_id, STAT_LABELS] * 100).round(0).tolist()
    radar.add_trace(go.Scatterpolar(
        r=values + values[:1],
        theta=STAT_LABELS + STAT_LABELS[:1],
        fill="toself",
        name=team_names[team_id],
        line_color=color,
        opacity=0.6,
    ))
radar.update_layout(
    polar={"radialaxis": {"range": [0, 100], "ticksuffix": "%", "tickfont": {"size": 9}}},
    title="League percentile by stat (higher is better)",
    legend={"orientation": "h", "y": -0.1},
    margin={"l": 90, "r": 90, "t": 60, "b": 40},
    height=560,
)

compare_left, compare_right = st.columns([3, 2])
with compare_left:
    st.plotly_chart(radar, key="compare_radar")
with compare_right:
    abbrs = standings.set_index("team_id")["abbreviation"]
    a_name, b_name = abbrs[team_a], abbrs[team_b]
    raw = league.loc[[team_a, team_b], STAT_LABELS].T
    raw.columns = [a_name, b_name]

    def edge(stat):
        a, b = raw.loc[stat, a_name], raw.loc[stat, b_name]
        if pd.isna(a) or pd.isna(b) or a == b:
            return "Even"
        better_a = a > b if HIGHER_IS_BETTER[stat] else a < b
        return a_name if better_a else b_name

    raw["Edge"] = [edge(s) for s in raw.index]
    st.dataframe(
        raw.reset_index(names="Stat"),
        hide_index=True,
        column_config={
            a_name: st.column_config.NumberColumn(format="%.1f"),
            b_name: st.column_config.NumberColumn(format="%.1f"),
        },
        height=460,
    )
    wins_a = (raw["Edge"] == a_name).sum()
    wins_b = (raw["Edge"] == b_name).sum()
    st.caption(f"{team_names[team_a]} leads {wins_a} categories, {team_names[team_b]} leads {wins_b}.")
