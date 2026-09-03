"""Validates the inspection (change detection) and optical flow modules against
real frames extracted from the real test video — not synthetic images. These
are generic classical-CV validations (do two real frames produce a sane,
bounded change/flow measurement?), not aircraft-specific claims.
"""
import cv2
import numpy as np
import pytest

from core.contracts import Frame, SourceType
from core.inspection.pipeline import (
    change_detection,
    contour_regions,
    edge_map,
    generate_inspection_report,
    preprocess,
    structural_similarity,
)
from core.vision.optical_flow import FarnebackFlowEstimator

VIDEO_PATH = "data/videos/vtest.avi"


def _load_frame(index: int) -> Frame:
    cap = cv2.VideoCapture(VIDEO_PATH)
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, image = cap.read()
    cap.release()
    if not ok:
        pytest.skip(f"could not read frame {index} from {VIDEO_PATH}")
    return Frame(frame_id=index, timestamp=index / 10.0, source_id="video:vtest.avi",
                 source_type=SourceType.VIDEO_FILE, image=image, width=image.shape[1], height=image.shape[0])


def test_preprocess_produces_grayscale_same_size():
    frame = _load_frame(0)
    out = preprocess(frame.image)
    assert out.ndim == 2
    assert out.shape[:2] == frame.image.shape[:2]


def test_edge_map_finds_real_edges_not_blank():
    frame = _load_frame(0)
    edges = edge_map(frame.image)
    assert edges.shape[:2] == frame.image.shape[:2]
    assert np.count_nonzero(edges) > 0, "Canny found zero edges on a real video frame — suspicious"


def test_change_detection_between_two_real_frames_is_bounded():
    a = _load_frame(0)
    b = _load_frame(50)  # a later frame with people having moved
    result = change_detection(a.image, b.image)
    assert 0.0 <= result["change_score"] <= 1.0
    assert result["diff_map"].shape[:2] == a.image.shape[:2]


def test_change_detection_identical_frame_has_near_zero_score():
    a = _load_frame(0)
    result = change_detection(a.image, a.image.copy())
    assert result["change_score"] < 0.02, "comparing a frame to itself should show almost no change"


def test_structural_similarity_identical_frame_is_near_one():
    a = _load_frame(0)
    gray = preprocess(a.image)
    score, ssim_map = structural_similarity(gray, gray.copy())
    assert score > 0.99
    assert ssim_map.shape == gray.shape


def test_structural_similarity_different_frames_is_lower_than_identical():
    a = _load_frame(0)
    b = _load_frame(200)
    gray_a, gray_b = preprocess(a.image), preprocess(b.image)
    same_score, _ = structural_similarity(gray_a, gray_a.copy())
    diff_score, _ = structural_similarity(gray_a, gray_b)
    assert diff_score < same_score


def test_contour_regions_on_real_change_mask():
    a = _load_frame(0)
    b = _load_frame(50)
    result = change_detection(a.image, b.image)
    regions = contour_regions(result["change_mask"], min_area=20)
    for r in regions:
        assert r["area_px"] >= 20
        assert len(r["bbox"]) == 4


def test_generate_inspection_report_end_to_end_on_real_frames():
    a = _load_frame(0)
    b = _load_frame(50)
    report = generate_inspection_report("insp_1", "asset_1", 0.0, a.image, b.image)
    assert 0.0 <= report.change_score <= 1.0
    assert -1.0 <= report.mean_ssim <= 1.0
    assert all(r["label"] == "VISUAL ANOMALY REGION" for r in report.anomaly_regions)
    assert "not a trained defect classifier" in report.notes.lower()


def test_farneback_optical_flow_on_real_consecutive_frames():
    a = _load_frame(100)
    b = _load_frame(101)
    estimator = FarnebackFlowEstimator()
    result = estimator.compute(a, b)
    assert result.flow_field.shape[:2] == a.image.shape[:2]
    assert result.magnitude_mean >= 0.0
    assert result.method == "farneback"
