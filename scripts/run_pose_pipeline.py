"""AERION-X pose pipeline: PERSON DETECTION+POSE -> TRACKING -> TEMPORAL STATE -> EVENTS.

Uses YOLOv8n-pose directly (it detects persons AND keypoints in one pass), feeds
the person bounding boxes into the same tracker/temporal/event engine used by
the plain detection pipeline. Keypoints are attached to each frame's output for
inspection but do not themselves drive state — state still comes from the
temporal motion-history engine (core/temporal/state_engine.py), consistent with
the "never classify from a single frame" rule.
"""
from __future__ import annotations

import argparse
import time

from adapters.synthetic.synthetic_source import SyntheticSource
from adapters.video.file_source import VideoFileSource
from core.contracts import Detection
from core.cv.pose import YoloPoseEstimator
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["synthetic", "video"], default="video")
    parser.add_argument("--path", default=None)
    parser.add_argument("--frames", type=int, default=150)
    parser.add_argument("--max-frames", type=int, default=None, help="stop after N frames of the source (for quick tests)")
    parser.add_argument("--zone", action="store_true")
    args = parser.parse_args()

    source = build_source(args)
    pose_estimator = YoloPoseEstimator()
    tracker = CentroidIoUTracker()
    zones = ZoneRegistry()
    if args.zone:
        zones.add(Zone("zone_1", "RESTRICTED ZONE", [(400, 0), (768, 0), (768, 576), (400, 576)]))
    events_engine = EventEngine(zones, stationary_alert_seconds=3.0)

    frame_count = 0
    total_people_seen = 0
    total_inference_ms = 0.0
    total_events = []
    t_start = time.monotonic()

    for frame in source.frames():
        if args.max_frames and frame_count >= args.max_frames:
            break

        people = pose_estimator.estimate(frame)
        total_inference_ms += pose_estimator.last_inference_ms
        total_people_seen += len(people)

        detections = [
            Detection(
                class_name="person",
                confidence=p["confidence"],
                bbox=p["bbox"],
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                model_name=p["model_name"],
            )
            for p in people
        ]
        detections = tracker.update(detections, frame.frame_id, frame.timestamp)

        state_changed = {}
        for track in tracker.active_tracks():
            state_changed[track.track_id] = update_track_state(track, frame.timestamp)

        new_events = events_engine.process(tracker.active_tracks(), source.source_id, frame.timestamp, state_changed)
        for ev in new_events:
            total_events.append(ev)
            print(f"[EVENT] t={ev.timestamp:.2f}s {ev.event_type} tracks={ev.track_ids} zone={ev.zone_id} evidence={ev.evidence}")

        frame_count += 1

    source.close()
    elapsed = time.monotonic() - t_start
    avg_inference = total_inference_ms / frame_count if frame_count else 0.0

    print("\n--- POSE PIPELINE SUMMARY ---")
    print(f"Frames processed: {frame_count}")
    print(f"Total person detections (all frames): {total_people_seen}")
    print(f"Unique tracks created: {tracker._next_id - 1}")
    print(f"Total events: {len(total_events)}")
    print(f"Avg pose inference latency: {avg_inference:.1f} ms/frame")
    print(f"Wall-clock FPS: {frame_count / elapsed:.2f}" if elapsed > 0 else "Wall-clock FPS: n/a")
    print("Final states:")
    for track in tracker.tracks.values():
        print(f"  track#{track.track_id} class={track.object_class} final_state={track.current_state} points={len(track.history)}")


if __name__ == "__main__":
    main()
