"""Common interface every input adapter implements.

The CV engine only ever talks to this interface. It never imports cv2.VideoCapture
directly, never checks "am I a webcam", and never branches on OS. That isolation is
what lets a USB camera replace a video file later with zero changes downstream.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional

from core.contracts import Frame


class FrameSource(ABC):
    source_type: str
    source_id: str

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield Frame objects until the source is exhausted or stopped."""

    @abstractmethod
    def fps_hint(self) -> Optional[float]:
        """Nominal source frame rate, if known (used for timestamp fallback)."""

    def close(self) -> None:
        pass
