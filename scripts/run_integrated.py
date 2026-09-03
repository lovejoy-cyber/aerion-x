"""AERION-X INTEGRATED PIPELINE — the full real chain in one run:

VIDEO -> YOLO DETECTION -> TRACKING -> TEMPORAL STATE -> ZONES
      -> WORKER SAFETY EVENTS -> AVIATION OPS EVENTS -> UNIFIED EVENT STREAM

Prints a periodic text dashboard (the "minimal integrated viewer" — this runs
headless/non-interactively, so the dashboard is the actual proof surface) and
writes a real annotated output video + sample frame images so the pipeline's
output can be inspected visually, not just read as event logs.

Everything printed comes from real pipeline state. If there are no events for
a given tick, it prints "NO ACTIVE EVENTS" rather than fabricating one.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from adapters.video.file_source import VideoFileSource
from core.contracts import Detection
from core.cv.detector import YoloDetector
from core.events.event_engine import EventEngine
from core.safety.aviation_ops import AviationOpsEngine, OperationsConfig
from core.safety.safety_engine import SafetyThresholds, WorkerSafetyEngine
from core.spatial.zones import Zone, ZoneRegistry
from core.temporal.state_engine import update_track_state
from core.tracking.tracker import CentroidIoUTracker


def draw_dashboard_overlay(image, detections, tracks_by_id, zones, model_name, source_label, fps, latency_ms, recent_events):
    y = 20
    for line in [
        f"SOURCE: {source_label}",
        f"MODEL: {model_name}   MODE: DETECTION + SAFETY + OPS",
        f"FPS: {fps:.1f}   LATENCY: {latency_ms:.0f} ms",
    ]:
        cv2.putText(image, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        y += 20

    for det in detections:
        x1, y1b, x2, y2b = [int(v) for v in det.bbox]
        track = tracks_by_id.get(det.track_id)
        color = (60, 220, 60) if det.class_name == "person" else (220, 180, 60)
        cv2.rectangle(image, (x1, y1b), (x2, y2b), color, 2)
        state = track.current_state if track else "?"
        cv2.putText(image, f"#{det.track_id} {det.class_name} {det.confidence:.2f} [{state}]",
                    (x1, max(0, y1b - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

    for zone in zones.zones.values():
        pts = [(int(x), int(y2)) for x, y2 in zone.polygon]
        for i in range(len(pts)):
            cv2.line(image, pts[i], pts[(i + 1) % len(pts)], (0, 200, 200), 1)
        cv2.putText(image, zone.name, pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 200), 1)

    box_y = image.shape[0] - 20 - 16 * max(1, min(len(recent_events), 6))
    cv2.putText(image, "EVENTS:" if recent_events else "NO ACTIVE EVENTS", (10, box_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    for i, ev in enumerate(recent_events[-6:]):
        cv2.putText(image, f"  {ev.event_type}", (10, box_y + 16 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)

    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="data/videos/vtest.avi")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--dashboard-every", type=int, default=30)
    parser.add_argument("--save-video", default="data/videos/vtest_annotated.webm")
    parser.add_argument("--sample-frames-dir", default="data/videos/samples")
    parser.add_argument("--sample-every", type=int, default=100)
    args = parser.parse_args()

    source = VideoFileSource(args.path)
    detector = YoloDetector()
    tracker = CentroidIoUTracker()

    zones = ZoneRegistry()
    zones.add(Zone("restricted_1", "RESTRICTED ZONE", [(400, 0), (768, 0), (768, 576), (400, 576)]))
    zones.add(Zone("safe_1", "SAFE AREA", [(0, 0), (400, 0), (400, 576), (0, 576)]))

    event_engine = EventEngine(zones, stationary_alert_seconds=3.0)
    worker_safety = WorkerSafetyEngine(zones, SafetyThresholds(
        proximity_px=120.0, crowding_count=3, immobility_seconds=5.0,
        restricted_zone_ids=("restricted_1",),
    ))
    ops_engine = AviationOpsEngine(zones, OperationsConfig(
        expected_classes_by_zone={"restricted_1": {"airplane", "truck"}},
        congestion_count=3, congestion_sustain_seconds=2.0,
    ))

    Path(args.sample_frames_dir).mkdir(parents=True, exist_ok=True)
    writer = None
    event_type_counts: dict[str, int] = {}
    recent_events = []
    frame_count = 0
    t_start = time.monotonic()

    for frame in source.frames():
        if args.max_frames and frame_count >= args.max_frames:
            break

        detections = detector.detect(frame)
        detections = tracker.update(detections, frame.frame_id, frame.timestamp)

        state_changed = {}
        for track in tracker.active_tracks():
            state_changed[track.track_id] = update_track_state(track, frame.timestamp)

        frame_events = []
        frame_events += event_engine.process(tracker.active_tracks(), source.source_id, frame.timestamp, state_changed)
        frame_events += worker_safety.process(tracker.active_tracks(), source.source_id, frame.timestamp)
        frame_events += ops_engine.process(tracker.active_tracks(), source.source_id, frame.timestamp)

        for ev in frame_events:
            event_type_counts[ev.event_type] = event_type_counts.get(ev.event_type, 0) + 1
            recent_events.append(ev)
        recent_events = recent_events[-6:]

        elapsed = time.monotonic() - t_start
        fps = frame_count / elapsed if elapsed > 0 else 0.0
        tracks_by_id = {t.track_id: t for t in tracker.active_tracks()}
        annotated = draw_dashboard_overlay(
            frame.image.copy(), detections, tracks_by_id, zones,
            detector.model_name, source.source_type.value, fps, detector.last_inference_ms, recent_events,
        )

        if writer is None:
            # VP8/WebM, not mp4v/H.264: this machine has no OpenH264 DLL or ffmpeg
            # binary, so an mp4v output plays nowhere useful (browsers reject
            # MPEG-4 Part 2) — VP8 is bundled with OpenCV's ffmpeg build and
            # actually plays. See LIMITATIONS.md.
            fourcc = cv2.VideoWriter_fourcc(*"VP80")
            writer = cv2.VideoWriter(args.save_video, fourcc, source.fps_hint() or 10.0,
                                      (annotated.shape[1], annotated.shape[0]))
        writer.write(annotated)

        if frame_count % args.sample_every == 0:
            cv2.imwrite(f"{args.sample_frames_dir}/frame_{frame.frame_id:04d}.png", annotated)

        if frame_count % args.dashboard_every == 0:
            print(f"\n=== t={frame.timestamp:.1f}s frame={frame.frame_id} ===")
            print(f"SOURCE: {source.source_type.value}   MODEL: {detector.model_name}")
            print(f"FPS: {fps:.1f}   LATENCY: {detector.last_inference_ms:.0f} ms")
            print(f"ACTIVE TRACKS: {len(tracker.active_tracks())}")
            if recent_events:
                for ev in recent_events:
                    print(f"  EVENT: {ev.event_type} tracks={ev.track_ids} zone={ev.zone_id} severity={ev.severity.value}")
            else:
                print("  NO ACTIVE EVENTS")

        frame_count += 1

    source.close()
    if writer:
        writer.release()

    print(f"\n--- INTEGRATED PIPELINE SUMMARY ---")
    print(f"Frames processed: {frame_count}")
    print(f"Annotated video saved: {args.save_video}")
    print(f"Sample frames saved to: {args.sample_frames_dir}/")
    print(f"Event counts by type:")
    for etype, count in sorted(event_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {etype}: {count}")


if __name__ == "__main__":
    main()
