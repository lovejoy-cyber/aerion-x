"""Reads real frames from a video file on disk via OpenCV."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional

import cv2

from adapters.base import FrameSource
from core.contracts import Frame, SourceType


class VideoFileSource(FrameSource):
    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")
        self.source_type = SourceType.VIDEO_FILE
        self.source_id = f"video:{self.path.name}"
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise RuntimeError(f"OpenCV could not open video file: {path}")
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0

    def fps_hint(self) -> Optional[float]:
        return self._fps

    def frames(self) -> Iterator[Frame]:
        frame_id = 0
        start = time.monotonic()
        while True:
            ok, image = self._cap.read()
            if not ok:
                break
            timestamp = frame_id / self._fps
            yield Frame(
                frame_id=frame_id,
                timestamp=timestamp,
                source_id=self.source_id,
                source_type=self.source_type,
                image=image,
                width=image.shape[1],
                height=image.shape[0],
            )
            frame_id += 1

    def close(self) -> None:
        self._cap.release()
