"""Snowflake access for the app via st.connection("snowflake").

Connection settings live in .streamlit/secrets.toml under [connections.snowflake]
(password auth; see that file). In Streamlit in Snowflake the same call uses the
app's session automatically.
"""
import logging

import pandas as pd
import streamlit as st

_LOG = logging.getLogger(__name__)


def get_connection():
    """Shared, cached Snowflake connection (st.connection caches it already)."""
    return st.connection("snowflake")


def run_query(sql, params=None, ttl=300):
    """Run a read query and return a DataFrame (column names upper-case, as in Snowflake).

    Values must go through `params` (qmark `?` placeholders), never string formatting.
    Parameterized queries skip `.query()`: its cache is keyed on the SQL text only, so
    the same SQL with different params would return the first cached result. Callers
    cache with @st.cache_data, whose key does include the arguments.
    """
    conn = get_connection()
    if params:
        cur = conn.raw_connection.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetch_pandas_all()
        finally:
            cur.close()
    return conn.query(sql, ttl=ttl, show_spinner=False)


@st.cache_data(ttl=60, show_spinner=False)
def snowflake_available():
    """True when NFL_SEASON is reachable; pages fall back to the ESPN API otherwise."""
    try:
        get_connection().query("SELECT 1 AS OK", ttl=0, show_spinner=False)
        return True
    except Exception as exc:  # connection/config errors vary by driver version
        _LOG.warning("Snowflake unavailable, using ESPN API fallback: %s", exc)
        return False


def lower_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Snowflake returns upper-case columns; the app uses lower-case names."""
    return df.rename(columns=str.lower)
