"""Live IP/RTSP camera stream via OpenCV's FFmpeg backend. Same pattern and
same untested-against-real-hardware caveat as WebcamSource — no RTSP camera
or stream exists on the machine this was written on.
"""
from __future__ import annotations

import time
from typing import Iterator, Optional

import cv2

from adapters.base import FrameSource
from core.contracts import Frame, SourceType


class RTSPSource(FrameSource):
    def __init__(self, rtsp_url: str):
        self.rtsp_url = rtsp_url
        self.source_type = SourceType.IP_CAMERA
        self.source_id = f"rtsp:{rtsp_url.split('@')[-1]}"  # strip any embedded credentials before using as an id/log label
        # Without an explicit timeout, FFmpeg's default RTSP connect timeout
        # is very long — an unreachable camera hangs the pipeline-start
        # thread for a long time instead of failing fast. Found by actually
        # testing against an unreachable address, not by reading FFmpeg docs.
        self._cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000])
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open RTSP stream: {self.source_id} (unreachable, wrong URL, or auth failed)")
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0

    def fps_hint(self) -> Optional[float]:
        return self._fps

    def frames(self) -> Iterator[Frame]:
        frame_id = 0
        start = time.monotonic()
        while True:
            ok, image = self._cap.read()
            if not ok:
                break  # stream dropped/unreachable — surfaces as a stopped pipeline run, not a silent hang
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
