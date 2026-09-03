"""Real object detection via a pretrained YOLOv8n model (Ultralytics).

YOLOv8n is chosen deliberately: it is the smallest/fastest variant in the family,
runs acceptably on CPU (no GPU present on this dev machine), and is a genuine
pretrained COCO model — not a placeholder. Swapping in a larger model or a custom
one later requires no changes outside this file (that's the adapter boundary).
"""
from __future__ import annotations

import time

from ultralytics import YOLO

from core.contracts import Detection, Frame
from core.interfaces import Detector

MODEL_NAME = "yolov8n.pt"


class YoloDetector(Detector):
    def __init__(self, model_name: str = MODEL_NAME, confidence_threshold: float = 0.35, imgsz: int = 640):
        """`imgsz` trades accuracy for speed: measured on this machine
        (scripts/benchmark_resolution.py, 40 real frames), imgsz=320 runs
        2.75x faster (222.8ms -> 81.0ms avg) but finds ~8% fewer detections
        (274 -> 251) than the default 640. Not a free win — pick deliberately."""
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.imgsz = imgsz
        self._model = YOLO(model_name)
        self.last_inference_ms: float = 0.0

    def detect(self, frame: Frame) -> list[Detection]:
        start = time.perf_counter()
        results = self._model.predict(frame.image, verbose=False, conf=self.confidence_threshold, imgsz=self.imgsz)
        self.last_inference_ms = (time.perf_counter() - start) * 1000.0

        detections: list[Detection] = []
        if not results:
            return detections

        result = results[0]
        names = result.names
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
            detections.append(Detection(
                class_name=names[cls_id],
                confidence=conf,
                bbox=(x1, y1, x2, y2),
                frame_id=frame.frame_id,
                timestamp=frame.timestamp,
                model_name=self.model_name,
            ))
        return detections
