"""Higher-level observable safety events, built entirely on the already-proven
primitives: real tracks (position, class, velocity), real temporal state
(STATIONARY/WALKING/MOVING duration), and real zones. No new models — this is
reasoning over evidence the core pipeline already produces.

Explicitly out of scope, per project rule: fatigue, illness, intoxication, or
any psychological/medical inference. Every event here describes an observable
geometric/temporal fact (distance, duration, zone membership, motion pattern).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.contracts import Event, Severity, Track
from core.spatial.zones import ZoneRegistry

VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "train"}
PERSON_CLASS = "person"


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


@dataclass
class SafetyThresholds:
    proximity_px: float = 100.0          # person-vehicle distance considered "too close" in pixel space
    crowding_count: int = 3              # people in one zone considered crowding
    immobility_seconds: float = 8.0      # STATIONARY duration considered "prolonged"
    fall_aspect_ratio_drop: float = 0.5  # bbox height/width ratio drop fraction considered fall-like
    fall_window_seconds: float = 1.0     # how fast that drop must happen to count as fall-like, not just sitting down slowly
    restricted_zone_ids: tuple[str, ...] = ()


class WorkerSafetyEngine:
    """Stateful — call `process` once per frame with the current active tracks.
    Tracks internal state (e.g. which fall-like events already fired) so it
    doesn't re-fire the same condition every single frame it remains true."""

    def __init__(self, zones: ZoneRegistry, thresholds: SafetyThresholds = SafetyThresholds()):
        self.zones = zones
        self.thresholds = thresholds
        self._fired_immobility: set[int] = set()
        self._fired_fall: set[int] = set()
        self._bbox_history: dict[int, list[tuple[float, tuple, float]]] = {}  # track_id -> [(t, bbox, aspect)]
        # Per-condition "currently active" keys, so onset-style events (proximity,
        # crowding, restricted-zone entry) fire once on transition-to-true instead
        # of every frame the condition continues to hold — discovered as a real
        # bug (thousands of duplicate events on a 795-frame test run) rather than
        # designed in from the start.
        self._active: dict[str, set] = {}

    def _on_transition(self, condition: str, currently_active: set, event_builder) -> list[Event]:
        prev = self._active.get(condition, set())
        newly_active = currently_active - prev
        self._active[condition] = currently_active
        return [event_builder(key) for key in newly_active]

    def _aspect_ratio(self, bbox: tuple[float, float, float, float]) -> float:
        x1, y1, x2, y2 = bbox
        w, h = max(1.0, x2 - x1), max(1.0, y2 - y1)
        return h / w

    def process(self, tracks: list[Track], source_id: str, timestamp: float) -> list[Event]:
        events: list[Event] = []
        people = [t for t in tracks if t.object_class == PERSON_CLASS and t.current_position]
        vehicles = [t for t in tracks if t.object_class in VEHICLE_CLASSES and t.current_position]

        # PERSON_VEHICLE_PROXIMITY — fires once when a given (person, vehicle) pair
        # first comes within threshold, not every frame they remain close.
        close_pairs = {}
        for person in people:
            for vehicle in vehicles:
                d = _distance(person.current_position, vehicle.current_position)
                if d < self.thresholds.proximity_px:
                    close_pairs[(person.track_id, vehicle.track_id)] = d
        events += self._on_transition(
            "proximity", set(close_pairs.keys()),
            lambda pair: Event(
                event_type="PERSON_VEHICLE_PROXIMITY", timestamp=timestamp, source_id=source_id,
                track_ids=list(pair), severity=Severity.WARNING,
                evidence={"distance_px": close_pairs[pair], "threshold_px": self.thresholds.proximity_px},
            ),
        )

        # CROWDING — fires once when a zone's occupant count crosses the threshold,
        # not every frame it stays crowded.
        by_zone: dict[str, list[Track]] = {}
        for person in people:
            zone_id = self.zones.zone_for_point(person.current_position)
            if zone_id:
                by_zone.setdefault(zone_id, []).append(person)
        crowded_zones = {zid: occ for zid, occ in by_zone.items() if len(occ) >= self.thresholds.crowding_count}
        events += self._on_transition(
            "crowding", set(crowded_zones.keys()),
            lambda zid: Event(
                event_type="CROWDING", timestamp=timestamp, source_id=source_id,
                track_ids=[t.track_id for t in crowded_zones[zid]], zone_id=zid, severity=Severity.WARNING,
                evidence={"occupant_count": len(crowded_zones[zid]), "threshold": self.thresholds.crowding_count},
            ),
        )

        # RESTRICTED_ZONE_ENTRY — fires once on entry, not every frame occupied.
        people_in_restricted = {}
        for person in people:
            zone_id = self.zones.zone_for_point(person.current_position)
            if zone_id in self.thresholds.restricted_zone_ids:
                people_in_restricted[person.track_id] = (zone_id, person.current_position)
        events += self._on_transition(
            "person_restricted", set(people_in_restricted.keys()),
            lambda tid: Event(
                event_type="PERSON_RESTRICTED_ZONE_ENTRY", timestamp=timestamp, source_id=source_id,
                track_ids=[tid], zone_id=people_in_restricted[tid][0], severity=Severity.CRITICAL,
                evidence={"position": people_in_restricted[tid][1]},
            ),
        )

        vehicles_in_restricted = {}
        for vehicle in vehicles:
            zone_id = self.zones.zone_for_point(vehicle.current_position)
            if zone_id in self.thresholds.restricted_zone_ids:
                vehicles_in_restricted[vehicle.track_id] = (zone_id, vehicle.current_position)
        events += self._on_transition(
            "vehicle_restricted", set(vehicles_in_restricted.keys()),
            lambda tid: Event(
                event_type="VEHICLE_RESTRICTED_ZONE_ENTRY", timestamp=timestamp, source_id=source_id,
                track_ids=[tid], zone_id=vehicles_in_restricted[tid][0], severity=Severity.CRITICAL,
                evidence={"position": vehicles_in_restricted[tid][1]},
            ),
        )

        # PROLONGED_IMMOBILITY (distinct name from PROLONGED_STATIONARY in event_engine —
        # this is the safety-severity-tagged version with a configurable, typically longer threshold)
        for person in people:
            if (person.current_state in ("STATIONARY",) and person.duration_in_state is not None
                    and person.duration_in_state >= self.thresholds.immobility_seconds
                    and person.track_id not in self._fired_immobility):
                events.append(Event(
                    event_type="PROLONGED_IMMOBILITY",
                    timestamp=timestamp,
                    source_id=source_id,
                    track_ids=[person.track_id],
                    severity=Severity.WARNING,
                    duration=person.duration_in_state,
                    evidence={"duration_seconds": person.duration_in_state},
                ))
                self._fired_immobility.add(person.track_id)
            elif person.current_state != "STATIONARY":
                self._fired_immobility.discard(person.track_id)

        # FALL_LIKE_MOTION — bbox aspect ratio (height/width) drops sharply and quickly.
        # A real person falling goes from "tall and narrow" to "short and wide" bbox
        # within a short time window. This is a geometric heuristic on real bbox data,
        # not a learned fall-detection model — reported as observable pattern only.
        for person in people:
            hist = self._bbox_history.setdefault(person.track_id, [])
            bbox = person.history[-1].bbox
            aspect = self._aspect_ratio(bbox)
            hist.append((timestamp, bbox, aspect))
            cutoff = timestamp - self.thresholds.fall_window_seconds
            hist[:] = [h for h in hist if h[0] >= cutoff]
            if len(hist) >= 2:
                max_aspect = max(h[2] for h in hist)
                if max_aspect > 0 and (max_aspect - aspect) / max_aspect >= self.thresholds.fall_aspect_ratio_drop:
                    if person.track_id not in self._fired_fall:
                        events.append(Event(
                            event_type="FALL_LIKE_MOTION",
                            timestamp=timestamp,
                            source_id=source_id,
                            track_ids=[person.track_id],
                            severity=Severity.CRITICAL,
                            evidence={"aspect_ratio_before": max_aspect, "aspect_ratio_now": aspect,
                                      "window_seconds": self.thresholds.fall_window_seconds,
                                      "note": "geometric bbox heuristic, not a medical/fall-classification model"},
                        ))
                        self._fired_fall.add(person.track_id)
                else:
                    self._fired_fall.discard(person.track_id)

        return events
