# AERION-X — Mobile / Field Client Architecture

**Update**: the "capture an image and analyze it" gap this doc originally
described has been closed. `POST /capture/analyze` + the "Field Capture" GUI
tab (browser camera access via `getUserMedia`, or a file-upload fallback) are
real, tested (`test_capture_analyze_runs_real_detection_on_uploaded_photo`),
and verified in a live browser end-to-end: real photo → real YOLO detection
→ real results rendered. No native app — this works from any phone's browser
on the same network, which is what "web app that uses the phone's camera"
actually means (no App Store, no native SDK required).

**Still not built**: no native Android/iOS app, no offline capture-and-sync,
no dedicated mobile-responsive CSS pass on the rest of the GUI (Field Capture
itself is usable on a small screen; Command Center/Event Intelligence/etc.
were designed for desktop and haven't been tested on a phone screen).

**A real constraint worth knowing now**: `getUserMedia` (camera access)
only works in a "secure context" — `https://`, or `http://localhost` /
`http://127.0.0.1`. If you open AERION-X from a phone at
`http://<your-pc's-LAN-IP>:8000`, the browser will refuse camera access
(this is enforced by the browser itself, not something this project can
bypass) — the file-upload fallback still works over plain HTTP, but live
camera capture needs either HTTPS or a same-machine `localhost` origin.
Practical fix: put a reverse proxy with a real TLS cert in front of it (e.g.
Caddy, which auto-provisions certs), or tunnel with something like ngrok/Tailscale
Funnel for testing — neither is set up in this project.

---

This document originally described a not-yet-built interface; the sections
below still apply to what remains unbuilt (live streaming, native apps).

```
PHONE CAMERA
    |
    v
[future mobile client — NOT BUILT]
    |
    v  HTTPS (same REST/WebSocket API this repo already serves)
    v
AERION-X SERVER (backend/main.py — already real, already tested)
    |
    v
core/ intelligence pipeline (already real, already tested)
    |
    v
RESULTS -> back to phone via the same REST responses / WebSocket messages
```

## What a field-inspection client would actually call (all already real)

1. **Capture + upload a photo for detection**: DONE. `POST /capture/analyze`
   accepts a real uploaded image (`multipart/form-data`, `UploadFile`), runs
   the real YOLO detector on it, returns real detections — file-size (10MB)
   and content-type validation included. `POST /inspections/run` (the
   before/after SSIM comparison workflow) still only takes a server-side
   `video_path`, not two uploaded images — extending it to accept an
   uploaded reference + current photo pair is the same small pattern, just
   not done yet.
2. **Live detections from a phone camera stream**: would require either (a) a
   new `RTSPSource`/`MobileStreamSource` implementing `adapters.base.FrameSource`
   (the interface exists; no implementation does), receiving frames over a
   websocket/HTTP stream from the phone, or (b) the phone periodically POSTing
   individual frames to a new endpoint. Neither transport is implemented.
3. **Receiving events/detections**: `GET /events`, `GET /inspections`, and
   `/ws/pipeline` already return exactly the data a mobile client would need
   to display — this half of the interface is real today, just never called
   from anything but the web GUI.
4. **Auth**: `POST /auth/login` already returns a JWT usable by any HTTP
   client, mobile or not — no mobile-specific auth work would be needed.

## Honest summary

The backend's API shape is mobile-ready for *read* operations (events,
inspections, assets, sensor data), for authentication, and now for *capture*
too — `POST /capture/analyze` + the Field Capture GUI tab work over a
browser, no native app. What's genuinely unverified: this has **not** been
tested from an actual physical phone (only from a desktop browser, with a
real image fed through the same JS function a phone's camera capture would
call) — the HTTPS/secure-context constraint above is a real, known limitation
of that path, documented rather than hidden. No native Android/iOS client
exists or was attempted.
