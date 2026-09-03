"""Generates a reproducible synthetic video stream for pipeline testing.

This is explicitly NOT a stand-in for real camera evidence. Every frame it produces
is labeled SourceType.SYNTHETIC and downstream consumers (GUI, logs, reports) must
surface that label — never present synthetic output as a real detection.

Draws a moving colored rectangle ("person-like" blob) along a deterministic path so
tracking/temporal/zone logic can be tested without any camera hardware.
"""
from __future__ import annotations

import time
from typing import Iterator, Optional

import numpy as np

from adapters.base import FrameSource
from core.contracts import Frame, SourceType


class SyntheticSource(FrameSource):
    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        num_frames: int = 300,
        fps: float = 30.0,
        seed: int = 42,
    ):
        self.source_type = SourceType.SYNTHETIC
        self.source_id = f"synthetic:seed{seed}"
        self.width = width
        self.height = height
        self.num_frames = num_frames
        self._fps = fps
        self._rng = np.random.default_rng(seed)

    def fps_hint(self) -> Optional[float]:
        return self._fps

    def frames(self) -> Iterator[Frame]:
        box_w, box_h = 60, 140
        for frame_id in range(self.num_frames):
            image = np.full((self.height, self.width, 3), 30, dtype=np.uint8)

            t = frame_id / self.num_frames
            x = int(20 + (self.width - box_w - 40) * (0.5 + 0.5 * np.sin(t * 2 * np.pi)))
            y = int(self.height / 2 - box_h / 2)

            noise = self._rng.integers(-3, 4, size=image.shape, dtype=np.int16)
            image = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            image[y : y + box_h, x : x + box_w] = (60, 140, 200)

            yield Frame(
                frame_id=frame_id,
                timestamp=frame_id / self._fps,
                source_id=self.source_id,
                source_type=self.source_type,
                image=image,
                width=self.width,
                height=self.height,
            )
