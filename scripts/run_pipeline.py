"""AERION-X CORE pipeline runner.

CAMERA/VIDEO/SYNTHETIC -> DETECTION -> TRACKING -> TEMPORAL STATE -> ZONES -> EVENTS

Renders an annotated video window and prints every real event as it fires.
Run with --source synthetic to test with zero external files, or
--source video --path <file.mp4> for a real video file.
"""
from __future__ import annotations

import argparse
import time

import cv2

from adapters.synthetic.synthetic_source import SyntheticSource
from adapters.video.file_source import VideoFileSource
from core.cv.detector import YoloDetector
from core.events.event_engine import EventEngine
from core.spatial.zones import Zone, ZoneRegistry
from core.temporal.state_engine import StateThresholds, update_track_state
from core.tracking.tracker import CentroidIoUTracker


def build_source(args):
    if args.source == "synthetic":
        return SyntheticSource(num_frames=args.frames)
    if args.source == "video":
        if not args.path:
            raise SystemExit("--path is required when --source video")
        return VideoFileSource(args.path)
    raise SystemExit(f"Unknown source: {args.source}")


def draw_overlay(image, detections, tracks_by_id, zones, fps, inference_ms, source_label):
    for zone in zones.zones.values():
        pts = [(int(x), int(y)) for x, y in zone.polygon]
        for i in range(len(pts)):
            cv2.line(image, pts[i], pts[(i + 1) % len(pts)], (0, 200, 200), 1)
        cv2.putText(image, zone.name, pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 200), 1)

    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.bbox]
        cv2.rectangle(image, (x1, y1), (x2, y2), (60, 220, 60), 2)
        track = tracks_by_id.get(det.track_id)
        state = track.current_state if track else "?"
        label = f"#{det.track_id} {det.class_name} {det.confidence:.2f} [{state}]"
        cv2.putText(image, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 220, 60), 1)

    cv2.putText(image, f"SOURCE: {source_label}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(image, f"FPS: {fps:.1f}  Inference: {inference_ms:.1f}ms", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(image, f"Detections: {len(detections)}" if detections else "0 DETECTIONS", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["synthetic", "video"], default="synthetic")
    parser.add_argument("--path", default=None)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument("--zone", action="store_true", help="add a demo zone covering the right half of the frame")
    args = parser.parse_args()

    source = build_source(args)
    detector = YoloDetector()
    tracker = CentroidIoUTracker()
    zones = ZoneRegistry()
    if args.zone:
        zones.add(Zone("zone_1", "RESTRICTED ZONE", [(400, 0), (640, 0), (640, 480), (400, 480)]))
    events_engine = EventEngine(zones, stationary_alert_seconds=3.0)

    frame_count = 0
    total_detections = 0
    inference_ms_samples: list[float] = []
    frame_ms_samples: list[float] = []
    t_start = time.monotonic()
    total_events = []

    for frame in source.frames():
        frame_t0 = time.perf_counter()
        detections = detector.detect(frame)
        total_detections += len(detections)
        inference_ms_samples.append(detector.last_inference_ms)
        detections = tracker.update(detections, frame.frame_id, frame.timestamp)

        state_changed = {}
        for track in tracker.active_tracks():
            state_changed[track.track_id] = update_track_state(track, frame.timestamp)

        new_events = events_engine.process(tracker.active_tracks(), source.source_id, frame.timestamp, state_changed)
        for ev in new_events:
            total_events.append(ev)
            print(f"[EVENT] t={ev.timestamp:.2f}s {ev.event_type} tracks={ev.track_ids} zone={ev.zone_id} evidence={ev.evidence}")

        frame_count += 1
        frame_ms_samples.append((time.perf_counter() - frame_t0) * 1000.0)
        elapsed = time.monotonic() - t_start
        fps = frame_count / elapsed if elapsed > 0 else 0.0

        if not args.no_display:
            tracks_by_id = {t.track_id: t for t in tracker.active_tracks()}
            annotated = draw_overlay(frame.image.copy(), detections, tracks_by_id, zones, fps, detector.last_inference_ms, source.source_type.value)
            cv2.imshow("AERION-X CORE", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    source.close()
    if not args.no_display:
        cv2.destroyAllWindows()

    total_elapsed = time.monotonic() - t_start
    avg_inference = sum(inference_ms_samples) / len(inference_ms_samples) if inference_ms_samples else 0.0
    max_inference = max(inference_ms_samples) if inference_ms_samples else 0.0
    avg_frame_ms = sum(frame_ms_samples) / len(frame_ms_samples) if frame_ms_samples else 0.0
    overall_fps = frame_count / total_elapsed if total_elapsed > 0 else 0.0

    print(f"\n--- SUMMARY (measured, not estimated) ---")
    print(f"Source: {source.source_type.value}")
    print(f"Frames processed: {frame_count}")
    print(f"Total detections (all frames): {total_detections}")
    print(f"Total events: {len(total_events)}")
    print(f"Tracks created: {tracker._next_id - 1}")
    print(f"Wall-clock elapsed: {total_elapsed:.2f}s")
    print(f"Overall FPS: {overall_fps:.2f}")
    print(f"Avg model inference latency: {avg_inference:.1f} ms/frame  (max: {max_inference:.1f} ms)")
    print(f"Avg total per-frame latency (inference+tracking+temporal+zones+events): {avg_frame_ms:.1f} ms")
    try:
        import psutil
        proc = psutil.Process()
        print(f"Process memory (RSS): {proc.memory_info().rss / (1024*1024):.1f} MB")
        print(f"Process CPU%: {proc.cpu_percent(interval=0.5):.1f}%")
    except ImportError:
        print("Process memory/CPU: not measured (psutil not installed)")
    import torch
    print(f"GPU available: {torch.cuda.is_available()}  (this run used CPU-only inference)")


if __name__ == "__main__":
    main()
