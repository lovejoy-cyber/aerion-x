# AERION-X — API Reference

Every endpoint below was exercised by an automated test or a manual `curl` call
against a real running `uvicorn` process this session — none are speculative.

Base: `http://127.0.0.1:8000` (default uvicorn port; examples below used 8123 for testing).

## Authentication

Every `GET` is unauthenticated (see SECURITY.md for why). Every `POST` below
needs `Authorization: Bearer <token>` unless noted.

- `POST /auth/register` — `{"username", "password"}`. First user on a fresh DB becomes ADMIN; everyone after is OPERATOR.
- `POST /auth/login` — `{"username", "password"}` → `{"access_token", "token_type", "role"}`
- `GET /auth/me` — requires auth, returns the caller's identity/role
- `GET /audit-log?limit=&offset=` — ADMIN only

## Health / status

- `GET /health` → `{"status": "ok", "time": <unix ts>}`
- `GET /status` → real platform string, `compute_device` (`{"device": "CPU"|"CUDA", ...}`, real `torch.cuda.is_available()` check — never claims GPU performance without having measured it), current pipeline status/FPS

## Models

- `GET /models` → models persisted in the registry
- `POST /models/register-yolo` → loads the actual YOLOv8n model, extracts real metadata (class list, parameter count from the live model object), persists it

## Pipeline

- `POST /pipeline/start` — auth required. Body: `{"source_type": "video"|"synthetic", "path": str|null, "max_frames": int|null, "zone": bool}`. Returns `409` if a pipeline is already running, `400` for an invalid `source_type`, a missing `path`, or a `path` that escapes `data/` (path traversal check — see SECURITY.md).
- `POST /pipeline/stop` — signals the running pipeline to stop after its current frame.
- `GET /pipeline/status` — real-time status: frames processed, FPS, last inference latency, active track count.
- `GET /pipeline/runs` — history of pipeline runs from the database.

## Events

- `GET /events?event_type=&severity=&limit=&offset=` — paginated: returns `{"items": [...], "total": <int>, "limit": <int>, "offset": <int>}`, filtered and paginated server-side (never loads full history into memory).
- `POST /correlations/compute?window_seconds=<float>&limit=<int>` — auth required. Runs the real `CorrelationEngine` over recent persisted events, persists any correlations found.
- `GET /correlations` — persisted correlations.

## Field capture (works from a phone browser)

- `POST /capture/analyze` — auth required. `multipart/form-data`, field `file` (JPEG/PNG/WebP, max 10MB). Runs the real YOLO detector on the uploaded image, returns `{"detections": [...], "inference_ms", "image_width", "image_height"}`. No native app needed — a phone's own browser (Safari/Chrome) can call this directly via `getUserMedia` + `fetch`. See MOBILE_ARCHITECTURE.md for the HTTPS/secure-context constraint on live camera capture from another device.

## Reports (real PDFs via ReportLab)

- `GET /reports/inspection/{inspection_id}` — auth required
- `GET /reports/events?event_type=&limit=` — auth required
- `GET /reports/sensor/{stream_id}` — auth required
- `GET /reports/asset/{asset_id}` — auth required

All return `application/pdf`. Every field comes from the database — never fabricated.

## Admin

- `POST /admin/backup` — ADMIN only. Real sqlite3 online-backup snapshot, written to `data/backups/`.
- `GET /admin/backups` — ADMIN only. Lists real backup files with size/timestamp.
- Restore is intentionally **not** an API endpoint (restoring into a live DB file corrupts it) — use `python -m scripts.restore_backup <path>` with the server stopped.

## Assets

- `POST /assets` — body: `{"asset_id", "asset_type", "name"}`. `asset_type` must be a valid `AssetType` enum value (`AIRCRAFT`, `ENGINE`, `DRONE`, `GROUND_VEHICLE`, `WORKER`, `EQUIPMENT`, `MACHINE`, `PIPELINE`, `INFRASTRUCTURE`) or `400`.
- `GET /assets` — list all.
- `GET /assets/{asset_id}` — `404` if not found.

## Inspections / sensors

- `GET /inspections?asset_id=<str>`
- `GET /sensors/streams`
- `GET /sensors/streams/{stream_id}/readings`
- `GET /sensors/anomalies?stream_id=<str>`

## WebSocket

- `ws://.../ws/pipeline` — broadcasts `{"type": "status", ...}` and `{"type": "event", ...}` messages while a pipeline is running. Tested with a real client connected during a real video pipeline run (`tests/test_backend_api.py::test_websocket_receives_real_pipeline_status_broadcasts`, `tests/test_end_to_end.py`).

## Not implemented

No write endpoints for inspections, sensor streams, or model evaluation runs yet
(those are currently populated only via direct script/repository calls, e.g.
`scripts/run_sensor_pipeline.py`, `scripts/run_asset_graph_demo.py`). No auth on
any endpoint — see LIMITATIONS.md.
