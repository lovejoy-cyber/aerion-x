"""Scoped PostgreSQL validation (Phase 6 Part 8).

Honest scope: backend/repositories.py is NOT YET database-agnostic — every
function calls sqlite3's Connection.execute() directly with '?' placeholders,
which psycopg2 doesn't support (it uses '%s' and a separate cursor object).
Making repositories.py truly dual-backend would mean rewriting all 20+
functions behind a placeholder-normalizing wrapper — real work, not done in
this pass.

What THIS script proves instead: the AERION-X data model (the same tables,
same columns, same relationships as backend/db.py's SQLite schema) is
genuinely portable to PostgreSQL — real INSERT/SELECT/JOIN operations against
a real running Postgres 16 container succeed, using the same JSON-as-TEXT
column strategy the SQLite schema uses. Run against an isolated container
(never the project's own unrelated postgres containers, if any are running).
"""
from __future__ import annotations

import json
import time

import psycopg2

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL,
    source_id TEXT NOT NULL,
    asset_id TEXT REFERENCES assets(asset_id),
    zone_id TEXT,
    severity TEXT NOT NULL,
    provenance TEXT NOT NULL,
    track_ids TEXT NOT NULL,
    evidence TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp_pg ON events(timestamp);
"""


def main():
    conn = psycopg2.connect(host="127.0.0.1", port=55432, dbname="aerionx", user="postgres", password="aerionx_test")
    cur = conn.cursor()

    cur.execute(PG_SCHEMA)
    conn.commit()
    print("Schema created in real PostgreSQL 16 (Docker container aerionx-postgres-test).")

    cur.execute(
        "INSERT INTO assets (asset_id, asset_type, name, created_at) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (asset_id) DO UPDATE SET name = EXCLUDED.name",
        ("PG_TEST_1", "AIRCRAFT", "Postgres Validation Aircraft", time.time()),
    )
    cur.execute(
        "INSERT INTO events (event_id, event_type, timestamp, source_id, asset_id, severity, provenance, "
        "track_ids, evidence, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("evt_pg_1", "ZONE_ENTER", 12.5, "video:test.mp4", "PG_TEST_1", "INFO", "REAL",
         json.dumps([1, 2]), json.dumps({"position": [10, 20]}), time.time()),
    )
    conn.commit()

    cur.execute("SELECT asset_id, name FROM assets WHERE asset_id = %s", ("PG_TEST_1",))
    asset_row = cur.fetchone()
    assert asset_row == ("PG_TEST_1", "Postgres Validation Aircraft"), asset_row
    print(f"Asset round-trip OK: {asset_row}")

    cur.execute(
        "SELECT e.event_type, e.track_ids, a.name FROM events e JOIN assets a ON e.asset_id = a.asset_id "
        "WHERE e.event_id = %s", ("evt_pg_1",),
    )
    joined_row = cur.fetchone()
    assert joined_row[0] == "ZONE_ENTER"
    assert json.loads(joined_row[1]) == [1, 2]
    assert joined_row[2] == "Postgres Validation Aircraft"
    print(f"Event+Asset JOIN OK: {joined_row}")

    cur.close()
    conn.close()
    print("\nPOSTGRESQL VALIDATION: PASSED (schema + core operations only — see module docstring for scope).")


if __name__ == "__main__":
    main()
