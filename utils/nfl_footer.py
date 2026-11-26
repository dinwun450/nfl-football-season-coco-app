"""App-wide footer: credits line rendered below every page."""
import streamlit as st

_FOOTER_HTML = """
<style>
  .nfl-footer { margin-top: 48px; padding: 18px 16px 6px; text-align: center;
    border-top: 1px solid rgba(128, 128, 128, .25); font-size: 13px; letter-spacing: .2px; opacity: .85; }
  .nfl-footer a { color: inherit; font-weight: 700; text-decoration: none;
    border-bottom: 1px solid rgba(41, 181, 232, .6); transition: color .15s, border-color .15s; }
  .nfl-footer a:hover { color: #29b5e8; border-color: #29b5e8; }
  .nfl-footer-heart { color: #ff3b6b; font-weight: 800; display: inline-block;
    animation: nfl-heartbeat 1.6s ease-in-out infinite; }
  @keyframes nfl-heartbeat { 0%, 100% { transform: scale(1); } 15% { transform: scale(1.25); } 30% { transform: scale(1); } }
</style>
<div class="nfl-footer">
  Data powered by Snowflake &amp; made with <span class="nfl-footer-heart">&lt;3</span> with CoCo.
  Built by <a href="https://www.linkedin.com/in/dinowun" target="_blank" rel="noopener noreferrer">Dino Wun</a>
</div>
"""


def render_footer():
    st.html(_FOOTER_HTML)
