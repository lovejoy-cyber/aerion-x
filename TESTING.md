# AERION-X — Testing

**96/96 tests pass** (`python -m pytest -v`, ~70s).

## Breakdown by file

| File | Count | What it actually exercises |
|---|---|---|
| `test_tracking_temporal.py` | 6 | Tracker, temporal state engine, zones, events |
| `test_safety_engine.py` | 10 | Worker safety + aviation ops event logic, onset-debounce regression |
| `test_sensor_anomaly.py` | 6 | z-score/rolling/CUSUM against a known injected anomaly |
| `test_inspection_and_flow.py` | 9 | Real SSIM, contour scoring, change detection, optical flow on real frames |
| `test_correlation.py` | 4 | Cross-source time-window correlation, causation-never-claimed |
| `test_model_lab.py` | 6 | IoU math, evaluation metrics, model registry |
| `test_assets.py` | 5 | Asset graph linking |
| `test_backend_db.py` | 13 | Real SQLite schema + repository round-trips, idempotent-resave regression |
| `test_backend_api.py` | 25 | Real FastAPI HTTP/WebSocket, auth, RBAC, rate limiting, pagination, path-traversal rejection, PDF reports, field-capture upload |
| `test_pipeline_manager.py` | 4 | Real background-thread pipeline lifecycle |
| `test_end_to_end.py` | 5 | TEST A-E (below) |
| `test_backup_restore.py` | 3 | Real backup/restore with actual data destruction |

## TEST A-E (Phase 6 Part 27, all real, all present)

- **A** — real video → YOLO → tracking → temporal → zone → safety event → DB → API → WebSocket
- **B** — sensor → anomaly → DB → correlation → asset → **PDF report**
- **C** — inspection → SSIM/regions → DB → asset → **PDF report**
- **D** — pipeline failure recovery: start against a nonexistent video path, verify clean `ERROR` status (not a stuck/orphaned thread), verify a subsequent legitimate run still succeeds
- **E** — unauthorized request rejected (401), authorized accepted, role restriction enforced (403) with a matching audit-log entry

## Real bugs found and fixed by this test suite (not hypothetical) — full list across all phases

1. Tracker's promised IoU→centroid fallback never existed
2. Safety/ops events fired every frame instead of on transition (3,367+4,308 spam events on one real run)
3. Windows SQLite file-locking race — tests polled status instead of joining the thread
4. `POST /pipeline/start` returned 200 for invalid input (validation ran on the wrong thread)
5. Annotated video codec (`mp4v`) was silently unplayable in every browser — no H.264 encoder on this machine
6. `save_sensor_stream` duplicated readings on re-save instead of replacing them
7. `.login-overlay[hidden]`/`.shell[hidden]` had no effect — a class rule with `display: flex`/`grid` silently beat the `[hidden]` UA default, found by actually testing login in a browser, not by code review
8. Docker image: torch/torchvision installed from mismatched indexes → `operator torchvision::nms does not exist` at runtime — found by actually running a pipeline inside the built container, not by inspecting the Dockerfile; fixed and re-verified with a full real pipeline run (real detections, real events) inside the rebuilt container

## Running

```bash
pip install -r requirements.txt
pytest -v                              # full suite, ~50s
pytest tests/test_end_to_end.py -v     # TEST A-E only
pytest tests/test_backup_restore.py -v # real backup/restore
python -m scripts.validate_postgres    # requires a running isolated Postgres container — see DEPLOYMENT.md
```

## Not covered by automated tests

- Live webcam capture (no camera on the dev machine).
- Multi-client WebSocket load / backpressure under many simultaneous connections.
- The Docker image, beyond a build attempt (see DEPLOYMENT.md for the actual outcome).
- PostgreSQL through the real repository layer (only the schema/data-model was validated — see DATA_PROVENANCE.md and DEPLOYMENT.md).
- GUI visual regression / accessibility testing (manual browser verification only, this session).
