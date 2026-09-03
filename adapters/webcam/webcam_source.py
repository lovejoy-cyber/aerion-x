"""Live USB/built-in webcam capture via OpenCV. Same FrameSource interface as
VideoFileSource — the pipeline downstream never knows the difference.

UNTESTED against real hardware: no camera exists on the machine this was
written on (see LIMITATIONS.md). The failure path (no camera / camera busy)
IS verified — cv2.VideoCapture(N).isOpened() correctly reports False here,
which is exactly what happens on a real machine with no camera at that index.
"""
from __future__ import annotations

import time
from typing import Iterator, Optional

import cv2

from adapters.base import FrameSource
from core.contracts import Frame, SourceType


class WebcamSource(FrameSource):
    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.source_type = SourceType.USB_CAMERA
        self.source_id = f"webcam:{device_index}"
        self._cap = cv2.VideoCapture(device_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open webcam at device index {device_index} — "
                "no camera there, already in use by another app, or driver issue"
            )
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0

    def fps_hint(self) -> Optional[float]:
        return self._fps

    def frames(self) -> Iterator[Frame]:
        """Runs until close()/stop is signaled upstream or the camera stops
        producing frames (unplugged, driver crash) — no fixed frame count,
        unlike a video file. Timestamps are real wall-clock time since a live
        feed has no fixed frame-rate-derived timeline."""
        frame_id = 0
        start = time.monotonic()
        while True:
            ok, image = self._cap.read()
            if not ok:
                break  # camera disconnected/unavailable — pipeline reports this as a stopped run, not a silent hang
            yield Frame(
                frame_id=frame_id,
                timestamp=time.monotonic() - start,
                source_id=self.source_id,
                source_type=self.source_type,
                image=image,
                width=image.shape[1],
                height=image.shape[0],
            )
            frame_id += 1

    def close(self) -> None:
        self._cap.release()
