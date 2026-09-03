"""Tests for tracking, temporal state, zones, and events using deterministic
synthetic detections — no model inference required, so these run fast and
reproducibly to validate the logic layers independently of YOLO.
"""
from core.contracts import Detection
from core.events.event_engine import EventEngine
from core.spatial.zones import Zone, ZoneRegistry
from core.temporal.state_engine import StateThresholds, update_track_state
from core.tracking.tracker import CentroidIoUTracker


def make_detection(x, class_name="person", frame_id=0, timestamp=0.0):
    return Detection(
        class_name=class_name,
        confidence=0.9,
        bbox=(x, 100, x + 50, 250),
        frame_id=frame_id,
        timestamp=timestamp,
        model_name="test",
    )


def test_tracker_assigns_stable_id_across_frames():
    tracker = CentroidIoUTracker()
    d1 = tracker.update([make_detection(100, frame_id=0, timestamp=0.0)], 0, 0.0)
    d2 = tracker.update([make_detection(105, frame_id=1, timestamp=0.033)], 1, 0.033)
    assert d1[0].track_id == d2[0].track_id


def test_tracker_ages_out_lost_track():
    tracker = CentroidIoUTracker(max_missed_frames=2)
    tracker.update([make_detection(100, frame_id=0, timestamp=0.0)], 0, 0.0)
    for i in range(1, 5):
        tracker.update([], i, i * 0.033)
    assert len(tracker.active_tracks()) == 0


def test_stationary_state_requires_temporal_window_not_one_frame():
    tracker = CentroidIoUTracker()
    thresholds = StateThresholds(window=4)
    for i in range(6):
        tracker.update([make_detection(100, frame_id=i, timestamp=i * 0.1)], i, i * 0.1)
    track = tracker.active_tracks()[0]
    changed = update_track_state(track, track.history[-1].timestamp, thresholds)
    assert track.current_state == "STATIONARY"


def test_moving_target_classified_as_moving():
    tracker = CentroidIoUTracker(iou_threshold=0.0)
    thresholds = StateThresholds(window=4)
    for i in range(6):
        tracker.update([make_detection(100 + i * 40, frame_id=i, timestamp=i * 0.1)], i, i * 0.1)
    track = tracker.active_tracks()[0]
    update_track_state(track, track.history[-1].timestamp, thresholds)
    assert track.current_state == "MOVING"


def test_zone_enter_and_exit_events_fire():
    """A person walks from outside a zone, through it, and back out again —
    modeled as realistic incremental motion (60px/frame, a box-width-sized
    step) rather than a teleport, since the tracker legitimately treats a
    jump far larger than a plausible per-frame displacement as a new object.
    """
    zones = ZoneRegistry()
    zones.add(Zone("z1", "TEST ZONE", [(400, 0), (640, 0), (640, 480), (400, 480)]))
    engine = EventEngine(zones)
    tracker = CentroidIoUTracker()

    walk_in = [100, 160, 220, 280, 340, 400, 460, 520]
    walk_out = [460, 400, 340, 280, 220, 160, 100]
    xs = walk_in + walk_out

    all_events = []
    for i, x in enumerate(xs):
        t = i * 0.1
        tracker.update([make_detection(x, frame_id=i, timestamp=t)], i, t)
        all_events.extend(engine.process(tracker.active_tracks(), "test", t, {}))

    track_ids_seen = {tid for ev in all_events for tid in ev.track_ids}
    assert track_ids_seen == {1}, f"expected one continuous track, got {track_ids_seen}"

    assert any(e.event_type == "OBJECT_APPEARED" for e in all_events)
    assert any(e.event_type == "ZONE_ENTER" and e.zone_id == "z1" for e in all_events)
    assert any(e.event_type == "ZONE_EXIT" and e.zone_id == "z1" for e in all_events)


def test_prolonged_stationary_fires_only_after_threshold():
    zones = ZoneRegistry()
    engine = EventEngine(zones, stationary_alert_seconds=1.0)
    tracker = CentroidIoUTracker()
    thresholds = StateThresholds(window=4)

    fired_early = False
    for i in range(20):
        t = i * 0.1
        tracker.update([make_detection(100, frame_id=i, timestamp=t)], i, t)
        track = tracker.active_tracks()[0]
        changed = update_track_state(track, t, thresholds)
        events = engine.process(tracker.active_tracks(), "test", t, {track.track_id: changed})
        if t < 1.0 and any(e.event_type == "PROLONGED_STATIONARY" for e in events):
            fired_early = True

    assert not fired_early
    final_track = tracker.active_tracks()[0]
    assert final_track.current_state == "STATIONARY"
