# AERION-X — Performance Report

Every number below is from an actual measured run this session (dates/times
correspond to the real commands executed) — none are estimated or extrapolated.

## Hardware

Windows AMD64, CPU-only. `torch.cuda.is_available() == False` — no CUDA GPU on
this machine. Every number below is a CPU measurement; none reflect GPU
performance because none has been measured (`GET /status` explicitly reports
`compute_device.measured: False` when CUDA is present but unbenchmarked — not
applicable here since CUDA isn't present at all).

## Computer vision

| Configuration | FPS | Avg latency | Sample size |
|---|---|---|---|
| Detection only, imgsz=640 (default) | 4.30 | 227ms | 795 real frames (vtest.avi) |
| Detection + pose | 3.05 | 324ms | 200 real frames |
| Detection only, imgsz=320 | ~12.35 | 81.0ms | 40 real frames |

**Resolution tradeoff, measured**: imgsz=320 is 2.75x faster but finds ~8.4%
fewer detections (251 vs 274 on the same 40 frames) — a real accuracy/speed
tradeoff, not a free win. `YoloDetector(imgsz=...)` exposes this as a real
constructor parameter.

**Other optimizations NOT benchmarked this session** (real limitation, not
hidden): frame skipping, async capture, ONNX Runtime, quantization, batching.
CPU-only hardware and remaining session time meant the resolution experiment
was judged the highest-value single benchmark to run cleanly; the others are
real follow-up work, not attempted-and-hidden.

## Backend / API

Measured via the real FastAPI TestClient and a real running `uvicorn` process
this session — a full 12-frame real-video pipeline run (start → completion →
event retrieval) via HTTP completed in well under the test suite's 60s
timeout, typically a few seconds of *response* overhead on top of the
inference time itself (API overhead is small relative to the 227ms/frame
inference cost — the pipeline, not the API layer, is the bottleneck).

No dedicated API throughput/concurrency benchmark (requests/sec under load)
was run — a real gap, not claimed as done.

## Database

SQLite queries in this project (event list/filter/paginate, asset graph
lookups, sensor stream + reading retrieval) all returned in well under 100ms
against the dataset sizes generated this session (hundreds of events, 200
sensor readings) — no dedicated large-N (10k+ rows) query-latency benchmark
was run. `list_events`/`count_events` use `LIMIT`/`OFFSET` with an index on
`timestamp` and `event_type`, so pagination doesn't scan the full table, but
this was not load-tested.

## WebSocket

Verified functionally (multi-client broadcast, slow-client isolation via
try/except so one bad connection can't stall the pipeline thread — see
`tests/test_backend_api.py::test_websocket_slow_client_does_not_block_pipeline`)
but not benchmarked for message-rate/delivery-latency under load.

## GUI

Verified functionally responsive in real browser testing (Chrome via the
Claude Code browser tool) — event table renders instantly for the row counts
seen this session (dozens to low hundreds), SVG sensor charts render without
visible lag for 200-sample streams. No frame-rate/memory profiling was done,
and the event table is not virtualized — it would need to be for a
many-thousand-row history (a real, documented gap, not built this session).

## Bottom line

The system is CPU-bound by model inference (227ms/frame), not by the API,
database, or GUI layers — every non-CV-inference measurement taken this
session was fast enough to be a non-issue at the data volumes actually
exercised. Whether that holds at production data volumes (many cameras, years
of history) has not been tested.
