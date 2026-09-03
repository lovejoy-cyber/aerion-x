"""Real optical flow via OpenCV — motion vectors, not CFD. Explicitly not
claiming fluid simulation: this measures apparent pixel motion between two
frames, useful for e.g. flow-visualization video analysis or general motion
magnitude/direction, nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from core.contracts import Frame
from core.interfaces import FlowEstimator


@dataclass
class FlowResult:
    flow_field: np.ndarray       # HxWx2, (dx, dy) per pixel
    magnitude_mean: float
    magnitude_max: float
    direction_mean_deg: float
    frame_id_a: int
    frame_id_b: int
    method: str


class FarnebackFlowEstimator(FlowEstimator):
    """Dense optical flow (Gunnar Farneback's algorithm, built into OpenCV)."""

    method_name = "farneback"

    def compute(self, frame_a: Frame, frame_b: Frame) -> FlowResult:
        gray_a = cv2.cvtColor(frame_a.image, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(frame_b.image, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            gray_a, gray_b, None, pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1], angleInDegrees=True)
        return FlowResult(
            flow_field=flow,
            magnitude_mean=float(mag.mean()),
            magnitude_max=float(mag.max()),
            direction_mean_deg=float(ang.mean()),
            frame_id_a=frame_a.frame_id,
            frame_id_b=frame_b.frame_id,
            method=self.method_name,
        )


@dataclass
class RegionFlowStats:
    region_bbox: tuple[int, int, int, int]
    magnitude_mean: float
    magnitude_max: float
    direction_mean_deg: float


def region_flow_statistics(flow_result: FlowResult, regions: list[tuple[int, int, int, int]]) -> list[RegionFlowStats]:
    """Breaks a dense flow field into per-region statistics (e.g. one region per
    tracked bounding box), so motion can be attributed to a specific object or
    zone rather than only reported as a single frame-wide average."""
    flow = flow_result.flow_field
    stats = []
    for x1, y1, x2, y2 in regions:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(flow.shape[1], int(x2)), min(flow.shape[0], int(y2))
        if x2 <= x1 or y2 <= y1:
            continue
        patch = flow[y1:y2, x1:x2]
        mag, ang = cv2.cartToPolar(patch[..., 0], patch[..., 1], angleInDegrees=True)
        stats.append(RegionFlowStats(
            region_bbox=(x1, y1, x2, y2),
            magnitude_mean=float(mag.mean()),
            magnitude_max=float(mag.max()),
            direction_mean_deg=float(ang.mean()),
        ))
    return stats


def detect_abnormal_motion(current: FlowResult, baseline_magnitude_mean: float, baseline_std: float,
                            n_std: float = 3.0) -> dict | None:
    """Flags a frame's overall flow magnitude as abnormal relative to a
    previously-established baseline (mean/std over prior frames) — the same
    z-score principle used in core.sensors.anomaly, applied to motion instead
    of telemetry. Caller supplies the baseline; this function does not invent one."""
    if baseline_std <= 0:
        return None
    z = abs(current.magnitude_mean - baseline_magnitude_mean) / baseline_std
    if z >= n_std:
        return {
            "z_score": z,
            "threshold": n_std,
            "current_magnitude_mean": current.magnitude_mean,
            "baseline_magnitude_mean": baseline_magnitude_mean,
            "reason": f"{z:.2f} std devs from baseline mean flow magnitude {baseline_magnitude_mean:.3f}",
        }
    return None


class LucasKanadeFlowEstimator(FlowEstimator):
    """Sparse optical flow tracking a grid of feature points — cheaper than
    Farneback, useful when only representative motion vectors are needed."""

    method_name = "lucas-kanade"

    def __init__(self, max_points: int = 200):
        self.max_points = max_points

    def compute(self, frame_a: Frame, frame_b: Frame):
        gray_a = cv2.cvtColor(frame_a.image, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(frame_b.image, cv2.COLOR_BGR2GRAY)
        points_a = cv2.goodFeaturesToTrack(gray_a, maxCorners=self.max_points, qualityLevel=0.01, minDistance=7)
        if points_a is None:
            return {"vectors": [], "frame_id_a": frame_a.frame_id, "frame_id_b": frame_b.frame_id, "method": self.method_name}

        points_b, status, _ = cv2.calcOpticalFlowPyrLK(gray_a, gray_b, points_a, None)
        vectors = []
        for pa, pb, st in zip(points_a, points_b, status):
            if st[0] == 1:
                vectors.append({
                    "from": (float(pa[0][0]), float(pa[0][1])),
                    "to": (float(pb[0][0]), float(pb[0][1])),
                })
        return {"vectors": vectors, "frame_id_a": frame_a.frame_id, "frame_id_b": frame_b.frame_id, "method": self.method_name}
