# AERION-X — Security

## Authentication

PBKDF2-HMAC-SHA256 password hashing (600,000 iterations, OWASP 2023 minimum),
random per-user salt, no plaintext password ever stored or logged. JWT
session tokens (HS256, 8-hour expiry). First registered user on a fresh
database becomes ADMIN (bootstrap); every registration after that is OPERATOR
by default — there is no open path to self-assign ADMIN or ENGINEER.

**`AERIONX_JWT_SECRET`**: if unset, a random secret is generated per process
start (a warning is logged). This means every session is invalidated on
restart unless you set this env var explicitly. Never commit a real secret to
version control; set it via your deployment's secret mechanism (Docker Compose
env, systemd EnvironmentFile, etc.) — `docker-compose.yml` in this repo
refuses to start without it (`${AERIONX_JWT_SECRET:?...}`).

## Optional site-wide passphrase gate

Set `AERIONX_SITE_PASSPHRASE` to require a single shared passphrase before
*anything* is reachable — including the GET endpoints that are otherwise
open. Meant for sharing a public link with non-technical people (a friend,
a professor) who just need "the password," not a real account: unset by
default (zero behavior change), and separate from the real per-user login
system, which still governs who can start pipelines/create data once past
the gate. Implemented as `backend/main.py::_site_gate` — a cookie set via
`POST /gate`, checked on every request with `hmac.compare_digest`.

## Rate limiting (added — quick pass, not comprehensive)

`/auth/login` (30/min) and `/auth/register` (20/min) are rate-limited per
client IP via a simple in-memory sliding window (`backend/main.py::rate_limit`)
— no new dependency, resets on restart, single-process only. This blocks the
attack that actually matters most (credential brute-forcing) without the time
cost of a general-purpose rate limiter across every endpoint. `AERIONX_CORS_ORIGINS`
now scopes CORS to explicit origins (defaults to `127.0.0.1:8000`/`localhost:8000`)
instead of `*`.

## Authorization scope (a real, documented tradeoff — not hidden)

Every `GET` (read) endpoint is currently **unauthenticated** — this is a
local, single-deployment monitoring tool, and read access was left open to
avoid rewriting every read-path test in this pass. Every `POST` (state-changing)
endpoint requires a valid bearer token; a subset require a specific role:

| Action | Minimum role |
|---|---|
| Start/stop pipeline, compute correlations, run optical flow | any authenticated user (OPERATOR+) |
| Create asset, run inspection, generate synthetic sensor data | ENGINEER+ |
| Register a model, view the audit log, create/restore a backup | ADMIN |

If you need read endpoints locked down too, that's a small, mechanical change
(add `Depends(get_current_user)` to each) — not done here because it would
have required touching ~30 existing test call sites for a local tool where the
read/write split above was judged sufficient.

## WebSocket authentication

`/ws/pipeline` requires `?token=<jwt>` as a query parameter (browsers can't
set custom headers on the WebSocket handshake) and is rejected with close code
1008 before `accept()` if the token is missing or invalid — an unauthenticated
client never reaches an open connection state.

## Input validation / path traversal

`/pipeline/start`, `/inspections/run`, and `/flow/demo` all accept a
user-supplied file path. `backend/main.py::safe_data_path()` resolves the path
and rejects anything that escapes `data/` — confirmed with a real test
(`test_pipeline_path_traversal_is_rejected`) using `../../../../etc/passwd`.

## Error handling

A global exception handler (`backend/main.py::_unhandled_exception_handler`)
catches any unhandled exception, logs the real traceback server-side, and
returns a generic `{"detail": "Internal server error"}` to the client — no
stack trace, file path, or internal detail is ever returned in a 500 response.

## What was NOT implemented (real limitations, not hidden)

- **No rate limiting.** A local single-user tool doesn't currently need it;
  a real multi-tenant deployment would.
- **No CSRF protection** — irrelevant for a bearer-token API consumed by a
  same-origin SPA, but would matter if a cookie-based session were added later.
- **CORS is wide open** (`allow_origins=["*"]`) — appropriate for local dev,
  wrong for any deployment reachable from untrusted origins. Tighten this in
  `backend/main.py` before deploying anywhere but localhost.
- **No file-upload endpoints exist yet**, so file-upload-specific validation
  (size limits, content-type sniffing) hasn't been needed or built.
- **Camera/privacy**: no live camera has been tested (no hardware). If/when a
  webcam adapter is added, consider: what's retained (raw frames vs. only
  detections), for how long, and whether faces are ever stored — this project
  explicitly does not implement facial recognition or any biometric inference,
  and none should be added without a real privacy review.

## Audit log

Every login, pipeline start/stop, asset/inspection/model creation, backup, and
authorization denial is recorded in the `audit_log` table with timestamp,
username, action, object, and result — visible via `GET /audit-log`
(ADMIN-only). No secrets (passwords, tokens) are ever written to it.
