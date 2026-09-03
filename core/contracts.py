"""Unified data contracts shared by every input adapter, ML stage, and consumer.

Any source (video file, webcam, synthetic generator) produces Frame objects.
Any consumer (GUI, API, tests) reads Detection/Track/Event objects.
No component here should know or care which physical source produced the data —
that provenance is carried explicitly in `source_type`, never implied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np


class SourceType(str, Enum):
    USB_CAMERA = "USB_CAMERA"
    IP_CAMERA = "IP_CAMERA"
    VIDEO_FILE = "VIDEO_FILE"
    IMAGE_SEQUENCE = "IMAGE_SEQUENCE"
    SYNTHETIC = "SYNTHETIC"
    MOBILE_UPLOAD = "MOBILE_UPLOAD"


@dataclass
class Frame:
    frame_id: int
    timestamp: float          # seconds, monotonic within a session
    source_id: str            # e.g. "video:walking.mp4" or "usb:0"
    source_type: SourceType
    image: np.ndarray         # BGR, HxWx3, uint8
    width: int
    height: int


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    frame_id: int
    timestamp: float
    model_name: str
    track_id: Optional[int] = None


@dataclass
class TrackPoint:
    frame_id: int
    timestamp: float
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    state: Optional[str] = None


@dataclass
class Track:
    track_id: int
    object_class: str
    history: list[TrackPoint] = field(default_factory=list)
    current_state: Optional[str] = None
    state_since: Optional[float] = None
    zone_id: Optional[str] = None
    active: bool = True

    @property
    def current_position(self) -> Optional[tuple[float, float]]:
        return self.history[-1].center if self.history else None

    @property
    def velocity(self) -> Optional[tuple[float, float]]:
        """Pixels/second, estimated from the last two history points."""
        if len(self.history) < 2:
            return None
        a, b = self.history[-2], self.history[-1]
        dt = b.timestamp - a.timestamp
        if dt <= 0:
            return None
        return ((b.center[0] - a.center[0]) / dt, (b.center[1] - a.center[1]) / dt)

    @property
    def duration_in_state(self) -> Optional[float]:
        if self.state_since is None or not self.history:
            return None
        return self.history[-1].timestamp - self.state_since


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


_event_counter = 0


def _next_event_id() -> str:
    global _event_counter
    _event_counter += 1
    return f"evt_{_event_counter}"


@dataclass
class Event:
    """Unified event schema — every module (vision, pose, temporal, spatial,
    safety, sensors, anomaly, inspection, flow, correlation) produces this same
    shape. Nothing downstream needs to know which subsystem an event came from
    to consume it."""
    event_type: str            # e.g. "ZONE_ENTER", "STATE_CHANGE", "PERSON_VEHICLE_PROXIMITY"
    timestamp: float
    source_id: str              # which pipeline/stream produced this (video/sensor stream id)
    track_ids: list[int] = field(default_factory=list)
    event_id: str = field(default_factory=_next_event_id)
    asset_id: Optional[str] = None
    zone_id: Optional[str] = None
    severity: Severity = Severity.INFO
    confidence: Optional[float] = None
    duration: Optional[float] = None
    provenance: str = "REAL"   # REAL | SYNTHETIC | SIMULATION — carried explicitly, never implied
    evidence: dict = field(default_factory=dict)   # measurable reason, never invented
    metadata: dict = field(default_factory=dict)
