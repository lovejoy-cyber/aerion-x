"""Aviation/ground-operations event layer — same real tracks/zones as
worker_safety, generalized to any tracked class (not just person/vehicle).

Honest limitation: COCO (what YOLOv8n was trained on) has no classes for
aircraft ground-support equipment (tugs, jetways, GPUs) and only "airplane"
for aircraft. This module treats COCO's "airplane" as the aircraft class and
documents the gap rather than inventing detections COCO can't produce — a
real ground-ops deployment would need a custom-trained model here.

This is monitoring / decision support, not autonomous safety certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.contracts import Event, Severity, Track
from core.spatial.zones import ZoneRegistry

AIRCRAFT_CLASSES = {"airplane"}  # COCO's only aircraft-adjacent class


@dataclass
class OperationsConfig:
    expected_classes_by_zone: dict[str, set[str]] = field(default_factory=dict)
    congestion_count: int = 4
    congestion_sustain_seconds: float = 3.0


class AviationOpsEngine:
    def __init__(self, zones: ZoneRegistry, config: OperationsConfig = OperationsConfig()):
        self.zones = zones
        self.config = config
        self._zone_over_threshold_since: dict[str, float] = {}
        self._congestion_fired: set[str] = set()
        self._unexpected_active: set[tuple[str, int]] = set()  # (zone_id, track_id) pairs currently flagged

    def process(self, tracks: list[Track], source_id: str, timestamp: float) -> list[Event]:
        events: list[Event] = []

        by_zone: dict[str, list[Track]] = {}
        for track in tracks:
            if not track.current_position:
                continue
            zone_id = self.zones.zone_for_point(track.current_position)
            if zone_id:
                by_zone.setdefault(zone_id, []).append(track)

        for zone_id, occupants in by_zone.items():
            # AREA_OCCUPANCY — a plain factual count, always emitted per zone per frame
            events.append(Event(
                event_type="AREA_OCCUPANCY",
                timestamp=timestamp,
                source_id=source_id,
                track_ids=[t.track_id for t in occupants],
                zone_id=zone_id,
                evidence={"count": len(occupants), "classes": [t.object_class for t in occupants]},
            ))

            # CONGESTION — occupancy above threshold, sustained for a duration (temporal, not single-frame)
            if len(occupants) >= self.config.congestion_count:
                since = self._zone_over_threshold_since.setdefault(zone_id, timestamp)
                duration = timestamp - since
                if duration >= self.config.congestion_sustain_seconds and zone_id not in self._congestion_fired:
                    events.append(Event(
                        event_type="CONGESTION",
                        timestamp=timestamp,
                        source_id=source_id,
                        track_ids=[t.track_id for t in occupants],
                        zone_id=zone_id,
                        severity=Severity.WARNING,
                        duration=duration,
                        evidence={"count": len(occupants), "threshold": self.config.congestion_count},
                    ))
                    self._congestion_fired.add(zone_id)
            else:
                self._zone_over_threshold_since.pop(zone_id, None)
                self._congestion_fired.discard(zone_id)

        # UNEXPECTED_OBJECT — fires once per (zone, track) pair on entry, not
        # every frame the object remains present.
        currently_unexpected: dict[tuple[str, int], tuple[str, set]] = {}
        for zone_id, occupants in by_zone.items():
            expected = self.config.expected_classes_by_zone.get(zone_id)
            if expected is None:
                continue
            for t in occupants:
                if t.object_class not in expected:
                    currently_unexpected[(zone_id, t.track_id)] = (t.object_class, expected)

        newly_unexpected = set(currently_unexpected.keys()) - self._unexpected_active
        self._unexpected_active = set(currently_unexpected.keys())
        for zone_id, track_id in newly_unexpected:
            object_class, expected = currently_unexpected[(zone_id, track_id)]
            events.append(Event(
                event_type="UNEXPECTED_OBJECT",
                timestamp=timestamp,
                source_id=source_id,
                track_ids=[track_id],
                zone_id=zone_id,
                severity=Severity.WARNING,
                evidence={"class": object_class, "expected_classes": sorted(expected)},
            ))

        return events
