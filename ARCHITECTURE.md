# AERION-X — Architecture

```
INPUT ADAPTERS (adapters/)
  VideoFileSource | SyntheticSource | [webcam interface defined, untested — no camera on dev machine]
        |
        v
   core.contracts.Frame  (source_type, timestamp, image — identical shape regardless of source)
        |
        v
CV / ML ENGINE (core/cv/)
  YoloDetector, YoloPoseEstimator  (implement core.interfaces.Detector / PoseEstimator)
        |
        v
TRACKING (core/tracking/)
  CentroidIoUTracker — IoU match, bounded centroid-distance fallback for fast motion
        |
        v
TEMPORAL (core/temporal/)
  state_engine — classifies STATIONARY/WALKING/MOVING from a sliding window, never one frame
        |
        v
SPATIAL (core/spatial/)
  ZoneRegistry — point-in-polygon occupancy in 2D pixel space
        |
        v
EVENT LAYER (core/events/, core/safety/)
  EventEngine (core events) + WorkerSafetyEngine + AviationOpsEngine
  all emit core.contracts.Event — one schema for every subsystem
        |
        v
CORRELATION (core/correlation/)
  CorrelationEngine — groups cross-source events within a time window (coincidence, never causation)
        |
        v
PERSISTENCE (backend/db.py, backend/repositories.py)
  SQLite, raw sqlite3 (no ORM) — swap-in-place migration path to Postgres via the same repository functions
        |
        v
API + STREAMING (backend/main.py)
  FastAPI REST endpoints + one WebSocket (/ws/pipeline) broadcasting real pipeline events/status
```

A parallel, independent path handles engineering telemetry:

```
core.sensors.telemetry (CSV/JSON) -> core.sensors.anomaly (z-score/rolling/CUSUM/IsolationForest)
    -> core.contracts.Event -> same persistence/API/correlation path as vision events
```

And a third, independent path for asset inspection:

```
two images -> core.inspection.pipeline (CLAHE, ORB registration, change detection, SSIM, contours)
    -> InspectionReport -> persistence -> core.assets.domain (linked to an Asset)
```

## Design principles actually followed (not aspirational)

- **The intelligence core never imports FastAPI, sqlite3, or anything backend-specific.** `core/` only depends on numpy/opencv/torch/scipy/sklearn. `backend/` depends on `core/`, never the reverse — verified by the fact that every `core/` module has tests that don't touch `backend/`.
- **Every subsystem speaks the same `Event` schema** (`core/contracts.py`) regardless of origin (vision, sensor, correlation) — this is what let the correlation engine and the database layer be written generically instead of per-subsystem.
- **`Detector`/`PoseEstimator`/`Tracker`/`AnomalyDetector`/`FlowEstimator` are abstract interfaces** (`core/interfaces.py`); `YoloDetector` etc. are one implementation each. A future aerospace-specific model or a different tracker plugs in without touching callers.
- **Source-agnostic by construction, not by promise**: `VideoFileSource` and `SyntheticSource` both implement `adapters.base.FrameSource` and produce identical `Frame` objects; the entire CV/tracking/temporal/spatial/event chain has zero source-type branches in it. A webcam adapter is a third implementation of the same interface — not written yet (no camera on this dev machine), but nothing else changes when it is.

## Phase 6 additions

```
backend/auth.py         — PBKDF2 password hashing + JWT issuance/validation, no framework dependency
backend/reports.py      — ReportLab PDF generation, reads only from repositories.py, never fabricates a field
backend/backup.py       — real sqlite3 online-backup API wrapper
```

Auth is enforced at the FastAPI route layer (`Depends(get_current_user)` /
`Depends(require_role(...))` in `backend/main.py`) — `backend/auth.py` itself
has zero FastAPI imports and is fully unit-testable without an HTTP layer.

## What is NOT abstracted (deliberately)

- `PipelineManager` (`backend/services.py`) runs one pipeline at a time. This is a monitoring/inspection tool, not a multi-tenant video platform — a real multi-camera deployment would need a pool of managers, which does not exist here.
- No dependency-injection framework, no plugin auto-discovery. Swapping a detector today means changing one constructor call, which is honest about the current scale of the project rather than pre-building for a scale it hasn't reached.
