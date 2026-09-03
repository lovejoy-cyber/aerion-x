"""WebcamSource/RTSPSource: this machine genuinely has no camera and no RTSP
stream, so what CAN be tested here for real is the failure path — and it
matters that it fails cleanly (RuntimeError, not a hang or a silent no-op)
rather than the happy path, which is untested pending real hardware (see
LIMITATIONS.md).
"""
import pytest

from adapters.network.rtsp_source import RTSPSource
from adapters.webcam.webcam_source import WebcamSource


def test_webcam_source_fails_cleanly_with_no_camera_present():
    """Real, not simulated: this dev machine has no webcam, so opening device
    0 genuinely fails — proving the error path works rather than hanging."""
    with pytest.raises(RuntimeError, match="Could not open webcam"):
        WebcamSource(device_index=0)


def test_rtsp_source_fails_cleanly_with_unreachable_stream():
    with pytest.raises(RuntimeError, match="Could not open RTSP stream"):
        RTSPSource(rtsp_url="rtsp://192.0.2.1:554/nonexistent")  # 192.0.2.0/24 is reserved for docs/testing, guaranteed unreachable


def test_rtsp_source_id_strips_embedded_credentials():
    """rtsp://user:pass@host/stream — the source_id (used in logs/events)
    must never carry the password through."""
    try:
        RTSPSource(rtsp_url="rtsp://user:secretpass@192.0.2.1:554/stream")
    except RuntimeError as e:
        assert "secretpass" not in str(e)
