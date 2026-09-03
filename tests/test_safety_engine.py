from core.contracts import Track, TrackPoint
from core.safety.aviation_ops import AviationOpsEngine, OperationsConfig
from core.safety.safety_engine import SafetyThresholds, WorkerSafetyEngine
from core.spatial.zones import Zone, ZoneRegistry


def make_track(track_id, object_class, x, y, w=40, h=100, state=None, state_since=None, timestamp=0.0):
    bbox = (x, y, x + w, y + h)
    center = (x + w / 2, y + h / 2)
    track = Track(track_id=track_id, object_class=object_class,
                  history=[TrackPoint(frame_id=0, timestamp=timestamp, bbox=bbox, center=center)])
    track.current_state = state
    track.state_since = state_since
    return track


def test_person_vehicle_proximity_fires_when_close():
    zones = ZoneRegistry()
    engine = WorkerSafetyEngine(zones, SafetyThresholds(proximity_px=100.0))
    person = make_track(1, "person", 100, 100)
    vehicle = make_track(2, "car", 130, 100)  # close
    events = engine.process([person, vehicle], "test", 0.0)
    assert any(e.event_type == "PERSON_VEHICLE_PROXIMITY" for e in events)


def test_person_vehicle_proximity_does_not_fire_when_far():
    zones = ZoneRegistry()
    engine = WorkerSafetyEngine(zones, SafetyThresholds(proximity_px=50.0))
    person = make_track(1, "person", 100, 100)
    vehicle = make_track(2, "car", 500, 500)
    events = engine.process([person, vehicle], "test", 0.0)
    assert not any(e.event_type == "PERSON_VEHICLE_PROXIMITY" for e in events)


def test_crowding_fires_at_threshold():
    zones = ZoneRegistry()
    zones.add(Zone("z1", "AREA", [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]))
    engine = WorkerSafetyEngine(zones, SafetyThresholds(crowding_count=3))
    people = [make_track(i, "person", i * 50, 100) for i in range(3)]
    events = engine.process(people, "test", 0.0)
    assert any(e.event_type == "CROWDING" for e in events)


def test_restricted_zone_entry_flags_only_configured_zone():
    zones = ZoneRegistry()
    zones.add(Zone("restricted", "RESTRICTED", [(0, 0), (200, 0), (200, 200), (0, 200)]))
    engine = WorkerSafetyEngine(zones, SafetyThresholds(restricted_zone_ids=("restricted",)))
    person = make_track(1, "person", 50, 50)
    events = engine.process([person], "test", 0.0)
    assert any(e.event_type == "PERSON_RESTRICTED_ZONE_ENTRY" and e.zone_id == "restricted" for e in events)


def test_prolonged_immobility_requires_duration_not_single_frame():
    zones = ZoneRegistry()
    engine = WorkerSafetyEngine(zones, SafetyThresholds(immobility_seconds=5.0))
    person = make_track(1, "person", 100, 100, state="STATIONARY", state_since=0.0, timestamp=1.0)
    events_early = engine.process([person], "test", 1.0)
    assert not any(e.event_type == "PROLONGED_IMMOBILITY" for e in events_early)

    person.history[-1].timestamp = 6.0
    events_late = engine.process([person], "test", 6.0)
    assert any(e.event_type == "PROLONGED_IMMOBILITY" for e in events_late)


def test_fall_like_motion_detects_sharp_aspect_ratio_drop():
    zones = ZoneRegistry()
    engine = WorkerSafetyEngine(zones)
    tall = make_track(1, "person", 100, 100, w=30, h=120, timestamp=0.0)
    engine.process([tall], "test", 0.0)

    wide = make_track(1, "person", 100, 180, w=100, h=40, timestamp=0.3)  # sudden short+wide bbox
    events = engine.process([wide], "test", 0.3)
    assert any(e.event_type == "FALL_LIKE_MOTION" for e in events)


def test_area_occupancy_reports_real_counts_and_classes():
    zones = ZoneRegistry()
    zones.add(Zone("z1", "AREA", [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]))
    engine = AviationOpsEngine(zones)
    tracks = [make_track(1, "person", 100, 100), make_track(2, "car", 200, 100)]
    events = engine.process(tracks, "test", 0.0)
    occupancy = [e for e in events if e.event_type == "AREA_OCCUPANCY"]
    assert occupancy
    assert occupancy[0].evidence["count"] == 2
    assert set(occupancy[0].evidence["classes"]) == {"person", "car"}


def test_unexpected_object_only_fires_with_allowlist_configured():
    zones = ZoneRegistry()
    zones.add(Zone("z1", "EQUIPMENT AREA", [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]))
    config = OperationsConfig(expected_classes_by_zone={"z1": {"truck", "airplane"}})
    engine = AviationOpsEngine(zones, config)
    tracks = [make_track(1, "person", 100, 100)]
    events = engine.process(tracks, "test", 0.0)
    assert any(e.event_type == "UNEXPECTED_OBJECT" and e.evidence["class"] == "person" for e in events)


def test_restricted_zone_entry_does_not_spam_every_frame_while_present():
    """Regression test for a real bug found running the integrated pipeline on
    vtest.avi: PERSON_RESTRICTED_ZONE_ENTRY fired 3,367 times over 795 frames
    because it re-fired every frame instead of only on transition into the zone."""
    zones = ZoneRegistry()
    zones.add(Zone("restricted", "RESTRICTED", [(0, 0), (200, 0), (200, 200), (0, 200)]))
    engine = WorkerSafetyEngine(zones, SafetyThresholds(restricted_zone_ids=("restricted",)))
    person = make_track(1, "person", 50, 50)

    fire_count = 0
    for t in range(10):
        events = engine.process([person], "test", float(t))
        fire_count += sum(1 for e in events if e.event_type == "PERSON_RESTRICTED_ZONE_ENTRY")

    assert fire_count == 1, f"expected exactly one entry event across 10 frames of continuous presence, got {fire_count}"


def test_congestion_requires_sustained_duration_not_single_frame():
    zones = ZoneRegistry()
    zones.add(Zone("z1", "AREA", [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]))
    engine = AviationOpsEngine(zones, OperationsConfig(congestion_count=2, congestion_sustain_seconds=2.0))
    tracks = [make_track(1, "person", 100, 100), make_track(2, "person", 200, 100)]

    events_t0 = engine.process(tracks, "test", 0.0)
    assert not any(e.event_type == "CONGESTION" for e in events_t0)

    events_t3 = engine.process(tracks, "test", 3.0)
    assert any(e.event_type == "CONGESTION" for e in events_t3)
