"""Aircraft/asset inspection infrastructure.

Implements what's genuinely possible with classical computer vision and no
specialized training data: preprocessing, ROI extraction, image registration
(feature-based alignment), before/after difference, and generic visual change
scoring. This is NOT crack/corrosion detection — it is change detection between
two images of the same surface. A specialized aerospace-defect model can later
implement `DefectDetector` and slot in without touching this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cv2
import numpy as np
from scipy.ndimage import uniform_filter


class InspectionSourceType(str, Enum):
    UPLOADED_IMAGE = "UPLOADED_IMAGE"
    UPLOADED_VIDEO = "UPLOADED_VIDEO"
    LIVE_CAPTURE = "LIVE_CAPTURE"


@dataclass
class ROI:
    x: int
    y: int
    width: int
    height: int

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.y : self.y + self.height, self.x : self.x + self.width]


@dataclass
class InspectionRecord:
    inspection_id: str
    asset_id: str
    timestamp: float
    source_type: InspectionSourceType
    image_path: str
    roi: Optional[ROI] = None
    baseline_image_path: Optional[str] = None
    change_score: Optional[float] = None
    notes: str = ""


def preprocess(image: np.ndarray) -> np.ndarray:
    """Grayscale + CLAHE contrast enhancement — improves visibility of surface
    detail (scratches, edges) without inventing any detection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def edge_map(image: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    """Canny edges — a real, classical technique for surface discontinuities.
    Produces candidate edge regions, not classified defects."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(gray, low, high)


def register_images(reference: np.ndarray, moving: np.ndarray) -> np.ndarray:
    """Aligns `moving` onto `reference` using ORB feature matching + homography,
    so before/after comparisons aren't corrupted by camera-position drift."""
    ref_gray = reference if reference.ndim == 2 else cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    mov_gray = moving if moving.ndim == 2 else cv2.cvtColor(moving, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=1000)
    kp1, des1 = orb.detectAndCompute(ref_gray, None)
    kp2, des2 = orb.detectAndCompute(mov_gray, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return moving  # not enough features to align — return unaligned rather than fabricate a transform

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(matcher.match(des1, des2), key=lambda m: m.distance)[:50]
    if len(matches) < 4:
        return moving

    src_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if H is None:
        return moving

    h, w = reference.shape[:2]
    return cv2.warpPerspective(moving, H, (w, h))


def change_detection(reference: np.ndarray, current: np.ndarray, threshold: int = 30) -> dict:
    """Aligns `current` to `reference`, computes absolute difference, and returns
    a change mask plus a single change_score (fraction of pixels changed above
    threshold). This is generic visual change detection — surfacing regions a
    human inspector should look at, not an automated defect classification."""
    aligned = register_images(reference, current)
    ref_gray = preprocess(reference)
    cur_gray = preprocess(aligned)

    if ref_gray.shape != cur_gray.shape:
        cur_gray = cv2.resize(cur_gray, (ref_gray.shape[1], ref_gray.shape[0]))

    diff = cv2.absdiff(ref_gray, cur_gray)
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    change_score = float(np.count_nonzero(mask)) / mask.size

    return {"diff_map": diff, "change_mask": mask, "change_score": change_score}


def structural_similarity(a: np.ndarray, b: np.ndarray, window: int = 7) -> tuple[float, np.ndarray]:
    """Real windowed SSIM (Wang et al. 2004 formula), implemented directly with
    scipy uniform filters rather than pulling in scikit-image for one function.
    Returns (mean_ssim, ssim_map) — the map highlights where structure differs,
    useful as a "VISUAL ANOMALY REGION" indicator, not a defect classification."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0])).astype(np.float64)

    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2

    mu_a = uniform_filter(a, window)
    mu_b = uniform_filter(b, window)
    mu_a_sq, mu_b_sq, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b

    sigma_a_sq = uniform_filter(a * a, window) - mu_a_sq
    sigma_b_sq = uniform_filter(b * b, window) - mu_b_sq
    sigma_ab = uniform_filter(a * b, window) - mu_ab

    ssim_map = ((2 * mu_ab + C1) * (2 * sigma_ab + C2)) / ((mu_a_sq + mu_b_sq + C1) * (sigma_a_sq + sigma_b_sq + C2))
    return float(ssim_map.mean()), ssim_map


def contour_regions(change_mask: np.ndarray, min_area: int = 30) -> list[dict]:
    """Extracts connected regions from a change/edge mask via real contour
    detection, scored by area — candidate regions for a human inspector to
    review, not classified defects."""
    contours, _ = cv2.findContours(change_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        regions.append({"bbox": (x, y, x + w, y + h), "area_px": area})
    return sorted(regions, key=lambda r: -r["area_px"])


@dataclass
class InspectionReport:
    inspection_id: str
    asset_id: str
    timestamp: float
    change_score: float
    mean_ssim: float
    anomaly_regions: list[dict]
    notes: str = "Generic visual change/structural-similarity analysis. Not a trained defect classifier."


def generate_inspection_report(inspection_id: str, asset_id: str, timestamp: float,
                                 reference: np.ndarray, current: np.ndarray) -> InspectionReport:
    """Ties preprocessing + registration + change detection + SSIM + contour
    scoring into one real, end-to-end inspection result."""
    change = change_detection(reference, current)
    mean_ssim, _ = structural_similarity(preprocess(reference), preprocess(current))
    regions = contour_regions(change["change_mask"])
    return InspectionReport(
        inspection_id=inspection_id,
        asset_id=asset_id,
        timestamp=timestamp,
        change_score=change["change_score"],
        mean_ssim=mean_ssim,
        anomaly_regions=[{"bbox": r["bbox"], "area_px": r["area_px"], "label": "VISUAL ANOMALY REGION"} for r in regions],
    )


class DefectDetector:
    """Model adapter interface for a future specialized aerospace-defect model
    (crack/corrosion/dent classifier). No implementation exists yet because no
    appropriate training dataset is available locally — this class documents
    the contract a trained model must satisfy to plug into the inspection
    pipeline, and calling it raises rather than pretending to work."""

    model_name = "UNIMPLEMENTED — requires specialized aerospace defect dataset"

    def detect(self, image: np.ndarray, roi: Optional[ROI] = None) -> list[dict]:
        raise NotImplementedError(
            "No specialized aircraft-defect model is available. "
            "Use change_detection() for generic before/after visual comparison instead."
        )
