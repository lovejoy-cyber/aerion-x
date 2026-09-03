"""The full set of true end-to-end tests (Phase 6 Part 27):
TEST A - real video through the full stack
TEST B - sensor -> anomaly -> correlation -> asset (-> report)
TEST C - inspection -> report
TEST D - pipeline failure recovery
TEST E - authentication / authorization
No mocking anywhere in any of these.
"""
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from backend import repositories
from core.assets.domain import Asset, AssetType
from core.contracts import Event
from core.correlation.correlation_engine import CorrelationEngine
from core.sensors.anomaly import ZScoreDetector
from core.sensors.synthetic_data import generate_vibration_stream


@pytest.fixture
def api_client():
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "e2e.sqlite3")

    import backend.db as db_module
    import backend.main as main_module

    main_module.DB_PATH = db_path
    main_module._conn = db_module.get_connection(db_path)
    db_module.init_db(main_module._conn)
    main_module.pipeline_manager.db_path = db_path

    with TestClient(main_module.app) as client:
        yield client, main_module._conn


def _bootstrap_admin(client):
    client.post("/auth/register", json={"username": "e2e_admin", "password": "correct horse battery staple"})
    login = client.post("/auth/login", json={"username": "e2e_admin", "password": "correct horse battery staple"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


def _wait_for_status(client, timeout=60.0):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get("/pipeline/status").json()
        if status["status"] in ("COMPLETED", "ERROR", "STOPPED"):
            break
        time.sleep(0.2)
    return status


# ---------- TEST A ----------

def test_real_video_through_full_stack_camera_to_api_retrieval(api_client):
    """REAL VIDEO -> YOLO -> POSE-CAPABLE TRACKER -> TEMPORAL -> ZONE ->
    SAFETY EVENT -> DATABASE -> API RETRIEVAL -> WEBSOCKET STREAM, using the
    actual vtest.avi file, actual YOLOv8n inference, actual SQLite writes.
    Capped at 12 frames to keep test runtime reasonable (~227ms/frame CPU)."""
    client, conn = api_client
    headers, token = _bootstrap_admin(client)
    video_path = "data/videos/vtest.avi"
    assert os.path.exists(video_path), "real test video must exist for this test to be meaningful"

    with client.websocket_connect(f"/ws/pipeline?token={token}") as ws:
        resp = client.post("/pipeline/start", json={
            "source_type": "video", "path": video_path, "max_frames": 12, "zone": True,
        }, headers=headers)
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        first_message = ws.receive_json()
        assert first_message["type"] in ("status", "event")

        status = _wait_for_status(client)

    assert status["status"] == "COMPLETED", status
    assert status["frames_processed"] == 12

    runs = client.get("/pipeline/runs").json()
    matching = [r for r in runs if r["run_id"] == run_id]
    assert matching and matching[0]["status"] == "COMPLETED"
    assert matching[0]["source_id"] == "video:vtest.avi"

    persisted_events = repositories.list_events(conn, limit=500)
    assert len(persisted_events) > 0, "no events were persisted from a real 12-frame video run"
    assert any(e["provenance"] == "REAL" for e in persisted_events)

    api_events = client.get("/events").json()
    assert api_events["total"] == len(persisted_events)
    assert len(api_events["items"]) == len(persisted_events)  # under the default limit=100


# ---------- TEST B ----------

def test_sensor_anomaly_correlation_asset_chain(api_client):
    """SENSOR DATA -> ANOMALY -> EVENT -> DATABASE -> CORRELATION -> ASSET -> REPORT,
    all real objects, real SQLite, real correlation engine, real PDF."""
    client, conn = api_client
    headers, _ = _bootstrap_admin(client)

    repositories.save_asset(conn, Asset(asset_id="AC1", asset_type=AssetType.AIRCRAFT, name="Test Aircraft"))

    stream, injected_indices = generate_vibration_stream()
    repositories.save_sensor_stream(conn, stream, asset_id="AC1")

    detector = ZScoreDetector(threshold=3.0)
    anomaly_results = detector.detect(stream)
    assert anomaly_results, "z-score detector found nothing on data with a known injected anomaly"
    repositories.save_anomaly_results(conn, stream.stream_id, anomaly_results)

    persisted_anomalies = repositories.list_anomalies(conn, stream.stream_id)
    injected_timestamps = {stream.readings[i].timestamp for i in injected_indices}
    assert injected_timestamps & {a["timestamp"] for a in persisted_anomalies}

    anomaly_event = Event(event_type="ANOMALY", timestamp=anomaly_results[0].timestamp,
                           source_id=stream.stream_id, asset_id="AC1", provenance="SYNTHETIC")
    vision_event = Event(event_type="ZONE_ENTER", timestamp=anomaly_results[0].timestamp + 0.5,
                          source_id="video:vtest.avi", asset_id="AC1", provenance="REAL")
    repositories.save_events(conn, [anomaly_event, vision_event])

    engine = CorrelationEngine(window_seconds=2.0)
    correlations = engine.correlate([anomaly_event, vision_event])
    assert len(correlations) == 1
    repositories.save_correlation(conn, correlations[0])

    persisted_correlations = repositories.list_correlations(conn)
    assert len(persisted_correlations) == 1
    assert set(persisted_correlations[0]["event_types"]) == {"ANOMALY", "ZONE_ENTER"}
    assert persisted_correlations[0]["provenance_note"] == "MIXED: REAL,SYNTHETIC"

    resp = client.get("/correlations")
    assert resp.status_code == 200

    report_resp = client.get("/reports/asset/AC1", headers=headers)
    assert report_resp.status_code == 200
    assert report_resp.content[:4] == b"%PDF"

    sensor_report_resp = client.get(f"/reports/sensor/{stream.stream_id}", headers=headers)
    assert sensor_report_resp.status_code == 200
    assert sensor_report_resp.content[:4] == b"%PDF"


# ---------- TEST C ----------

def test_inspection_full_chain_with_report(api_client):
    """REFERENCE + CURRENT FRAME -> ALIGNMENT -> SSIM -> DIFFERENCE -> REGIONS
    -> INSPECTION RECORD -> ASSET -> REPORT, using real vtest.avi frames
    through the real API, then a real PDF generated from that stored record."""
    client, conn = api_client
    headers, _ = _bootstrap_admin(client)

    client.post("/assets", json={"asset_id": "INSP_A1", "asset_type": "AIRCRAFT", "name": "Inspection Test Asset"},
                headers=headers)

    resp = client.post("/inspections/run", json={
        "asset_id": "INSP_A1", "video_path": "data/videos/vtest.avi", "reference_frame": 0, "current_frame": 50,
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert 0.0 <= data["change_score"] <= 1.0
    assert -1.0 <= data["mean_ssim"] <= 1.0
    assert all(r["label"] == "VISUAL ANOMALY REGION" for r in data["anomaly_regions"])

    history = client.get("/inspections?asset_id=INSP_A1").json()
    assert any(i["inspection_id"] == data["inspection_id"] for i in history)

    report_resp = client.get(f"/reports/inspection/{data['inspection_id']}", headers=headers)
    assert report_resp.status_code == 200
    assert report_resp.content[:4] == b"%PDF"


# ---------- TEST D ----------

def test_pipeline_failure_recovery(api_client):
    """Start a pipeline against a video path that doesn't exist -> verify it
    fails cleanly (ERROR status, error_message set, no orphaned thread) ->
    verify a subsequent legitimate pipeline run still works normally."""
    client, conn = api_client
    headers, _ = _bootstrap_admin(client)

    resp = client.post("/pipeline/start", json={
        "source_type": "video", "path": "data/videos/does_not_exist.avi", "max_frames": 5,
    }, headers=headers)
    assert resp.status_code == 200  # path exists check happens inside the source, not at request validation

    status = _wait_for_status(client)
    assert status["status"] == "ERROR"
    assert status["error_message"]

    # the manager must not be stuck "RUNNING" — a fresh start must succeed
    resp2 = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 5}, headers=headers)
    assert resp2.status_code == 200
    status2 = _wait_for_status(client)
    assert status2["status"] == "COMPLETED"


# ---------- TEST E ----------

def test_authentication_and_role_restriction(api_client):
    """Unauthorized request -> rejected. Authorized request -> accepted.
    Role restriction -> an OPERATOR is rejected from an ENGINEER-gated action,
    an ENGINEER-or-above (here, the bootstrap ADMIN) succeeds at it."""
    client, conn = api_client

    unauthorized = client.post("/assets", json={"asset_id": "X1", "asset_type": "AIRCRAFT", "name": "X"})
    assert unauthorized.status_code == 401

    admin_headers, _ = _bootstrap_admin(client)
    authorized = client.post("/assets", json={"asset_id": "X1", "asset_type": "AIRCRAFT", "name": "X"}, headers=admin_headers)
    assert authorized.status_code == 200

    client.post("/auth/register", json={"username": "plain_operator", "password": "password1234"})
    op_login = client.post("/auth/login", json={"username": "plain_operator", "password": "password1234"})
    op_headers = {"Authorization": f"Bearer {op_login.json()['access_token']}"}

    operator_denied = client.post("/assets", json={"asset_id": "X2", "asset_type": "AIRCRAFT", "name": "X2"}, headers=op_headers)
    assert operator_denied.status_code == 403

    denied_audit = [a for a in repositories.list_audit_log(conn) if a["action"] == "AUTHORIZATION_CHECK" and a["result"] == "DENIED"]
    assert denied_audit
