# AERION-X — Deployment

## Local (tested this session)

```bash
pip install -r requirements.txt
export AERIONX_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"  # or set your own
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. First account you register becomes ADMIN.

Verified this session: real process start, `/health`/`/status` respond, a real
video pipeline run persists real events retrievable via `/events`, real GUI
login/pipeline/reports/audit-log flows work end-to-end in an actual browser.

Requirements: Python 3.14 (tested), Windows (tested; no Windows-only APIs in
core, Linux expected to work but untested this session), no GPU required
(CPU-only inference verified — `torch.cuda.is_available() == False` here,
pipeline works anyway).

## Docker

`Dockerfile` and `docker-compose.yml` exist at the repo root.

```bash
export AERIONX_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"
docker compose up --build
```

**Build status: succeeded, verified working, real bug found and fixed
along the way.** Sequence, honestly:

1. First build attempt: genuinely progressing (confirmed from its log) but
   an interim `docker buildx du` progress check was misread as "stuck" and
   the build was killed prematurely — a real process mistake, not a build
   defect.
2. Retried with `docker build --progress=plain` (streams instead of
   buffering) and let it run uninterrupted (~15 min, mostly the CPU
   torch+opencv+ultralytics download over a slow container network path,
   down to ~120-160 kB/s at points). **This build completed successfully**:
   `docker images aerionx` → real 715MB image.
3. Ran it (`docker run -p 8200:8000 ... aerionx:latest`) and hit a real bug:
   `POST /pipeline/start` returned `{"status": "ERROR", "error_message":
   "operator torchvision::nms does not exist"}` — a torch/torchvision ABI
   mismatch, because the Dockerfile installed `torch` from the CPU wheel
   index but let `requirements.txt`'s later `pip install` resolve
   `torchvision` (an ultralytics dependency) from default PyPI, giving two
   incompatible builds.
4. Fixed by installing both from the same CPU index in one command
   (`pip install --index-url https://download.pytorch.org/whl/cpu torch
   torchvision`) and adding `torchvision` explicitly to `requirements.txt`.
5. Rebuilt, ran again, and **verified a full real pipeline run inside the
   container**: registered a user, logged in, started a pipeline against the
   baked-in `vtest.avi`, got `"status": "COMPLETED"` with real detections
   (person/truck/car) and real persisted events retrievable via `GET /events`
   — all through the actual containerized API, port-mapped to the host.

```bash
docker build -t aerionx:latest .
docker run -d -p 8000:8000 -e AERIONX_JWT_SECRET=$(python -c 'import secrets;print(secrets.token_hex(32))') aerionx:latest
curl http://127.0.0.1:8000/health
```

CPU-only base image (`python:3.12-slim`) — no CUDA. A GPU-enabled Dockerfile
variant does not exist and has not been attempted (no GPU on this dev machine
to build/test it against).

## Clean install (Part 28) — verified this session

A fresh Python venv (not this project's existing environment — genuinely
empty), `pip install -r requirements.txt`, then `pytest -q`: **92/92 passed**,
zero manual fixes required. This is on the same physical machine (not a truly
separate one — an honest caveat, not a claim of cross-machine validation), but
it does prove the dependency list is complete and self-contained: nothing in
this project silently depends on a package that isn't in `requirements.txt`.

## PostgreSQL

**Not integrated into `backend/repositories.py`** — that module calls
`sqlite3.Connection.execute()` directly with `?` placeholders throughout,
which is not psycopg2-compatible as-is. What *was* validated this session
(`scripts/validate_postgres.py`, run against a real, isolated PostgreSQL 16
Docker container, `INSERT`/`SELECT`/`JOIN` with real data, then torn down):
the schema/data model itself ports cleanly to PostgreSQL. Making the
repository layer actually dual-backend is real, scoped follow-up work — see
ARCHITECTURE.md and DATA_PROVENANCE.md for exactly what would need to change.

## Windows deployment path

1. Install Python 3.14+ from python.org
2. `pip install -r requirements.txt` (downloads CPU PyTorch automatically via the plain `torch` entry — see requirements.txt comment if you need the explicit `--index-url` form used in the Dockerfile)
3. Set `AERIONX_JWT_SECRET` (PowerShell: `$env:AERIONX_JWT_SECRET = "..."`)
4. `uvicorn backend.main:app --host 127.0.0.1 --port 8000`
5. YOLOv8n/YOLOv8n-pose weights auto-download on first use (~6MB each, needs outbound internet once)
6. No camera-specific setup exists yet — no webcam adapter has been implemented or tested (see LIMITATIONS.md)

## Linux deployment path

Same as Windows from step 2 onward; step 1 is your distro's Python 3.11+ (this
project was developed/tested on 3.14 specifically, not older versions).
Platform-specific code is isolated to `platform.system()` checks in
`backend/main.py::get_compute_device()` — nothing in `core/` branches on OS.
Not actually run on Linux this session; "expected to work" is an architecture
claim, not a test result.

## Backup / restore

```bash
curl -X POST http://127.0.0.1:8000/admin/backup -H "Authorization: Bearer <admin token>"
# ... later, with the server STOPPED:
python -m scripts.restore_backup data/backups/aerionx_backup_<timestamp>.sqlite3
```

Real sqlite3 online-backup API (not a naive file copy), tested with actual
data destruction + restore + verification (`tests/test_backup_restore.py`).

## What's missing for a real production deployment

No process supervisor/restart policy beyond Docker's `restart: unless-stopped`,
no TLS termination configured, no log aggregation, no metrics/observability
beyond the structured stdout logging in `backend/main.py`. All in LIMITATIONS.md.
