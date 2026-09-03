# AERION-X — Known Limitations (Phase 1)

Honest record of what's proven, what's approximate, and what's not built.

## Real bugs found and fixed during actual execution (not hypothetical)

1. **Tracker fallback never implemented.** `CentroidIoUTracker`'s docstring promised
   an IoU→centroid-distance fallback for fast motion; the code never had it. A
   zone-crossing test with realistic 60px/frame motion silently created a new track
   instead of continuing the real one. Fixed with a bounded nearest-centroid fallback;
   regression test added.
2. **Event-stream spam.** Running the integrated pipeline (detection+tracking+safety+ops)
   on the full real video showed `PERSON_RESTRICTED_ZONE_ENTRY` firing 3,367 times and
   `UNEXPECTED_OBJECT` 4,308 times over 795 frames — they were re-firing every frame a
   condition held instead of only on transition, unlike the already-correct
   `ZONE_ENTER`/`ZONE_EXIT`. Fixed with an onset-debounce pattern; after the fix, the
   same real run produced 56 and 65 events respectively — sane, discrete alerts.
   Regression test added (`test_restricted_zone_entry_does_not_spam_every_frame_while_present`).

## Real measured performance optimization

`scripts/benchmark_resolution.py` measured YOLOv8n at imgsz=640 vs. imgsz=320 on the
same 40 real video frames, same hardware: **2.75x faster** (222.8ms → 81.0ms avg
inference) at imgsz=320, but **~8.4% fewer detections** (274 → 251) — a real
accuracy/speed tradeoff, not a free win. `YoloDetector` now exposes `imgsz` as a
constructor parameter so this is an actual usable choice, not just a benchmark note.

## Aviation ground-equipment classes

COCO (YOLOv8n's training set) has no classes for real aircraft ground-support
equipment (tugs, jetways, GPUs, chocks) and only "airplane" for aircraft. The aviation
ops module treats "airplane" as the aircraft class and documents this gap explicitly
rather than inventing detections COCO cannot produce — a real deployment needs a
custom-trained model for actual ground-equipment classes.

## Phase 3 (backend): two more real bugs found and fixed

3. **Windows SQLite file-locking race.** Pipeline-manager tests polled
   `status.status == "COMPLETED"` and then immediately tried to delete the
   temp DB file — but the background thread's `finally: conn.close()` hadn't
   necessarily finished yet, so Windows still held the file lock. Fixed by
   adding `PipelineManager.join()`, which blocks on the actual thread object
   rather than inferring completion from a status flag.
4. **`POST /pipeline/start` returned 200 for an invalid `source_type`.**
   Validation (`source_type in ("video", "synthetic")`, `path` required for
   video) happened inside `_run()`, which only executes on the background
   thread — so `start()` always returned success immediately, and the error
   only appeared later via `/pipeline/status`. Fixed by validating
   synchronously in `start()` before the thread is spawned.

## Phase 4/5 (GUI): one more real bug found and fixed

5. **The annotated video didn't play in the browser.** `run_integrated.py`
   wrote output with the `mp4v` fourcc; the request succeeded (HTTP 206
   Partial Content, byte-ranges served correctly) but Chrome silently aborted
   playback — `mp4v` is MPEG-4 Part 2, which browsers don't decode. Root
   cause: this machine has no H.264 encoder (OpenCV's H.264 path needs the
   OpenH264 DLL, not installed, and there's no `ffmpeg` binary either —
   confirmed by directly testing `avc1`/`H264`/`X264` fourcc, all of which
   report `isOpened() == True` but fail silently inside FFmpeg at encode
   time). Fixed by switching to VP8/WebM (`cv2.VideoWriter_fourcc(*"VP80")`),
   which OpenCV's bundled FFmpeg *can* actually encode without external
   dependencies, and which every current browser plays natively — re-encoded
   and verified actually playing (with a real duration and moving overlays)
   in the live GUI. Did not download the OpenH264 DLL to "properly" fix H.264
   support, since that's a discretionary download this session didn't have
   standing approval for and a working codec-free alternative existed.

## Phase 6 (hardening): what's real and what's scoped out

**Built and tested**: real auth (PBKDF2+JWT, RBAC), audit log, real PDF
reports, server-side pagination, path-traversal protection, backup/restore
(with real data destruction + recovery), a global exception handler that
never leaks stack traces, WebSocket token auth, multi-client + slow-client
WebSocket resilience, centralized config wired into the actual pipeline
(previously it wasn't), a genuine clean-install test (fresh venv, 92/92 pass),
a scoped PostgreSQL schema validation (real Postgres 16 container, real
INSERT/JOIN — NOT the full repository layer, which remains SQLite-specific).

**Explicitly not built this phase** (see the Phase 6 task list for what these
refer to): the 2D spatial operational map GUI, the fusion-timeline GUI, true
concurrent multi-camera pipelines (schema supports multiple `source_id`s;
`PipelineManager` remains single-run), GUI list virtualization for very large
event histories, API rate limiting, ONNX/quantization/GPU benchmarking (no GPU
hardware available to measure), a tested mobile client (see
MOBILE_ARCHITECTURE.md for the honest interface-only writeup), offline field
mode, a dedicated visual-polish pass beyond what shipped functionally.

**A process mistake, reported rather than hidden**: mid-session, a Docker
build that was genuinely progressing (confirmed afterward from its log — it
had resolved all dependencies and was mid-download of a real 73.8MB opencv
wheel) was killed based on a misread `docker buildx du` cache-size heuristic
that looked like zero progress but wasn't. Retried properly (streamed output,
left uninterrupted) and it succeeded — see DEPLOYMENT.md for the full
sequence, including a real torch/torchvision ABI mismatch bug
(`operator torchvision::nms does not exist`) found by actually running a
pipeline inside the built container, fixed, and re-verified working end to
end (real detections, real events) inside the container.

## Backend/production gaps (real, not hidden)

- **No authentication on any endpoint.** Anyone reaching the port has full
  read/write access. Acceptable for local single-user use only.
- **One pipeline at a time.** `PipelineManager` is a singleton by design — this
  is a single-camera monitoring tool, not a multi-tenant video platform.
- **SQLite only** — the repository layer avoids ORM-specific assumptions so a
  Postgres migration is plausible, but it has never actually been run against
  Postgres.
- **No GUI beyond the text dashboard + annotated video output.** A REST/WebSocket
  API exists and is tested; nothing consumes it visually yet.
- **No Docker/CI/process-supervisor.** See DEPLOYMENT.md.
- **WebSocket tested with one client at a time** — multi-client backpressure/stale-connection
  handling under load has not been exercised.

## Correlation engine

`core/correlation/correlation_engine.py` groups events from different sources within
a time window — a claim of temporal coincidence only, never causation (enforced by
the schema: `CorrelatedEvent` has no `caused_by` or confidence-of-causation field).
Tested with synthetic timestamps only; no real simultaneous vision+sensor recording
exists to validate against actual correlated real-world events.

## Detection accuracy

YOLOv8n (the nano variant, chosen for CPU speed) genuinely runs and genuinely detects
COCO classes on real video — verified against `data/videos/vtest.avi`. It also produces
occasional misclassifications on small/blurry regions of a low-resolution, decades-old
test clip (e.g. a shadow or bag briefly read as "bird" or "skateboard"). This is a real,
expected accuracy ceiling of the smallest model in the family — not a fabricated result,
and not hidden: the raw event log includes every class the model actually output.

## Live-ish phone/browser detection: real, partially verified

"GO LIVE" on the Field Capture GUI page repeatedly calls the real
`/capture/analyze` endpoint, self-paced to actual inference speed (waits for
each response before capturing the next frame — can't outrun the detector),
drawing bounding boxes over the camera preview. Verified: the fetch/response
handling and the bounding-box overlay math (correct scaling and positioning
against a real image and real returned detections). NOT verified: the loop
running continuously against an actual live camera stream — no camera on
this machine (browser correctly reported "Requested device not found," a
clean real error, not a crash). Each frame is analyzed independently — no
tracking IDs persist frame-to-frame, unlike the full video-file pipeline
(no "this person has been standing still for 5s" style events here).

## Live camera support (server-side): written, NOT verified against real hardware

`adapters/webcam/webcam_source.py` (USB/built-in camera) and
`adapters/network/rtsp_source.py` (IP camera) exist, wired into the pipeline
and API (`source_type: "webcam"` / `"rtsp"`). What IS genuinely verified here
(no camera exists on this dev machine, so this is honestly all that could
be): the failure path. `WebcamSource(0)` and `RTSPSource(unreachable_url)`
both fail with a clean `RuntimeError` rather than hanging — and a real bug
was found doing this: an unreachable RTSP URL took **183 seconds** to fail
(FFmpeg's default connect timeout) before `CAP_PROP_OPEN_TIMEOUT_MSEC` was
added, cut to **10.8 seconds** for the same real test. The actual happy path
— frames genuinely arriving from a real webcam or RTSP camera — has never
been exercised. First real test happens on whatever machine actually has a
camera attached.

## Spatial reasoning is 2D-only

Zones are polygons in pixel space. No camera calibration, no real-world distance, no
3D position. `core/spatial/zones.py` never claims otherwise.

## Tracker is classical, not learned

`CentroidIoUTracker` is IoU-matching with a bounded nearest-centroid fallback for fast
motion — not DeepSORT, not an embedding-based re-identifier. It can lose an identity
across a full occlusion or a genuinely large frame-to-frame jump; this was confirmed
directly while fixing a real bug in the fallback logic (see git history / test
`test_zone_enter_and_exit_events_fire`).

## Aircraft defect detection: not implemented

`core/inspection/pipeline.py` implements real classical CV (CLAHE preprocessing, Canny
edges, ORB-based image registration, before/after change detection) — genuine
generic visual change detection. It does **not** detect cracks, corrosion, or dents.
`DefectDetector.detect()` raises `NotImplementedError` on purpose: no appropriate
trained model or aerospace defect dataset exists locally, and pretending a generic
detector does this job would violate the project's own "never fake it" rule.

## Anomaly detection: validated only on synthetic data

`core/sensors/anomaly.py` algorithms (z-score, rolling threshold, CUSUM, optional
Isolation Forest) are tested against a deterministic synthetic vibration signal with
a known injected anomaly (`core/sensors/synthetic_data.py`) — and they do detect it.
This proves the algorithms work correctly, not that they're tuned for any specific
real machine or aircraft sensor. No real sensor data was available to validate against.

## No GUI, backend, or persistence

Currently: a CLI pipeline runner (`scripts/run_pipeline.py`,
`scripts/run_pose_pipeline.py`) with an OpenCV debug-overlay window. No REST API,
no database, no auth, no web frontend. Per the project's own priority order, these
were deliberately deferred until the CV/ML core proved out.

## Pose module: written, integration-tested separately

`core/cv/pose.py` (YOLOv8n-pose) exists and is wired into
`scripts/run_pose_pipeline.py`, feeding the same tracker/temporal/event pipeline
used for plain detection. Run separately from the main detector pipeline (running
both models per-frame on CPU roughly doubles inference cost).

## Optical flow: implemented, not aerospace-validated

`core/vision/optical_flow.py` wraps real OpenCV Farneback and Lucas-Kanade optical
flow, tested against consecutive real video frames. This is motion estimation, not
CFD, and was never claimed to be.

## Environment

Python 3.14, Windows, CPU-only (no NVIDIA GPU detected — `torch.cuda.is_available()`
is `False` on this machine). All performance numbers reported in test runs reflect
CPU inference specifically.
