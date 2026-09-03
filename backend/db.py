"""Real SQLite persistence. Uses stdlib sqlite3 directly (no ORM) — the schema
is small and explicit enough that raw SQL is more honest than an abstraction
layer that would hide what's actually happening. Swapping to PostgreSQL later
means replacing this module's connection/execute helpers; callers (repositories.py)
use only `execute`/`query`, so that migration doesn't ripple outward.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = "data/db/aerionx.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    source_id TEXT NOT NULL,
    asset_id TEXT,
    zone_id TEXT,
    severity TEXT NOT NULL,
    confidence REAL,
    duration REAL,
    provenance TEXT NOT NULL,
    track_ids TEXT NOT NULL,      -- JSON array
    evidence TEXT NOT NULL,       -- JSON object
    metadata TEXT NOT NULL,       -- JSON object
    created_at REAL NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_asset ON events(asset_id);

CREATE TABLE IF NOT EXISTS sensor_streams (
    stream_id TEXT PRIMARY KEY,
    signal_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    provenance TEXT NOT NULL,
    asset_id TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (stream_id) REFERENCES sensor_streams(stream_id)
);
CREATE INDEX IF NOT EXISTS idx_readings_stream ON sensor_readings(stream_id);

CREATE TABLE IF NOT EXISTS anomaly_results (
    anomaly_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    value REAL NOT NULL,
    score REAL NOT NULL,
    threshold REAL NOT NULL,
    algorithm TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (stream_id) REFERENCES sensor_streams(stream_id)
);

CREATE TABLE IF NOT EXISTS inspections (
    inspection_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    change_score REAL NOT NULL,
    mean_ssim REAL NOT NULL,
    anomaly_regions TEXT NOT NULL,  -- JSON array
    notes TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE IF NOT EXISTS correlations (
    correlation_id TEXT PRIMARY KEY,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    event_ids TEXT NOT NULL,      -- JSON array
    event_types TEXT NOT NULL,    -- JSON array
    sources TEXT NOT NULL,        -- JSON array
    provenance_note TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    framework TEXT NOT NULL,
    task TEXT NOT NULL,
    classes TEXT NOT NULL,        -- JSON array
    input_resolution TEXT NOT NULL,
    weights_source TEXT NOT NULL,
    license TEXT NOT NULL,
    hardware TEXT NOT NULL,
    num_parameters INTEGER,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL,           -- ADMIN | ENGINEER | OPERATOR
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    result TEXT NOT NULL,          -- SUCCESS | DENIED | ERROR
    metadata TEXT NOT NULL         -- JSON object, never secrets
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,          -- RUNNING | STOPPED | ERROR | COMPLETED
    started_at REAL NOT NULL,
    ended_at REAL,
    frames_processed INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
