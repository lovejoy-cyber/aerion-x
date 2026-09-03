"""Correlates events across independent streams (vision, sensor/anomaly,
inspection, flow) by time window. Generic on purpose: it operates on the
unified Event schema (core.contracts.Event) regardless of which subsystem
produced each event, so real aircraft telemetry can plug in later without
changing this module.

A correlation is a claim about temporal coincidence only — "these things
happened close together in time" — never a claim of causation. That
distinction is kept explicit in the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.contracts import Event


@dataclass
class CorrelatedEvent:
    correlation_id: str
    window_start: float
    window_end: float
    events: list[Event]
    event_types: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    provenance_note: str = ""

    def __post_init__(self):
        self.event_types = {e.event_type for e in self.events}
        self.sources = {e.source_id for e in self.events}
        provenances = {e.provenance for e in self.events}
        self.provenance_note = "MIXED: " + ",".join(sorted(provenances)) if len(provenances) > 1 else next(iter(provenances))


class CorrelationEngine:
    """Groups events from *different* sources whose timestamps fall within
    `window_seconds` of each other. Same-source event bursts don't count as a
    correlation on their own — the point is cross-subsystem coincidence
    (e.g. a vision event and a sensor anomaly near the same moment)."""

    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds = window_seconds
        self._counter = 0

    def correlate(self, events: list[Event]) -> list[CorrelatedEvent]:
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        correlations: list[CorrelatedEvent] = []
        used: set[int] = set()

        for i, anchor in enumerate(sorted_events):
            if id(anchor) in used:
                continue
            group = [anchor]
            for j in range(i + 1, len(sorted_events)):
                candidate = sorted_events[j]
                if candidate.timestamp - anchor.timestamp > self.window_seconds:
                    break
                if id(candidate) in used:
                    continue
                if candidate.source_id != anchor.source_id:
                    group.append(candidate)

            if len(group) > 1:
                for e in group:
                    used.add(id(e))
                self._counter += 1
                correlations.append(CorrelatedEvent(
                    correlation_id=f"corr_{self._counter}",
                    window_start=min(e.timestamp for e in group),
                    window_end=max(e.timestamp for e in group),
                    events=group,
                ))

        return correlations
