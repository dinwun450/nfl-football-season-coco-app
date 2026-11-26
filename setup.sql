-- NFL_SEASON schema. Safe to re-run: tables use IF NOT EXISTS so loaded data is kept.
-- Data is loaded from ESPN by Python (no external access integration):
--   venv\Scripts\python.exe -m utils.load_nfl_season            -- full load
--   venv\Scripts\python.exe -m utils.load_nfl_season --results  -- game-by-game refresh
-- The Streamlit app also runs the game-by-game refresh every ~2 minutes while open.
CREATE DATABASE IF NOT EXISTS nfl_season;
USE DATABASE nfl_season;
USE SCHEMA PUBLIC;

CREATE TABLE IF NOT EXISTS nfl_teams (
    team_id INT PRIMARY KEY,        -- ESPN team id
    team_name VARCHAR(255),
    team_nickname VARCHAR(255),
    city VARCHAR(255),
    color VARCHAR(255),             -- hex without '#'
    alt_color VARCHAR(255),
    logo_url VARCHAR(255),
    abbreviation VARCHAR(8),        -- e.g. 'KC'
    conference VARCHAR(3),          -- 'AFC' | 'NFC'
    division VARCHAR(16)            -- e.g. 'AFC West'
);

CREATE TABLE IF NOT EXISTS nfl_venues (
    venue_id INT PRIMARY KEY,       -- ESPN venue id
    venue_name VARCHAR(255),
    city VARCHAR(255),
    state VARCHAR(255),
    zip_code VARCHAR(255),
    country VARCHAR(64),
    indoor BOOLEAN,
    latitude FLOAT,                 -- seeded by the loader; never overwritten with NULL
    longitude FLOAT
);

CREATE TABLE IF NOT EXISTS nfl_matches (
    match_id INT PRIMARY KEY,       -- ESPN event id
    week INT,
    home_team_id INT,               -- -1/-2 = TBD postseason placeholder
    away_team_id INT,
    venue_id INT,
    match_date TIMESTAMP_NTZ,       -- kickoff in UTC
    season INT,
    season_type INT,                -- 1 pre, 2 regular, 3 post
    neutral_site BOOLEAN,
    status VARCHAR(32),             -- e.g. STATUS_SCHEDULED, STATUS_FINAL
    home_score INT,
    away_score INT,
    broadcasts VARCHAR(255),
    updated_at TIMESTAMP_NTZ
);

-- Updated game by game: refreshed whenever a match newly reaches STATUS_FINAL.
CREATE TABLE IF NOT EXISTS nfl_team_standings (
    team_id INT PRIMARY KEY,
    season INT,
    conference VARCHAR(3),          -- 'AFC' | 'NFC'
    division VARCHAR(16),           -- e.g. 'AFC East'
    wins INT,
    losses INT,
    ties INT,
    win_pct FLOAT,                  -- ESPN winPercent (ties count as half a win)
    points_for INT,
    points_against INT,
    point_differential INT,
    playoff_seed INT,               -- ESPN rank within conference; 1-7 = playoff position
    streak VARCHAR(8),              -- e.g. 'W3', 'L1'
    division_record VARCHAR(8),
    conference_record VARCHAR(8),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    home_record VARCHAR(8),
    road_record VARCHAR(8)
);

CREATE TABLE IF NOT EXISTS nfl_team_byes (
    season INT,
    team_id INT,
    bye_week INT,
    PRIMARY KEY (season, team_id)
);

-- Conference rankings: ESPN's playoff seed when available, otherwise
-- win %, point differential, then points scored as tiebreakers.
-- A view, so it reflects nfl_team_standings immediately after each refresh.
CREATE OR REPLACE VIEW nfl_conference_standings AS
SELECT
    s.conference,
    RANK() OVER (
        PARTITION BY s.conference
        ORDER BY s.playoff_seed ASC NULLS LAST,
                 s.win_pct DESC,
                 s.point_differential DESC,
                 s.points_for DESC
    ) AS conference_rank,
    RANK() OVER (
        PARTITION BY s.division
        -- ESPN's seed already applies NFL tiebreakers (head-to-head, division record...).
        ORDER BY s.playoff_seed ASC NULLS LAST,
                 s.win_pct DESC,
                 s.point_differential DESC
    ) AS division_rank,
    s.playoff_seed BETWEEN 1 AND 7 AS in_playoff_position,
    s.team_id,
    t.team_name,
    t.team_nickname,
    t.abbreviation,
    t.logo_url,
    t.color,
    t.alt_color,
    s.division,
    s.wins,
    s.losses,
    s.ties,
    s.wins || '-' || s.losses || IFF(s.ties > 0, '-' || s.ties, '') AS record,
    s.win_pct,
    s.points_for,
    s.points_against,
    s.point_differential,
    s.playoff_seed,
    s.streak,
    s.home_record,
    s.road_record,
    s.division_record,
    s.conference_record,
    s.season,
    s.updated_at
FROM nfl_team_standings s
JOIN nfl_teams t ON t.team_id = s.team_id;
