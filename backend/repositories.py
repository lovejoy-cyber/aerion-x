"""Repositories: translate between core domain objects (Event, Asset, etc.)
and SQLite rows. Callers never write SQL directly — services.py and the API
layer go through these functions only.
"""
from __future__ import annotations

import json
import sqlite3
import time

from core.assets.domain import Asset
from core.contracts import Event
from core.correlation.correlation_engine import CorrelatedEvent
from core.inspection.pipeline import InspectionReport
from core.model_lab.registry import ModelRecord
from core.sensors.anomaly import AnomalyResult
from core.sensors.telemetry import TelemetryStream


def save_asset(conn: sqlite3.Connection, asset: Asset) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO assets (asset_id, asset_type, name, created_at) VALUES (?, ?, ?, ?)",
        (asset.asset_id, asset.asset_type.value, asset.name, time.time()),
    )
    conn.commit()


def get_asset(conn: sqlite3.Connection, asset_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def list_assets(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM assets ORDER BY created_at DESC")]


def save_event(conn: sqlite3.Connection, event: Event) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO events
        (event_id, event_type, timestamp, source_id, asset_id, zone_id, severity,
         confidence, duration, provenance, track_ids, evidence, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event.event_id, event.event_type, event.timestamp, event.source_id, event.asset_id,
         event.zone_id, event.severity.value, event.confidence, event.duration, event.provenance,
         json.dumps(event.track_ids), json.dumps(event.evidence), json.dumps(event.metadata), time.time()),
    )
    conn.commit()


def save_events(conn: sqlite3.Connection, events: list[Event]) -> int:
    for e in events:
        conn.execute(
            """INSERT OR REPLACE INTO events
            (event_id, event_type, timestamp, source_id, asset_id, zone_id, severity,
             confidence, duration, provenance, track_ids, evidence, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e.event_id, e.event_type, e.timestamp, e.source_id, e.asset_id,
             e.zone_id, e.severity.value, e.confidence, e.duration, e.provenance,
             json.dumps(e.track_ids), json.dumps(e.evidence), json.dumps(e.metadata), time.time()),
        )
    conn.commit()
    return len(events)


def list_events(conn: sqlite3.Connection, event_type: str | None = None, limit: int = 100,
                 offset: int = 0, severity: str | None = None) -> list[dict]:
    """Server-side filtered + paginated — the caller never needs to load the
    full event history into memory to see one page of it."""
    clauses, params = [], []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params += [limit, offset]
    rows = conn.execute(
        f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", params
    ).fetchall()
    return [_event_row_to_dict(r) for r in rows]


def count_events(conn: sqlite3.Connection, event_type: str | None = None, severity: str | None = None) -> int:
    clauses, params = [], []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) as n FROM events {where}", params).fetchone()
    return row["n"]


def _event_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["track_ids"] = json.loads(d["track_ids"])
    d["evidence"] = json.loads(d["evidence"])
    d["metadata"] = json.loads(d["metadata"])
    return d


def save_sensor_stream(conn: sqlite3.Connection, stream: TelemetryStream, asset_id: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sensor_streams (stream_id, signal_name, unit, provenance, asset_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (stream.stream_id, stream.signal_name, stream.unit, stream.provenance.value, asset_id, time.time()),
    )
    # Idempotent re-save: without this, calling save_sensor_stream twice for the
    # same stream_id (e.g. a user clicking "generate" twice in the GUI) would
    # silently duplicate every reading instead of replacing them.
    conn.execute("DELETE FROM sensor_readings WHERE stream_id = ?", (stream.stream_id,))
    for r in stream.readings:
        conn.execute(
            "INSERT INTO sensor_readings (stream_id, timestamp, value) VALUES (?, ?, ?)",
            (stream.stream_id, r.timestamp, r.value),
        )
    conn.commit()


def list_sensor_streams(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM sensor_streams ORDER BY created_at DESC")]


def get_sensor_readings(conn: sqlite3.Connection, stream_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT timestamp, value FROM sensor_readings WHERE stream_id = ? ORDER BY timestamp", (stream_id,)
    )]


def save_anomaly_results(conn: sqlite3.Connection, stream_id: str, results: list[AnomalyResult]) -> int:
    for i, r in enumerate(results):
        anomaly_id = f"anom_{stream_id}_{r.timestamp}_{i}"
        conn.execute(
            """INSERT OR REPLACE INTO anomaly_results
            (anomaly_id, stream_id, timestamp, value, score, threshold, algorithm, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (anomaly_id, stream_id, r.timestamp, r.value, r.score, r.threshold, r.algorithm, r.reason, time.time()),
        )
    conn.commit()
    return len(results)


def list_anomalies(conn: sqlite3.Connection, stream_id: str | None = None) -> list[dict]:
    if stream_id:
        rows = conn.execute("SELECT * FROM anomaly_results WHERE stream_id = ? ORDER BY timestamp", (stream_id,))
    else:
        rows = conn.execute("SELECT * FROM anomaly_results ORDER BY timestamp DESC LIMIT 200")
    return [dict(r) for r in rows]


def save_inspection(conn: sqlite3.Connection, report: InspectionReport) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO inspections
        (inspection_id, asset_id, timestamp, change_score, mean_ssim, anomaly_regions, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (report.inspection_id, report.asset_id, report.timestamp, report.change_score, report.mean_ssim,
         json.dumps(report.anomaly_regions), report.notes, time.time()),
    )
    conn.commit()


def list_inspections(conn: sqlite3.Connection, asset_id: str | None = None) -> list[dict]:
    if asset_id:
        rows = conn.execute("SELECT * FROM inspections WHERE asset_id = ? ORDER BY timestamp DESC", (asset_id,))
    else:
        rows = conn.execute("SELECT * FROM inspections ORDER BY timestamp DESC")
    results = []
    for r in rows:
        d = dict(r)
        d["anomaly_regions"] = json.loads(d["anomaly_regions"])
        results.append(d)
    return results


def save_correlation(conn: sqlite3.Connection, corr: CorrelatedEvent) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO correlations
        (correlation_id, window_start, window_end, event_ids, event_types, sources, provenance_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (corr.correlation_id, corr.window_start, corr.window_end,
         json.dumps([e.event_id for e in corr.events]), json.dumps(sorted(corr.event_types)),
         json.dumps(sorted(corr.sources)), corr.provenance_note, time.time()),
    )
    conn.commit()


def list_correlations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM correlations ORDER BY window_start DESC")
    results = []
    for r in rows:
        d = dict(r)
        d["event_ids"] = json.loads(d["event_ids"])
        d["event_types"] = json.loads(d["event_types"])
        d["sources"] = json.loads(d["sources"])
        results.append(d)
    return results


def save_model(conn: sqlite3.Connection, record: ModelRecord) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO models
        (name, version, framework, task, classes, input_resolution, weights_source, license,
         hardware, num_parameters, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (record.name, record.version, record.framework, record.task, json.dumps(record.classes),
         record.input_resolution, record.weights_source, record.license, record.hardware,
         record.num_parameters, record.registered_at),
    )
    conn.commit()


def list_models(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM models ORDER BY registered_at DESC")
    results = []
    for r in rows:
        d = dict(r)
        d["classes"] = json.loads(d["classes"])
        results.append(d)
    return results


def create_pipeline_run(conn: sqlite3.Connection, run_id: str, source_id: str) -> None:
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, source_id, status, started_at, frames_processed) VALUES (?, ?, 'RUNNING', ?, 0)",
        (run_id, source_id, time.time()),
    )
    conn.commit()


def update_pipeline_run(conn: sqlite3.Connection, run_id: str, status: str, frames_processed: int,
                         error_message: str | None = None, ended: bool = False) -> None:
    conn.execute(
        "UPDATE pipeline_runs SET status = ?, frames_processed = ?, error_message = ?, ended_at = ? WHERE run_id = ?",
        (status, frames_processed, error_message, time.time() if ended else None, run_id),
    )
    conn.commit()


def get_pipeline_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_pipeline_runs(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC")]


def log_audit(conn: sqlite3.Connection, username: str | None, action: str, result: str,
              object_type: str | None = None, object_id: str | None = None, metadata: dict | None = None) -> None:
    """Records a system action. `metadata` must never contain secrets (passwords,
    tokens) — callers are responsible for that; this function does not scrub."""
    conn.execute(
        "INSERT INTO audit_log (timestamp, username, action, object_type, object_id, result, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (time.time(), username, action, object_type, object_id, result, json.dumps(metadata or {})),
    )
    conn.commit()


def list_audit_log(conn: sqlite3.Connection, limit: int = 200, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d["metadata"])
        results.append(d)
    return results


def get_asset_graph(conn: sqlite3.Connection, asset_id: str) -> dict | None:
    """Builds the linked graph for one asset directly from the database —
    every sensor stream, inspection, event, and anomaly actually associated
    with this asset_id, not the in-memory AssetRegistry (which is a separate,
    non-persistent demo path used by scripts/run_asset_graph_demo.py)."""
    asset = get_asset(conn, asset_id)
    if not asset:
        return None

    streams = [dict(r) for r in conn.execute(
        "SELECT * FROM sensor_streams WHERE asset_id = ?", (asset_id,))]
    inspections = list_inspections(conn, asset_id=asset_id)
    events = list_events_by_asset(conn, asset_id)

    anomalies = []
    for s in streams:
        anomalies.extend(list_anomalies(conn, s["stream_id"]))

    return {
        "asset": asset,
        "sensor_streams": streams,
        "inspections": inspections,
        "events": events,
        "anomalies": anomalies,
    }


def list_events_by_asset(conn: sqlite3.Connection, asset_id: str, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE asset_id = ? ORDER BY timestamp DESC LIMIT ?", (asset_id, limit)
    ).fetchall()
    return [_event_row_to_dict(r) for r in rows]
