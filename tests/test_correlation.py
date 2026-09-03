from core.contracts import Event
from core.correlation.correlation_engine import CorrelationEngine


def make_event(event_type, source_id, timestamp, provenance="REAL"):
    return Event(event_type=event_type, timestamp=timestamp, source_id=source_id, provenance=provenance)


def test_correlates_events_from_different_sources_within_window():
    engine = CorrelationEngine(window_seconds=2.0)
    events = [
        make_event("ZONE_ENTER", "video:test.mp4", 10.0, provenance="REAL"),
        make_event("ANOMALY", "sensor:vibration", 11.0, provenance="SYNTHETIC"),
    ]
    correlations = engine.correlate(events)
    assert len(correlations) == 1
    assert correlations[0].event_types == {"ZONE_ENTER", "ANOMALY"}
    assert correlations[0].provenance_note == "MIXED: REAL,SYNTHETIC"


def test_does_not_correlate_events_outside_window():
    engine = CorrelationEngine(window_seconds=1.0)
    events = [
        make_event("ZONE_ENTER", "video:test.mp4", 10.0),
        make_event("ANOMALY", "sensor:vibration", 50.0),
    ]
    correlations = engine.correlate(events)
    assert len(correlations) == 0


def test_does_not_correlate_events_from_the_same_source():
    engine = CorrelationEngine(window_seconds=5.0)
    events = [
        make_event("ZONE_ENTER", "video:test.mp4", 10.0),
        make_event("ZONE_EXIT", "video:test.mp4", 10.5),
    ]
    correlations = engine.correlate(events)
    assert len(correlations) == 0


def test_correlation_never_claims_causation_only_coincidence():
    engine = CorrelationEngine(window_seconds=2.0)
    events = [
        make_event("PERSON_VEHICLE_PROXIMITY", "video:test.mp4", 5.0),
        make_event("ANOMALY", "sensor:vibration", 5.5, provenance="SYNTHETIC"),
    ]
    correlations = engine.correlate(events)
    assert len(correlations) == 1
    # the correlated event carries the raw events + a provenance note; it does
    # not carry any "caused_by" or "confidence_of_causation" field
    assert not hasattr(correlations[0], "caused_by")
