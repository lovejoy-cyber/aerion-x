# AERION-X — Core Engine + Backend + GUI + Hardening (Phases 1-6)

## Phase 6: hardening

Real authentication (PBKDF2+JWT, ADMIN/ENGINEER/OPERATOR roles), audit log,
real PDF report generation (ReportLab — inspection/event/sensor/asset
reports, all from real stored data), server-side event pagination, path-
traversal protection, real backup/restore (tested with actual data
destruction), a scoped-but-real PostgreSQL schema validation, a genuine
clean-install test (fresh venv, 92/92 pass), Docker/Compose files. Full
honest scope in [LIMITATIONS.md](LIMITATIONS.md), [SECURITY.md](SECURITY.md),
[DATA_PROVENANCE.md](DATA_PROVENANCE.md), [PERFORMANCE.md](PERFORMANCE.md),
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

Run: `uvicorn backend.main:app --host 127.0.0.1 --port 8000`, register the
first account (becomes ADMIN), sign in.

---

## Phase 4/5: real GUI, wired to the real backend

`frontend/` — vanilla HTML/CSS/JS (no build step), served by FastAPI's
StaticFiles at `/`. Six real workspaces, every one driven by the actual API/WebSocket,
verified in a real browser this session (not just code-reviewed):

- **Command Center** — real pipeline start/stop controls, live WebSocket telemetry (FPS/latency/tracks), live event feed, and the actual annotated video output playing (re-encoded to WebM after finding the original mp4v output was silently unplayable in-browser — see LIMITATIONS.md bug #5)
- **Event Intelligence** — real persisted events, filterable by type, severity/provenance color-coded
- **Sensor Workspace** — triggers a real synthetic-vibration-stream + z-score-detection run via the API, renders an actual SVG chart with real anomaly markers
- **Inspection** — runs the real change-detection/SSIM pipeline against real video frames on demand, shows real regions and history
- **Motion Analysis** — real Farneback optical flow computed on demand between two real frames
- **Assets** — create real assets, see their real linked sensor/inspection/event/anomaly counts

Run: `uvicorn backend.main:app --host 127.0.0.1 --port 8000` then open `http://127.0.0.1:8000/`.

---

# AERION-X — Core Engine (Phase 1 + Phase 2 intelligence layer)

Real computer-vision + engineering-intelligence core: detection → pose → tracking →
temporal state → spatial zones → safety/ops events → sensor anomaly detection →
cross-stream correlation → inspection → optical flow, all source-agnostic (video
file / synthetic today, USB camera is a drop-in adapter for later — no core code
changes required). Every number in this README is from an actual measured run, not
an estimate. See [LIMITATIONS.md](LIMITATIONS.md) for the honest gaps, including two
real bugs found and fixed by actually executing the pipeline.

## What's real right now

- **Detection**: genuine pretrained YOLOv8n (COCO, 80 classes) via Ultralytics/PyTorch, CPU inference. Tested on real video: 795 frames, 6,467 real detections.
- **Pose**: YOLOv8n-pose, tested on 200 real frames (63 person detections, 5 tracked people).
- **Tracking**: IoU + bounded centroid-distance fallback, stable IDs, ages out lost tracks.
- **Temporal state**: STATIONARY/WALKING/MOVING from a sliding window of real motion history — never a single frame.
- **Spatial zones**: point-in-polygon occupancy in 2D pixel space (no 3D/real-world distance — that needs calibration, out of scope).
- **Core events**: OBJECT_APPEARED/DISAPPEARED, ZONE_ENTER/EXIT, STATE_CHANGE, PROLONGED_STATIONARY.
- **Worker safety events**: PERSON_VEHICLE_PROXIMITY, CROWDING, PERSON/VEHICLE_RESTRICTED_ZONE_ENTRY, PROLONGED_IMMOBILITY, FALL_LIKE_MOTION (geometric bbox heuristic, explicitly not a medical claim). All onset-debounced — fire once on transition, not every frame.
- **Aviation ops events**: AREA_OCCUPANCY, UNEXPECTED_OBJECT, CONGESTION (temporal, sustained-duration threshold).
- **Unified event schema**: every module emits the same `Event` shape (id, type, timestamp, source, asset_id, track_ids, severity, confidence, duration, provenance, evidence, metadata).
- **Sensor + anomaly pipeline**: real CSV round-trip, z-score/rolling-threshold/CUSUM (pure NumPy) + optional Isolation Forest (sklearn). Validated against a known injected anomaly — detectors found it at the exact timestamps.
- **Cross-stream correlation**: `CorrelationEngine` groups events from different sources within a time window — coincidence only, never causation (no `caused_by` field exists).
- **Aircraft inspection foundation**: CLAHE, Canny, ORB-based image registration, before/after change detection, real windowed SSIM, contour-based region scoring — all tested against real video frames. `DefectDetector.detect()` deliberately raises `NotImplementedError`: no crack/corrosion model or dataset exists.
- **Optical flow**: real Farneback + Lucas-Kanade (OpenCV), plus region-based flow statistics and baseline-relative abnormal-motion detection (z-score on flow magnitude).
- **Model registry**: real metadata pulled from the loaded model object (3,157,200 params, 80 classes, actual weights URL/license) — nothing hardcoded.
- **Evaluation infrastructure**: precision/recall/F1/IoU/confusion-matrix, honestly returns `"EVALUATION DATASET: NOT AVAILABLE"` when no ground truth is supplied — never fabricates accuracy.
- **Asset graph**: `AssetRegistry` links real inspection reports, real anomaly results, and real vision events to one asset (`scripts/run_asset_graph_demo.py` demonstrates this end to end).
- **Measured performance optimization**: imgsz=320 vs 640 benchmarked on 40 real frames — 2.75x faster, ~8.4% fewer detections. Now a real constructor parameter on `YoloDetector`, not just a benchmark footnote.
- **Sources**: `VideoFileSource` (real files via OpenCV) and `SyntheticSource` (deterministic, always labeled `SYNTHETIC`).

## What's explicitly NOT built yet

- No webcam adapter tested (dev machine has no camera) — interface exists (`adapters/base.py`), untested in practice.
- No backend API, database, or persistence layer. No auth. No web GUI — the "viewer" is a real-time text dashboard plus an actual annotated output video (`scripts/run_integrated.py`), by design: the project's own priority order was CV/intelligence core first, GUI/backend later.
- No aircraft-specific defect detection (needs a dataset that doesn't exist locally).

## Real measured performance (CPU-only, no GPU on this machine)

| Config | FPS | Avg latency |
|---|---|---|
| Detection only, imgsz=640 | 4.30 | 227ms |
| Detection + pose | 3.05 | 324ms |
| Detection only, imgsz=320 | ~12.35 (40-frame sample) | 81.0ms |

364MB RSS, ~34% CPU during full-pipeline run.

## Source labeling

Every `Frame` carries `source_type`; every `Event` carries `provenance` (REAL/SYNTHETIC/SIMULATION).
Synthetic data is never presented as camera or sensor evidence.

## Test video

`data/videos/vtest.avi` — OpenCV's standard pedestrian-corridor sample (BSD-licensed,
official opencv/opencv samples repo).

## Running it

```bash
pip install -r requirements.txt
pytest -v                                                                  # 46/46 pass

# core CV pipeline (detection + tracking + temporal + zones)
python -m scripts.run_pipeline --source video --path data/videos/vtest.avi --zone --no-display

# pose pipeline
python -m scripts.run_pose_pipeline --path data/videos/vtest.avi --zone --max-frames 200

# full integrated pipeline: detection + tracking + safety + ops + real annotated video output
python -m scripts.run_integrated --max-frames 300

# sensor -> anomaly -> event pipeline
python -m scripts.run_sensor_pipeline

# real asset graph tying inspection + sensor + anomaly together
python -m scripts.run_asset_graph_demo

# measured resolution performance tradeoff
python -m scripts.benchmark_resolution
```

Drop `--no-display` on `run_pipeline.py` to see a live OpenCV window (press `q` to quit) — only works when run on a machine with a display attached, not through a headless terminal.
