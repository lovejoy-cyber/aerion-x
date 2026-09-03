"""Abstract model interfaces. Every concrete implementation (YOLOv8n today,
a specialized aerospace model tomorrow) plugs in here — nothing downstream
imports Ultralytics, sklearn, or any specific library directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.contracts import Detection, Frame, Track


class Detector(ABC):
    model_name: str

    @abstractmethod
    def detect(self, frame: Frame) -> list[Detection]: ...


class PoseEstimator(ABC):
    model_name: str

    @abstractmethod
    def estimate(self, frame: Frame) -> list[dict]: ...


class Segmenter(ABC):
    model_name: str

    @abstractmethod
    def segment(self, frame: Frame) -> Any: ...


class Tracker(ABC):
    @abstractmethod
    def update(self, detections: list[Detection], frame_id: int, timestamp: float) -> list[Detection]: ...

    @abstractmethod
    def active_tracks(self) -> list[Track]: ...


class AnomalyDetector(ABC):
    algorithm_name: str

    @abstractmethod
    def fit(self, values: list[float]) -> None: ...

    @abstractmethod
    def score(self, values: list[float]) -> list[float]: ...


class FlowEstimator(ABC):
    method_name: str

    @abstractmethod
    def compute(self, frame_a: Frame, frame_b: Frame) -> Any: ...
