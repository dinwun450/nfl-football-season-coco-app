import streamlit as st
from pathlib import Path

from utils.nfl_footer import render_footer
from utils.nfl_score_banner import render_score_banner
from utils.nfl_football_api import LIVE_REFRESH_SECONDS
from utils.nfl_data_loader import maybe_sync_results
from utils.snowflake_connector import snowflake_available

st.set_page_config(
    page_title="NFL Football Season", 
    page_icon="🏈", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.html(f"<style>{(Path(__file__).parent / 'app.css').read_text(encoding='utf-8')}</style>")

# Pages live in app_pages/ (not pages/) so Streamlit's legacy auto-navigation
# can't run them without this entrypoint's CSS and score banner.
home_page = st.Page("app_pages/0_overview.py", title="Overview", icon="🏈", url_path="overview", default=True)
venue_page = st.Page("app_pages/1_venue_map.py", title="Venue", icon="🏟️", url_path="venue_map")
standings_page = st.Page("app_pages/2_standings.py", title="Team Standings", icon="📊", url_path="standings")
brackets_page= st.Page("app_pages/3_bracket_builder.py", title="Bracket Builder", icon="🧩", url_path="bracket_builder")
injuries_page = st.Page("app_pages/4_injury_report.py", title="Injury Report", icon="🩹", url_path="injury_report")

pg = st.navigation([
    home_page,
    venue_page,
    standings_page,
    brackets_page,
    injuries_page,
])


@st.fragment(run_every=LIVE_REFRESH_SECONDS)
def score_banner():
    render_score_banner()
    # Game-by-game: push newly finished games + standings to NFL_SEASON (throttled, one session at a time).
    if snowflake_available():
        maybe_sync_results()


# Rendered in the entrypoint so it sits above every page.
score_banner()

pg.run()

# Also rendered in the entrypoint, so it sits below every page.
render_footer()