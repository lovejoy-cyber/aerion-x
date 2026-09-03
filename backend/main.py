"""AERION-X backend API. Every endpoint here calls a real service/repository
function — none return hardcoded JSON. Run with:
    uvicorn backend.main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import auth, repositories
from backend.auth import Role, User
from backend.db import get_connection, init_db
from backend.services import PipelineManager
from core.assets.domain import Asset, AssetType
from core.config import settings
from core.correlation.correlation_engine import CorrelationEngine
from core.contracts import Event
from core.cv.detector import YoloDetector
from core.inspection.pipeline import generate_inspection_report
from core.model_lab.registry import build_yolo_detector_record
from core.vision.optical_flow import FarnebackFlowEstimator

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="AERION-X API", version="0.1.0", lifespan=_lifespan)

# ---------- optional site-wide gate ----------
# A single shared passphrase in front of EVERYTHING (including the GET
# endpoints that are otherwise open — see SECURITY.md). Separate from the
# real per-user login system: this is for "don't let random internet
# strangers in at all" when sharing a public link with non-technical people
# who just need "the password," not an account. Disabled entirely (zero
# behavior change) unless AERIONX_SITE_PASSPHRASE is set.
_SITE_PASSPHRASE = os.environ.get("AERIONX_SITE_PASSPHRASE", "")
_GATE_COOKIE = "aerionx_gate"

_GATE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AERION-X</title>
<style>
body{background:#0b0e13;color:#e6ebf2;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
.box{width:300px;background:#12161d;border:1px solid #232a35;border-radius:8px;padding:28px;text-align:center}
input{width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #232a35;color:#e6ebf2;
padding:9px;border-radius:4px;margin:14px 0;font-size:14px}
button{width:100%;background:#2c7a72;color:#d5fff9;border:1px solid #4fd1c5;padding:9px;
border-radius:4px;cursor:pointer;font-size:13px}
.err{color:#e0522d;font-size:12px;min-height:14px}
</style></head><body>
<div class="box">
<h2 style="margin-top:0">AERION-X</h2>
<p style="color:#7c8697;font-size:13px">Enter the access passphrase to continue.</p>
<form id="f"><input id="p" type="password" placeholder="Passphrase" autofocus>
<button type="submit">ENTER</button><div class="err" id="e"></div></form>
</div>
<script>
document.getElementById('f').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const r = await fetch('/gate', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({passphrase: document.getElementById('p').value})});
  if (r.ok) { location.reload(); } else { document.getElementById('e').textContent = 'Wrong passphrase.'; }
});
</script></body></html>"""


def _gate_ok(request: Request) -> bool:
    if not _SITE_PASSPHRASE:
        return True  # gate disabled
    import hmac
    cookie = request.cookies.get(_GATE_COOKIE, "")
    return hmac.compare_digest(cookie, _SITE_PASSPHRASE)


@app.middleware("http")
async def _site_gate(request: Request, call_next):
    from starlette.responses import HTMLResponse, JSONResponse

    if not _SITE_PASSPHRASE or request.url.path in ("/health", "/gate"):
        return await call_next(request)
    if not _gate_ok(request):
        if request.url.path == "/" or request.url.path.endswith(".html"):
            return HTMLResponse(_GATE_HTML)
        return JSONResponse(status_code=403, content={"detail": "Site passphrase required"})
    return await call_next(request)


@app.post("/gate")
async def check_gate(request: Request):
    from starlette.responses import JSONResponse
    body = await request.json()
    import hmac
    if _SITE_PASSPHRASE and hmac.compare_digest(body.get("passphrase", ""), _SITE_PASSPHRASE):
        resp = JSONResponse({"ok": True})
        resp.set_cookie(_GATE_COOKIE, _SITE_PASSPHRASE, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
        return resp
    return JSONResponse(status_code=403, content={"detail": "Wrong passphrase"})

# Quick, high-value hardening pass — deliberately NOT a full security overhaul
# (that's real, scoped-out follow-up work, see SECURITY.md/LIMITATIONS.md).
# Just the two fixes that matter most in minutes: CORS wasn't scoped to
# anything, and login/register had zero brute-force protection.
_cors_origins = os.environ.get("AERIONX_CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,  # set AERIONX_CORS_ORIGINS for other deployments
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("aerionx.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


# Simple in-memory sliding-window rate limit — no new dependency, resets on
# restart, single-process only (fine for this tool's actual deployment shape;
# a real multi-worker deployment would need a shared store like Redis instead).
_rate_limit_hits: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()


def rate_limit(max_requests: int, window_seconds: float):
    def _check(request: Request):
        key = f"{request.url.path}:{request.client.host if request.client else 'unknown'}"
        now = time.time()
        with _rate_limit_lock:
            hits = _rate_limit_hits[key] = [t for t in _rate_limit_hits[key] if now - t < window_seconds]
            if len(hits) >= max_requests:
                raise HTTPException(status_code=429, detail="Too many requests — try again shortly")
            hits.append(now)
    return _check


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc: Exception):
    """Never leak a stack trace or internal error text to a client — log the
    real detail server-side, return a generic message client-side."""
    from fastapi.responses import JSONResponse
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

DB_PATH = "data/db/aerionx.sqlite3"
_conn = get_connection(DB_PATH)
init_db(_conn)

pipeline_manager = PipelineManager(db_path=DB_PATH)

# WebSocket broadcast: pipeline events/status pushed to every connected client.
# The pipeline runs on a plain threading.Thread (not an anyio worker thread), so
# reaching back into the async event loop from it requires capturing the loop
# explicitly and using asyncio.run_coroutine_threadsafe — anyio.from_thread.run
# only works from threads anyio itself spawned, which this isn't.
_ws_clients: list[WebSocket] = []
_event_loop: Optional[asyncio.AbstractEventLoop] = None


async def _send_to_all(message: dict) -> None:
    for ws in list(_ws_clients):
        try:
            await ws.send_json(message)
        except Exception:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


def _broadcast_to_websockets(message: dict) -> None:
    """Called from the pipeline's background thread. Schedules the actual send
    onto the FastAPI event loop rather than trying to await anything here."""
    if _event_loop is None or not _ws_clients:
        return
    asyncio.run_coroutine_threadsafe(_send_to_all(message), _event_loop)


pipeline_manager.on_broadcast(_broadcast_to_websockets)


# ---------- authentication ----------
# Scoping decision (documented, not silent — see SECURITY.md): GET endpoints
# stay unauthenticated (read-only monitoring), every POST/state-changing
# endpoint requires a valid bearer token, and a handful require a specific
# role. This keeps the change bounded rather than rewiring every existing
# read-path test, while still gating every action that actually mutates state.

def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")
    user = auth.decode_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_role(role: Role):
    def _check(user: User = Depends(get_current_user)) -> User:
        if not auth.role_at_least(user.role, role):
            repositories.log_audit(_conn, user.username, "AUTHORIZATION_CHECK", "DENIED",
                                    metadata={"required_role": role.value, "actual_role": user.role.value})
            raise HTTPException(status_code=403, detail=f"Requires role {role.value} or higher")
        return user
    return _check


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/register", dependencies=[Depends(rate_limit(20, 60))])
def register(req: RegisterRequest):
    """First registered user becomes ADMIN (bootstrap); everyone after that
    self-registers as OPERATOR — an ADMIN can be created for someone else only
    by an existing ADMIN via a direct DB/script action, not through this
    open endpoint, to avoid unauthenticated privilege escalation."""
    existing_users = _conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
    role = Role.ADMIN if existing_users == 0 else Role.OPERATOR
    try:
        user = auth.create_user(_conn, req.username, req.password, role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    repositories.log_audit(_conn, user.username, "USER_REGISTERED", "SUCCESS",
                            object_type="user", object_id=user.user_id, metadata={"role": role.value})
    return {"user_id": user.user_id, "username": user.username, "role": user.role.value}


@app.post("/auth/login", dependencies=[Depends(rate_limit(30, 60))])
def login(req: LoginRequest):
    user = auth.authenticate(_conn, req.username, req.password)
    if not user:
        repositories.log_audit(_conn, req.username, "LOGIN", "DENIED")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    repositories.log_audit(_conn, user.username, "LOGIN", "SUCCESS")
    return {"access_token": auth.issue_token(user), "token_type": "bearer", "role": user.role.value}


@app.get("/auth/me")
def whoami(user: User = Depends(get_current_user)):
    return {"user_id": user.user_id, "username": user.username, "role": user.role.value}


@app.post("/admin/backup")
def create_backup(user: User = Depends(require_role(Role.ADMIN))):
    from backend import backup as backup_module
    path = backup_module.create_backup(_conn)
    repositories.log_audit(_conn, user.username, "BACKUP_CREATED", "SUCCESS", object_id=path)
    return {"backup_path": path}


@app.get("/admin/backups")
def list_backups(user: User = Depends(require_role(Role.ADMIN))):
    from backend import backup as backup_module
    return backup_module.list_backups()


@app.get("/audit-log")
def get_audit_log(limit: int = 200, offset: int = 0, user: User = Depends(require_role(Role.ADMIN))):
    return repositories.list_audit_log(_conn, limit=limit, offset=offset)


# ---------- health / status ----------

@app.get("/health")
def health():
    return {"status": "ok", "time": time.time()}


DATA_ROOT = Path("data").resolve()


def safe_data_path(user_path: str) -> str:
    """Resolves a user-supplied path and rejects anything that escapes
    data/ — without this, /inspections/run and /flow/demo would happily
    cv2.VideoCapture() any path on disk the server process can read,
    including e.g. ../../../../Users/<name>/AppData/... — a real path
    traversal gap, not a hypothetical one."""
    resolved = (Path.cwd() / user_path).resolve()
    try:
        resolved.relative_to(DATA_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path must be within the data/ directory")
    return str(resolved)


def get_compute_device() -> dict:
    """Real hardware detection — never asserts GPU performance without having
    measured it (see LIMITATIONS.md: all FPS/latency numbers in this project
    were measured CPU-only, since no CUDA GPU exists on the dev machine)."""
    try:
        import torch
        if torch.cuda.is_available():
            return {"device": "CUDA", "name": torch.cuda.get_device_name(0), "measured": False,
                     "note": "CUDA detected but no benchmark has been run on it in this project"}
    except ImportError:
        pass
    return {"device": "CPU", "name": platform.processor() or "unknown", "measured": True,
             "note": "all performance numbers in this project were measured on this CPU path"}


@app.get("/status")
def system_status():
    compute = get_compute_device()
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "gpu_available": compute["device"] == "CUDA",
        "compute_device": compute,
        "pipeline_status": pipeline_manager.status.status,
        "pipeline_frames_processed": pipeline_manager.status.frames_processed,
        "pipeline_fps": pipeline_manager.status.fps,
    }


# ---------- models ----------

@app.get("/models")
def list_models():
    return repositories.list_models(_conn)


@app.post("/models/register-yolo")
def register_yolo_model(user: User = Depends(require_role(Role.ADMIN))):
    """Loads the real YOLOv8n model and registers its actual metadata (class
    list, parameter count) — not a hardcoded record. ADMIN-only: changing
    which model is registered/trusted is a system-configuration action."""
    detector = YoloDetector()
    record = build_yolo_detector_record(detector)
    repositories.save_model(_conn, record)
    repositories.log_audit(_conn, user.username, "MODEL_REGISTERED", "SUCCESS",
                            object_type="model", object_id=f"{record.name}:{record.version}")
    return {"registered": f"{record.name}:{record.version}", "num_parameters": record.num_parameters}


# ---------- pipeline ----------

class PipelineStartRequest(BaseModel):
    source_type: str  # "video" | "synthetic"
    path: Optional[str] = None
    max_frames: Optional[int] = None
    zone: bool = False


@app.post("/pipeline/start")
def start_pipeline(req: PipelineStartRequest, user: User = Depends(get_current_user)):
    safe_path = safe_data_path(req.path) if req.path else None
    try:
        run_id = pipeline_manager.start(req.source_type, safe_path, req.max_frames, req.zone)
    except RuntimeError as e:
        repositories.log_audit(_conn, user.username, "PIPELINE_START", "DENIED", metadata={"reason": str(e)})
        raise HTTPException(status_code=409, detail=str(e))
    except (ValueError, FileNotFoundError) as e:
        repositories.log_audit(_conn, user.username, "PIPELINE_START", "ERROR", metadata={"reason": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    repositories.log_audit(_conn, user.username, "PIPELINE_START", "SUCCESS", object_type="pipeline_run", object_id=run_id,
                            metadata={"source_type": req.source_type})
    return {"run_id": run_id, "status": pipeline_manager.status.status}


@app.post("/pipeline/stop")
def stop_pipeline(user: User = Depends(get_current_user)):
    pipeline_manager.stop()
    repositories.log_audit(_conn, user.username, "PIPELINE_STOP", "SUCCESS", object_type="pipeline_run",
                            object_id=pipeline_manager.status.run_id)
    return {"status": "stopping"}


@app.get("/pipeline/status")
def pipeline_status():
    s = pipeline_manager.status
    return {
        "run_id": s.run_id, "status": s.status, "source_id": s.source_id,
        "frames_processed": s.frames_processed, "fps": s.fps,
        "last_inference_ms": s.last_inference_ms, "active_tracks": s.active_tracks,
        "error_message": s.error_message,
    }


@app.get("/pipeline/runs")
def pipeline_runs():
    return repositories.list_pipeline_runs(_conn)


# ---------- events ----------

@app.get("/events")
def list_events(event_type: Optional[str] = None, severity: Optional[str] = None,
                 limit: int = 100, offset: int = 0):
    return {
        "items": repositories.list_events(_conn, event_type=event_type, severity=severity, limit=limit, offset=offset),
        "total": repositories.count_events(_conn, event_type=event_type, severity=severity),
        "limit": limit, "offset": offset,
    }


@app.post("/correlations/compute")
def compute_correlations(window_seconds: float = 2.0, limit: int = 500, user: User = Depends(get_current_user)):
    """Pulls recent persisted events and runs the real correlation engine
    against them, persisting any correlations found."""
    rows = repositories.list_events(_conn, limit=limit)
    events = [
        Event(event_type=r["event_type"], timestamp=r["timestamp"], source_id=r["source_id"],
              track_ids=r["track_ids"], event_id=r["event_id"], zone_id=r["zone_id"],
              provenance=r["provenance"])
        for r in rows
    ]
    engine = CorrelationEngine(window_seconds=window_seconds)
    correlations = engine.correlate(events)
    for c in correlations:
        repositories.save_correlation(_conn, c)
    return {"correlations_found": len(correlations)}


@app.get("/correlations")
def list_correlations():
    return repositories.list_correlations(_conn)


# ---------- assets ----------

class AssetCreateRequest(BaseModel):
    asset_id: str
    asset_type: str
    name: str


@app.post("/assets")
def create_asset(req: AssetCreateRequest, user: User = Depends(require_role(Role.ENGINEER))):
    try:
        asset_type = AssetType(req.asset_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown asset_type: {req.asset_type}")
    asset = Asset(asset_id=req.asset_id, asset_type=asset_type, name=req.name)
    repositories.save_asset(_conn, asset)
    repositories.log_audit(_conn, user.username, "ASSET_CREATED", "SUCCESS", object_type="asset", object_id=asset.asset_id)
    return {"asset_id": asset.asset_id}


@app.get("/assets")
def list_assets():
    return repositories.list_assets(_conn)


@app.get("/assets/{asset_id}")
def get_asset(asset_id: str):
    asset = repositories.get_asset(_conn, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@app.get("/assets/{asset_id}/graph")
def get_asset_graph(asset_id: str):
    graph = repositories.get_asset_graph(_conn, asset_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return graph


# ---------- inspections ----------

@app.get("/inspections")
def list_inspections(asset_id: Optional[str] = None):
    return repositories.list_inspections(_conn, asset_id=asset_id)


class InspectionRunRequest(BaseModel):
    asset_id: str
    video_path: str = "data/videos/vtest.avi"
    reference_frame: int = 0
    current_frame: int = 50


@app.post("/inspections/run")
def run_inspection(req: InspectionRunRequest, user: User = Depends(require_role(Role.ENGINEER))):
    """Runs the real inspection pipeline (CLAHE, ORB registration, change
    detection, SSIM, contour scoring) against two actual frames pulled from a
    real video file, and persists the result. This is generic visual change
    detection — the response never claims a confirmed defect."""
    import uuid as uuid_module

    import cv2

    if not repositories.get_asset(_conn, req.asset_id):
        raise HTTPException(status_code=404, detail="Asset not found — create it first via POST /assets")

    video_path = safe_data_path(req.video_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail=f"Could not open video: {req.video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, req.reference_frame)
    ok_a, img_a = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, req.current_frame)
    ok_b, img_b = cap.read()
    cap.release()
    if not (ok_a and ok_b):
        raise HTTPException(status_code=400, detail="Could not read the requested frames from the video")

    inspection_id = f"insp_{uuid_module.uuid4().hex[:8]}"
    report = generate_inspection_report(inspection_id, req.asset_id, time.time(), img_a, img_b)
    repositories.save_inspection(_conn, report)
    repositories.log_audit(_conn, user.username, "INSPECTION_RUN", "SUCCESS",
                            object_type="inspection", object_id=inspection_id, metadata={"asset_id": req.asset_id})

    return {
        "inspection_id": report.inspection_id,
        "asset_id": report.asset_id,
        "change_score": report.change_score,
        "mean_ssim": report.mean_ssim,
        "anomaly_regions": report.anomaly_regions,
        "notes": report.notes,
    }


# ---------- optical flow ----------

class FlowDemoRequest(BaseModel):
    video_path: str = "data/videos/vtest.avi"
    frame_a: int = 100
    frame_b: int = 101


@app.post("/flow/demo")
def run_flow_demo(req: FlowDemoRequest, user: User = Depends(get_current_user)):
    """Real Farneback optical flow between two actual video frames. Named
    'demo' because it computes flow on demand for the GUI rather than running
    continuously — the algorithm itself is the same one used in the tested
    core.vision.optical_flow module, not a separate implementation."""
    import cv2

    from core.contracts import Frame, SourceType

    video_path = safe_data_path(req.video_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail=f"Could not open video: {req.video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, req.frame_a)
    ok_a, img_a = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, req.frame_b)
    ok_b, img_b = cap.read()
    cap.release()
    if not (ok_a and ok_b):
        raise HTTPException(status_code=400, detail="Could not read the requested frames")

    fa = Frame(frame_id=req.frame_a, timestamp=0.0, source_id="video", source_type=SourceType.VIDEO_FILE,
               image=img_a, width=img_a.shape[1], height=img_a.shape[0])
    fb = Frame(frame_id=req.frame_b, timestamp=0.0, source_id="video", source_type=SourceType.VIDEO_FILE,
               image=img_b, width=img_b.shape[1], height=img_b.shape[0])
    result = FarnebackFlowEstimator().compute(fa, fb)
    return {
        "magnitude_mean": result.magnitude_mean,
        "magnitude_max": result.magnitude_max,
        "direction_mean_deg": result.direction_mean_deg,
        "method": result.method,
        "frame_id_a": result.frame_id_a,
        "frame_id_b": result.frame_id_b,
    }


# ---------- mobile/field capture ----------
# The genuinely-doable half of "mobile support": a phone's own browser can
# already hit this over the same network via getUserMedia + fetch — no native
# app needed. See MOBILE_ARCHITECTURE.md for what's still NOT built (this
# closes exactly the "upload an image" gap that doc called out).

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB — a phone photo is typically 1-5MB
ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}


@app.post("/capture/analyze")
async def analyze_capture(file: UploadFile, user: User = Depends(get_current_user)):
    """Real YOLO detection on an uploaded image — the same detector used by
    the video pipeline, just fed a single decoded frame instead of a video
    stream. No tracking (a single photo has no motion history), no fake
    confidence numbers — whatever the model actually outputs."""
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content type: {file.content_type}")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)")

    import cv2
    import numpy as np

    from core.contracts import Frame, SourceType

    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode image — not a valid JPEG/PNG/WebP")

    frame = Frame(frame_id=0, timestamp=time.time(), source_id=f"mobile:{user.username}",
                  source_type=SourceType.MOBILE_UPLOAD, image=image, width=image.shape[1], height=image.shape[0])
    detector = YoloDetector(confidence_threshold=settings.detector_confidence_threshold)
    detections = detector.detect(frame)

    repositories.log_audit(_conn, user.username, "MOBILE_CAPTURE_ANALYZED", "SUCCESS",
                            metadata={"num_detections": len(detections), "file_size_bytes": len(raw)})

    return {
        "source_type": "MOBILE_UPLOAD",
        "image_width": image.shape[1],
        "image_height": image.shape[0],
        "inference_ms": detector.last_inference_ms,
        "detections": [
            {"class_name": d.class_name, "confidence": d.confidence, "bbox": d.bbox}
            for d in detections
        ],
    }


# ---------- sensors ----------

@app.get("/sensors/streams")
def list_sensor_streams():
    return repositories.list_sensor_streams(_conn)


@app.get("/sensors/streams/{stream_id}/readings")
def get_sensor_readings(stream_id: str):
    return repositories.get_sensor_readings(_conn, stream_id)


@app.get("/sensors/anomalies")
def list_anomalies(stream_id: Optional[str] = None):
    return repositories.list_anomalies(_conn, stream_id=stream_id)


class SyntheticSensorRequest(BaseModel):
    asset_id: Optional[str] = None
    seed: int = 7


@app.post("/sensors/generate-synthetic")
def generate_synthetic_sensor(req: SyntheticSensorRequest, user: User = Depends(require_role(Role.ENGINEER))):
    """Generates a real deterministic synthetic vibration stream with a known
    injected anomaly, runs the real z-score detector against it, and persists
    both — always labeled SYNTHETIC, never presented as real sensor evidence.
    This exists so the Sensor workspace has real (if synthetic) data to show
    through the actual API rather than requiring a separate CLI script."""
    from core.sensors.anomaly import ZScoreDetector
    from core.sensors.synthetic_data import generate_vibration_stream

    stream, injected_indices = generate_vibration_stream(seed=req.seed)
    repositories.save_sensor_stream(_conn, stream, asset_id=req.asset_id)

    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    repositories.save_anomaly_results(_conn, stream.stream_id, results)

    return {
        "stream_id": stream.stream_id,
        "provenance": stream.provenance.value,
        "num_readings": len(stream.readings),
        "num_anomalies_detected": len(results),
        "injected_anomaly_window": [stream.readings[i].timestamp for i in
                                     (injected_indices[0], injected_indices[-1])],
    }


# ---------- reports ----------

from fastapi.responses import FileResponse

from backend import reports as reports_module


@app.get("/reports/inspection/{inspection_id}")
def report_inspection(inspection_id: str, user: User = Depends(get_current_user)):
    matches = [i for i in repositories.list_inspections(_conn) if i["inspection_id"] == inspection_id]
    if not matches:
        raise HTTPException(status_code=404, detail="Inspection not found")
    inspection = matches[0]
    asset = repositories.get_asset(_conn, inspection["asset_id"])
    path = reports_module.generate_inspection_report_pdf(inspection, asset)
    repositories.log_audit(_conn, user.username, "REPORT_GENERATED", "SUCCESS",
                            object_type="inspection_report", object_id=inspection_id)
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


@app.get("/reports/events")
def report_events(event_type: Optional[str] = None, limit: int = 200, user: User = Depends(get_current_user)):
    events = repositories.list_events(_conn, event_type=event_type, limit=limit)
    path = reports_module.generate_event_report_pdf(events)
    repositories.log_audit(_conn, user.username, "REPORT_GENERATED", "SUCCESS", object_type="event_report")
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


@app.get("/reports/sensor/{stream_id}")
def report_sensor(stream_id: str, user: User = Depends(get_current_user)):
    streams = [s for s in repositories.list_sensor_streams(_conn) if s["stream_id"] == stream_id]
    if not streams:
        raise HTTPException(status_code=404, detail="Stream not found")
    readings = repositories.get_sensor_readings(_conn, stream_id)
    anomalies = repositories.list_anomalies(_conn, stream_id)
    path = reports_module.generate_sensor_report_pdf(streams[0], readings, anomalies)
    repositories.log_audit(_conn, user.username, "REPORT_GENERATED", "SUCCESS",
                            object_type="sensor_report", object_id=stream_id)
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


@app.get("/reports/asset/{asset_id}")
def report_asset(asset_id: str, user: User = Depends(get_current_user)):
    graph = repositories.get_asset_graph(_conn, asset_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = reports_module.generate_asset_history_report_pdf(graph)
    repositories.log_audit(_conn, user.username, "REPORT_GENERATED", "SUCCESS",
                            object_type="asset_report", object_id=asset_id)
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


# ---------- WebSocket streaming ----------

@app.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket, token: Optional[str] = None):
    """Bearer tokens can't be set as a WebSocket handshake header from a
    browser, so the token travels as a query param instead (?token=...) —
    the standard workaround for browser WebSocket auth. Rejected before
    accept() if missing/invalid, so an unauthenticated client never even
    reaches the open-connection state."""
    user = auth.decode_token(token) if token else None
    if user is None:
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection open; client isn't required to send anything meaningful
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ---------- static GUI + media ----------
# Mounted last so it never shadows the API routes above.
app.mount("/media", StaticFiles(directory="data/videos"), name="media")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
