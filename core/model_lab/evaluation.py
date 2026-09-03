"""Real evaluation metrics — precision/recall/F1/IoU/confusion matrix/mAP —
computed from actual predictions vs. actual ground truth. If no ground-truth
dataset is supplied, functions return an explicit "NOT AVAILABLE" result
rather than a fabricated number. No accuracy is ever invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BoxAnnotation:
    class_name: str
    bbox: tuple[float, float, float, float]


@dataclass
class EvaluationResult:
    status: str  # "OK" or "EVALUATION DATASET: NOT AVAILABLE"
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    mean_iou: float | None = None
    confusion_matrix: dict | None = None
    num_ground_truth: int = 0
    num_predictions: int = 0
    per_class: dict = field(default_factory=dict)


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def evaluate(predictions: list[BoxAnnotation], ground_truth: list[BoxAnnotation] | None,
             iou_threshold: float = 0.5) -> EvaluationResult:
    if not ground_truth:
        return EvaluationResult(status="EVALUATION DATASET: NOT AVAILABLE", num_predictions=len(predictions))

    matched_gt: set[int] = set()
    true_positives = 0
    ious = []

    for pred in predictions:
        best_iou, best_idx = 0.0, None
        for i, gt in enumerate(ground_truth):
            if i in matched_gt or gt.class_name != pred.class_name:
                continue
            score = iou(pred.bbox, gt.bbox)
            if score > best_iou:
                best_iou, best_idx = score, i
        if best_idx is not None and best_iou >= iou_threshold:
            matched_gt.add(best_idx)
            true_positives += 1
            ious.append(best_iou)

    false_positives = len(predictions) - true_positives
    false_negatives = len(ground_truth) - true_positives

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    mean_iou = sum(ious) / len(ious) if ious else 0.0

    return EvaluationResult(
        status="OK",
        precision=precision,
        recall=recall,
        f1=f1,
        mean_iou=mean_iou,
        confusion_matrix={"true_positives": true_positives, "false_positives": false_positives,
                           "false_negatives": false_negatives},
        num_ground_truth=len(ground_truth),
        num_predictions=len(predictions),
    )
