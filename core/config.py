"""Central configuration, loaded from environment variables with sane defaults.
No secrets belong here — this is for runtime tuning knobs only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    detector_confidence_threshold: float = _env_float("AERIONX_DETECTOR_CONFIDENCE", 0.35)
    tracker_iou_threshold: float = _env_float("AERIONX_TRACKER_IOU", 0.3)
    tracker_max_missed_frames: int = _env_int("AERIONX_TRACKER_MAX_MISSED", 15)
    tracker_max_centroid_distance: float = _env_float("AERIONX_TRACKER_MAX_CENTROID_DIST", 80.0)
    stationary_alert_seconds: float = _env_float("AERIONX_STATIONARY_ALERT_SECONDS", 5.0)
    log_level: str = os.environ.get("AERIONX_LOG_LEVEL", "INFO")
    data_dir: str = os.environ.get("AERIONX_DATA_DIR", "data")


settings = Settings()
