"""Load NFL_SEASON.PUBLIC from ESPN (teams, venues, full schedule, byes, standings).

Usage (from the project root, with the project venv):
    venv\\Scripts\\python.exe -m utils.load_nfl_season            # full load
    venv\\Scripts\\python.exe -m utils.load_nfl_season --results  # game-by-game refresh only

Uses the same [connections.snowflake] block as the Streamlit app.
"""
import argparse
import os
import sys
import tomllib
from pathlib import Path

import snowflake.connector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.nfl_snowflake_sync import sync_all, sync_results  # noqa: E402


def connect():
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))
    snowflake.connector.paramstyle = "qmark"
    return snowflake.connector.connect(**secrets["connections"]["snowflake"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", action="store_true", help="only refresh this week's games and standings")
    args = parser.parse_args()
    conn = connect()
    try:
        print(sync_results(conn) if args.results else sync_all(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
