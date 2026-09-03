"""Real human pose/keypoint estimation via a pretrained YOLOv8n-pose model.

Produces 17 COCO keypoints per detected person. This module only reports
keypoints and their confidences — it does not itself infer state; the temporal
state engine (core/temporal/state_engine.py) is what turns pose+motion history
into WALKING/STANDING/etc over a window. Kept separate on purpose so pose
extraction can be swapped or skipped without touching temporal logic.
"""
from __future__ import annotations

import time

from ultralytics import YOLO

from core.contracts import Frame
from core.interfaces import PoseEstimator as PoseEstimatorInterface

MODEL_NAME = "yolov8n-pose.pt"

COCO_KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


class YoloPoseEstimator(PoseEstimatorInterface):
    def __init__(self, model_name: str = MODEL_NAME, confidence_threshold: float = 0.35):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self._model = YOLO(model_name)
        self.last_inference_ms: float = 0.0

    def estimate(self, frame: Frame) -> list[dict]:
        """Returns one dict per detected person: bbox, confidence, keypoints (17 x,y,conf)."""
        start = time.perf_counter()
        results = self._model.predict(frame.image, verbose=False, conf=self.confidence_threshold)
        self.last_inference_ms = (time.perf_counter() - start) * 1000.0

        people = []
        if not results or results[0].keypoints is None:
            return people

        result = results[0]
        boxes = result.boxes
        kpts = result.keypoints.data  # N x 17 x 3 (x, y, conf)

        for i in range(len(boxes)):
            x1, y1, x2, y2 = [float(v) for v in boxes.xyxy[i]]
            conf = float(boxes.conf[i])
            keypoints = [(float(x), float(y), float(c)) for x, y, c in kpts[i].tolist()]
            people.append({
                "bbox": (x1, y1, x2, y2),
                "confidence": conf,
                "keypoints": dict(zip(COCO_KEYPOINT_NAMES, keypoints)),
                "frame_id": frame.frame_id,
                "timestamp": frame.timestamp,
                "model_name": self.model_name,
            })
        return people
