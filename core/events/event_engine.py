"""Derives real events from track/state/zone changes. No randomness, no fabrication —
every event's `evidence` dict names the measurable fact that triggered it.
"""
from __future__ import annotations

from core.contracts import Event, Track
from core.spatial.zones import ZoneRegistry


class EventEngine:
    def __init__(self, zone_registry: ZoneRegistry, stationary_alert_seconds: float = 5.0):
        self.zones = zone_registry
        self.stationary_alert_seconds = stationary_alert_seconds
        self._prolonged_fired: set[int] = set()
        self._seen_tracks: set[int] = set()

    def process(self, tracks: list[Track], source_id: str, timestamp: float, state_changed: dict[int, bool]) -> list[Event]:
        events: list[Event] = []

        for track in tracks:
            if track.track_id not in self._seen_tracks:
                self._seen_tracks.add(track.track_id)
                events.append(Event(
                    event_type="OBJECT_APPEARED",
                    timestamp=timestamp,
                    source_id=source_id,
                    track_ids=[track.track_id],
                    evidence={"class": track.object_class, "bbox": track.history[-1].bbox},
                ))

            if track.current_position:
                new_zone = self.zones.zone_for_point(track.current_position)
                if new_zone != track.zone_id:
                    if track.zone_id is not None:
                        events.append(Event(
                            event_type="ZONE_EXIT",
                            timestamp=timestamp,
                            source_id=source_id,
                            track_ids=[track.track_id],
                            zone_id=track.zone_id,
                            evidence={"position": track.current_position},
                        ))
                    if new_zone is not None:
                        events.append(Event(
                            event_type="ZONE_ENTER",
                            timestamp=timestamp,
                            source_id=source_id,
                            track_ids=[track.track_id],
                            zone_id=new_zone,
                            evidence={"position": track.current_position},
                        ))
                    track.zone_id = new_zone

            if state_changed.get(track.track_id):
                events.append(Event(
                    event_type="STATE_CHANGE",
                    timestamp=timestamp,
                    source_id=source_id,
                    track_ids=[track.track_id],
                    evidence={"new_state": track.current_state},
                ))
                self._prolonged_fired.discard(track.track_id)

            if (
                track.current_state in ("STATIONARY", "STOPPED")
                and track.duration_in_state is not None
                and track.duration_in_state >= self.stationary_alert_seconds
                and track.track_id not in self._prolonged_fired
            ):
                events.append(Event(
                    event_type="PROLONGED_STATIONARY",
                    timestamp=timestamp,
                    source_id=source_id,
                    track_ids=[track.track_id],
                    evidence={"duration_seconds": track.duration_in_state},
                ))
                self._prolonged_fired.add(track.track_id)

        active_ids = {t.track_id for t in tracks}
        disappeared = self._seen_tracks - active_ids
        for tid in list(disappeared):
            events.append(Event(
                event_type="OBJECT_DISAPPEARED",
                timestamp=timestamp,
                source_id=source_id,
                track_ids=[tid],
                evidence={},
            ))
            self._seen_tracks.discard(tid)

        return events
