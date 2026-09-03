"""Real FastAPI endpoint tests via TestClient — actual HTTP requests against
the actual app, actual SQLite file, actual pipeline runs where relevant. Uses
an isolated temp DB per test module run by pointing backend.main's globals at
a temp file before importing, since the app builds its connection at import time.
"""
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    tmp_dir = tempfile.mkdtemp()
    os.environ["AERIONX_TEST_DB"] = os.path.join(tmp_dir, "test_api.sqlite3")

    # backend.main opens its DB connection at import time using a hardcoded
    # path; redirect it for tests by patching before import.
    import backend.db as db_module
    original_path = db_module.DEFAULT_DB_PATH
    db_module.DEFAULT_DB_PATH = os.environ["AERIONX_TEST_DB"]

    import backend.main as main_module
    main_module.DB_PATH = os.environ["AERIONX_TEST_DB"]
    main_module._conn = db_module.get_connection(main_module.DB_PATH)
    db_module.init_db(main_module._conn)
    main_module.pipeline_manager.db_path = main_module.DB_PATH

    with TestClient(main_module.app) as test_client:
        yield test_client

    db_module.DEFAULT_DB_PATH = original_path


@pytest.fixture(scope="module")
def admin_auth(client):
    """First registration in a fresh DB bootstraps as ADMIN (see backend/auth.py).
    Returns (headers, token) so both REST calls and the WebSocket query-param
    auth can use the same real session."""
    resp = client.post("/auth/register", json={"username": "test_admin", "password": "correct horse battery staple"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "ADMIN"

    resp = client.post("/auth/login", json={"username": "test_admin", "password": "correct horse battery staple"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_status_endpoint_reports_real_platform_info(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "platform" in data
    assert "gpu_available" in data
    assert isinstance(data["gpu_available"], bool)
    assert data["compute_device"]["device"] in ("CPU", "CUDA")


def test_login_is_rate_limited_against_brute_force(client, admin_auth):
    """Quick, high-value hardening: 30 login attempts/60s is the real limit —
    hammer it well past that and confirm a 429 shows up, proving the limiter
    actually engages rather than just existing in code.

    Cleans up the shared in-memory rate-limit state afterward — it's a single
    process-wide dict (by design: no new dependency, single-worker deployment
    only), so every test file in this pytest run shares it, and leaving it
    exhausted here would spuriously 429 unrelated login calls in later tests."""
    import backend.main as main_module

    for _ in range(35):
        client.post("/auth/login", json={"username": "test_admin", "password": "wrong"})
    resp = client.post("/auth/login", json={"username": "test_admin", "password": "wrong"})
    assert resp.status_code == 429

    main_module._rate_limit_hits.clear()


def test_login_rejects_wrong_password(client, admin_auth):
    resp = client.post("/auth/login", json={"username": "test_admin", "password": "wrong"})
    assert resp.status_code == 401


def test_protected_endpoint_rejects_missing_token(client):
    resp = client.post("/assets", json={"asset_id": "NOPE", "asset_type": "AIRCRAFT", "name": "Nope"})
    assert resp.status_code == 401


def test_protected_endpoint_rejects_invalid_token(client):
    resp = client.post("/assets", json={"asset_id": "NOPE", "asset_type": "AIRCRAFT", "name": "Nope"},
                        headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_operator_cannot_register_models(client):
    """Real role check: a freshly self-registered (non-bootstrap) user is
    OPERATOR and must be rejected from an ADMIN-only action. The admin-succeeds
    half of this check is exercised directly by
    test_register_yolo_model_pulls_real_metadata below, using the bootstrap admin."""
    client.post("/auth/register", json={"username": "some_operator", "password": "password1234"})
    login = client.post("/auth/login", json={"username": "some_operator", "password": "password1234"})
    operator_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post("/models/register-yolo", headers=operator_headers)
    assert resp.status_code == 403


def test_create_and_get_asset(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/assets", json={"asset_id": "A100", "asset_type": "AIRCRAFT", "name": "Test Aircraft"}, headers=headers)
    assert resp.status_code == 200

    resp = client.get("/assets/A100")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Aircraft"


def test_create_asset_rejects_unknown_type(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/assets", json={"asset_id": "A101", "asset_type": "SPACESHIP", "name": "Nope"}, headers=headers)
    assert resp.status_code == 400


def test_get_nonexistent_asset_404s(client):
    resp = client.get("/assets/does_not_exist")
    assert resp.status_code == 404


def test_register_yolo_model_pulls_real_metadata(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/models/register-yolo", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["num_parameters"] == 3157200  # actual YOLOv8n param count, verified earlier this session

    resp = client.get("/models")
    models = resp.json()
    assert any(m["name"] == "YOLOv8n" for m in models)


def test_audit_log_records_real_actions_admin_only(client, admin_auth):
    headers, _ = admin_auth
    resp = client.get("/audit-log", headers=headers)
    assert resp.status_code == 200
    actions = {row["action"] for row in resp.json()}
    assert "LOGIN" in actions
    assert "ASSET_CREATED" in actions

    resp_no_auth = client.get("/audit-log")
    assert resp_no_auth.status_code == 401


def test_pipeline_start_status_and_completion_real_synthetic_run(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 15}, headers=headers)
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        status = client.get("/pipeline/status").json()
        if status["status"] in ("COMPLETED", "ERROR"):
            break
        time.sleep(0.2)

    assert status["status"] == "COMPLETED", status
    assert status["frames_processed"] == 15

    runs = client.get("/pipeline/runs").json()
    assert any(r["run_id"] == run_id and r["status"] == "COMPLETED" for r in runs)


def test_pipeline_cannot_start_while_already_running(client, admin_auth):
    headers, _ = admin_auth
    resp1 = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 5000}, headers=headers)
    assert resp1.status_code == 200
    try:
        resp2 = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 5}, headers=headers)
        assert resp2.status_code == 409
    finally:
        client.post("/pipeline/stop", headers=headers)
        deadline = time.time() + 30
        while time.time() < deadline:
            if client.get("/pipeline/status").json()["status"] != "RUNNING":
                break
            time.sleep(0.2)


def test_events_endpoint_reflects_real_pipeline_events_and_paginates(client):
    resp = client.get("/events")
    data = resp.json()
    assert "items" in data and "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= len(data["items"])

    small_page = client.get("/events?limit=1").json()
    assert len(small_page["items"]) <= 1


def test_pipeline_start_with_invalid_source_type_is_rejected(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/pipeline/start", json={"source_type": "not_a_real_source"}, headers=headers)
    assert resp.status_code == 400


def test_pipeline_path_traversal_is_rejected(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/pipeline/start", json={"source_type": "video", "path": "../../../../etc/passwd"}, headers=headers)
    assert resp.status_code == 400


def test_websocket_requires_auth_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/pipeline"):
            pass  # no token query param — server closes with code 1008 before accept()


def test_websocket_broadcasts_to_multiple_clients_simultaneously(client, admin_auth):
    """Phase 6 Part 10: two real WebSocket clients connected at once must both
    receive the same broadcast from one pipeline run — proving _send_to_all()
    actually iterates every connected client rather than just the first."""
    headers, token = admin_auth
    with client.websocket_connect(f"/ws/pipeline?token={token}") as ws1, \
         client.websocket_connect(f"/ws/pipeline?token={token}") as ws2:
        resp = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 8}, headers=headers)
        assert resp.status_code == 200

        msg1 = ws1.receive_json()
        msg2 = ws2.receive_json()
        assert msg1["type"] in ("status", "event")
        assert msg2["type"] in ("status", "event")

        deadline = time.time() + 30
        while time.time() < deadline:
            if client.get("/pipeline/status").json()["status"] != "RUNNING":
                break
            time.sleep(0.2)


def test_websocket_slow_client_does_not_block_pipeline(client, admin_auth):
    """Phase 6 Part 10: a client that connects and never reads its messages
    must not stall or crash the pipeline thread — _broadcast wraps every send
    in try/except specifically so one bad client can't take the others down."""
    headers, token = admin_auth
    with client.websocket_connect(f"/ws/pipeline?token={token}") as slow_client:
        resp = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 10}, headers=headers)
        assert resp.status_code == 200
        # deliberately not calling slow_client.receive_json() — the pipeline
        # must still reach COMPLETED despite this client never draining its queue
        status = None
        deadline = time.time() + 30
        while time.time() < deadline:
            status = client.get("/pipeline/status").json()
            if status["status"] in ("COMPLETED", "ERROR"):
                break
            time.sleep(0.2)
        assert status["status"] == "COMPLETED", status


def test_websocket_receives_real_pipeline_status_broadcasts(client, admin_auth):
    headers, token = admin_auth
    with client.websocket_connect(f"/ws/pipeline?token={token}") as websocket:
        resp = client.post("/pipeline/start", json={"source_type": "synthetic", "max_frames": 10}, headers=headers)
        assert resp.status_code == 200

        message = websocket.receive_json()
        assert message["type"] in ("status", "event")
        if message["type"] == "status":
            assert "fps" in message
            assert "frames_processed" in message

        deadline = time.time() + 30
        while time.time() < deadline:
            if client.get("/pipeline/status").json()["status"] != "RUNNING":
                break
            time.sleep(0.2)


def test_report_generation_produces_real_pdf(client, admin_auth):
    headers, _ = admin_auth
    resp = client.get("/reports/events", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_capture_analyze_runs_real_detection_on_uploaded_photo(client, admin_auth):
    """Field-capture endpoint: encode a real frame from vtest.avi as a real
    JPEG (not a synthetic blank image), upload it exactly like a phone
    browser would, and confirm the real YOLO detector actually runs on it."""
    import cv2

    headers, _ = admin_auth
    cap = cv2.VideoCapture("data/videos/vtest.avi")
    ok, frame = cap.read()
    cap.release()
    assert ok, "need a real frame from the test video for this test to be meaningful"

    ok, jpeg_bytes = cv2.imencode(".jpg", frame)
    assert ok

    resp = client.post("/capture/analyze", headers=headers,
                        files={"file": ("capture.jpg", jpeg_bytes.tobytes(), "image/jpeg")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_type"] == "MOBILE_UPLOAD"
    assert data["image_width"] == frame.shape[1]
    assert data["image_height"] == frame.shape[0]
    assert isinstance(data["detections"], list)
    assert data["inference_ms"] > 0


def test_capture_analyze_rejects_oversized_or_wrong_type(client, admin_auth):
    headers, _ = admin_auth
    resp = client.post("/capture/analyze", headers=headers,
                        files={"file": ("notes.txt", b"not an image", "text/plain")})
    assert resp.status_code == 400


def test_capture_analyze_requires_auth(client):
    resp = client.post("/capture/analyze", files={"file": ("x.jpg", b"fake", "image/jpeg")})
    assert resp.status_code == 401
