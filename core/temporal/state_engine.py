"""Temporal state classification from motion history — never from a single frame.

Speed is measured over a sliding window of recent track history (pixels/second,
smoothed) and mapped to an observable physical state. Thresholds are configurable
and expressed in pixels/second because this operates on uncalibrated 2D camera
space — there is no real-world speed without calibration, and this module does not
pretend to have one.

Only reports observable motion states (STATIONARY/STANDING/MOVING/WALKING) — never
fatigue, health, or intent.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.contracts import Track


@dataclass
class StateThresholds:
    stationary_max_speed: float = 8.0     # px/s below this => STATIONARY
    walking_max_speed: float = 60.0       # px/s below this => WALKING, above => MOVING
    window: int = 8                       # history points used for smoothing


def _smoothed_speed(track: Track, window: int) -> float:
    pts = track.history[-window:]
    if len(pts) < 2:
        return 0.0
    total_dist = 0.0
    total_time = 0.0
    for a, b in zip(pts, pts[1:]):
        dt = b.timestamp - a.timestamp
        if dt <= 0:
            continue
        dist = ((b.center[0] - a.center[0]) ** 2 + (b.center[1] - a.center[1]) ** 2) ** 0.5
        total_dist += dist
        total_time += dt
    return total_dist / total_time if total_time > 0 else 0.0


def classify_state(track: Track, thresholds: StateThresholds = StateThresholds()) -> str:
    speed = _smoothed_speed(track, thresholds.window)
    if speed < thresholds.stationary_max_speed:
        return "STATIONARY" if track.object_class == "person" else "STOPPED"
    if speed < thresholds.walking_max_speed:
        return "WALKING" if track.object_class == "person" else "MOVING"
    return "MOVING"


def update_track_state(track: Track, timestamp: float, thresholds: StateThresholds = StateThresholds()) -> bool:
    """Updates track.current_state / state_since in place.

    Returns True if the state changed this call (caller uses this to emit a
    STATE_CHANGE event with proper before/after evidence).
    """
    new_state = classify_state(track, thresholds)
    if track.current_state != new_state:
        track.current_state = new_state
        track.state_since = timestamp
        if track.history:
            track.history[-1].state = new_state
        return True
    if track.history:
        track.history[-1].state = new_state
    return False
