"""Model registry — real metadata about each model actually used in AERION-X,
not placeholder text. Populated from the loaded model object plus known facts
about its public release (weights source, license), not invented.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ModelRecord:
    name: str
    version: str
    framework: str
    task: str
    classes: list[str]
    input_resolution: str
    weights_source: str
    license: str
    hardware: str
    num_parameters: int | None = None
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    benchmark_results: dict = field(default_factory=dict)  # filled in only by an actual measured run


class ModelRegistry:
    def __init__(self):
        self._models: dict[str, ModelRecord] = {}

    def register(self, record: ModelRecord) -> None:
        self._models[f"{record.name}:{record.version}"] = record

    def get(self, name: str, version: str) -> ModelRecord | None:
        return self._models.get(f"{name}:{version}")

    def all(self) -> list[ModelRecord]:
        return list(self._models.values())


def _current_hardware() -> str:
    gpu = "none detected (CPU-only)"
    try:
        import torch
        if torch.cuda.is_available():
            gpu = torch.cuda.get_device_name(0)
    except ImportError:
        pass
    return f"{platform.system()} {platform.machine()}, GPU: {gpu}"


def build_yolo_detector_record(detector) -> ModelRecord:
    """Extracts genuine metadata from an already-loaded YoloDetector instance —
    class list and parameter count come directly from the model object, not
    from a hardcoded guess."""
    model = detector._model
    try:
        num_params = sum(p.numel() for p in model.model.parameters())
    except Exception:
        num_params = None

    return ModelRecord(
        name="YOLOv8n",
        version="8.4.0",  # matches the release the weights were fetched from (ultralytics/assets v8.4.0)
        framework="PyTorch (Ultralytics)",
        task="object_detection",
        classes=list(model.names.values()),
        input_resolution="640x640 (default, letterboxed)",
        weights_source="https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt",
        license="AGPL-3.0 (Ultralytics)",
        hardware=_current_hardware(),
        num_parameters=num_params,
    )
