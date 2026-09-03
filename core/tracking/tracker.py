"""Centroid + IoU-based multi-object tracker.

Not a learned tracker (no DeepSORT/embedding model) — deliberately simple and
inspectable: match detections to existing tracks by IoU first, fall back to
nearest-centroid, age out tracks that go unmatched. This is a real, working
algorithm (the same family used by SORT), not a placeholder.
"""
from __future__ import annotations

from typing import Optional

from core.contracts import Detection, Track, TrackPoint
from core.interfaces import Tracker as TrackerInterface


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class CentroidIoUTracker(TrackerInterface):
    def __init__(self, iou_threshold: float = 0.3, max_missed_frames: int = 15, max_centroid_distance: float = 80.0):
        self.iou_threshold = iou_threshold
        self.max_missed_frames = max_missed_frames
        self.max_centroid_distance = max_centroid_distance
        self.tracks: dict[int, Track] = {}
        self._missed: dict[int, int] = {}
        self._next_id = 1

    def _match_track(self, track: Track, detections: list[Detection], unmatched_dets: list[int]) -> Optional[int]:
        last_point = track.history[-1]
        best_score, best_idx = 0.0, None
        for i in unmatched_dets:
            if detections[i].class_name != track.object_class:
                continue
            score = _iou(last_point.bbox, detections[i].bbox)
            if score > best_score:
                best_score, best_idx = score, i
        if best_idx is not None and best_score >= self.iou_threshold:
            return best_idx

        # IoU found nothing usable (e.g. fast motion, low frame rate) — fall back
        # to nearest centroid within a bounded distance rather than losing the track.
        best_dist, best_idx = self.max_centroid_distance, None
        for i in unmatched_dets:
            if detections[i].class_name != track.object_class:
                continue
            d = _dist(last_point.center, _center(detections[i].bbox))
            if d < best_dist:
                best_dist, best_idx = d, i
        return best_idx

    def update(self, detections: list[Detection], frame_id: int, timestamp: float) -> list[Detection]:
        unmatched_dets = list(range(len(detections)))
        matched_track_ids: set[int] = set()

        active_ids = [tid for tid, tr in self.tracks.items() if tr.active]
        for tid in active_ids:
            track = self.tracks[tid]
            best_idx = self._match_track(track, detections, unmatched_dets)
            if best_idx is not None:
                det = detections[best_idx]
                track.history.append(
                    TrackPoint(frame_id=frame_id, timestamp=timestamp, bbox=det.bbox, center=_center(det.bbox))
                )
                det.track_id = tid
                unmatched_dets.remove(best_idx)
                matched_track_ids.add(tid)
                self._missed[tid] = 0

        for tid in active_ids:
            if tid not in matched_track_ids:
                self._missed[tid] = self._missed.get(tid, 0) + 1
                if self._missed[tid] > self.max_missed_frames:
                    self.tracks[tid].active = False

        for i in unmatched_dets:
            det = detections[i]
            tid = self._next_id
            self._next_id += 1
            self.tracks[tid] = Track(
                track_id=tid,
                object_class=det.class_name,
                history=[TrackPoint(frame_id=frame_id, timestamp=timestamp, bbox=det.bbox, center=_center(det.bbox))],
            )
            det.track_id = tid
            self._missed[tid] = 0

        return detections

    def active_tracks(self) -> list[Track]:
        return [t for t in self.tracks.values() if t.active]
