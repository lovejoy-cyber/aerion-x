from core.model_lab.evaluation import BoxAnnotation, evaluate, iou
from core.model_lab.registry import ModelRecord, ModelRegistry


def test_iou_of_identical_boxes_is_one():
    box = (10.0, 10.0, 50.0, 50.0)
    assert iou(box, box) == 1.0


def test_iou_of_disjoint_boxes_is_zero():
    assert iou((0, 0, 10, 10), (100, 100, 110, 110)) == 0.0


def test_evaluate_reports_not_available_without_ground_truth():
    predictions = [BoxAnnotation("person", (0, 0, 10, 10))]
    result = evaluate(predictions, ground_truth=None)
    assert result.status == "EVALUATION DATASET: NOT AVAILABLE"
    assert result.precision is None


def test_evaluate_computes_real_metrics_with_perfect_match():
    box = (10.0, 10.0, 50.0, 50.0)
    predictions = [BoxAnnotation("person", box)]
    ground_truth = [BoxAnnotation("person", box)]
    result = evaluate(predictions, ground_truth)
    assert result.status == "OK"
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0
    assert result.mean_iou == 1.0


def test_evaluate_penalizes_false_positive_and_false_negative():
    predictions = [BoxAnnotation("person", (0, 0, 10, 10)), BoxAnnotation("person", (500, 500, 510, 510))]
    ground_truth = [BoxAnnotation("person", (0, 0, 10, 10)), BoxAnnotation("person", (1000, 1000, 1010, 1010))]
    result = evaluate(predictions, ground_truth)
    assert result.confusion_matrix["true_positives"] == 1
    assert result.confusion_matrix["false_positives"] == 1
    assert result.confusion_matrix["false_negatives"] == 1


def test_model_registry_stores_and_retrieves_by_name_version():
    registry = ModelRegistry()
    record = ModelRecord(
        name="YOLOv8n", version="8.4.0", framework="PyTorch", task="object_detection",
        classes=["person", "car"], input_resolution="640x640",
        weights_source="https://example.test/yolov8n.pt", license="AGPL-3.0", hardware="CPU",
    )
    registry.register(record)
    fetched = registry.get("YOLOv8n", "8.4.0")
    assert fetched is not None
    assert fetched.classes == ["person", "car"]
