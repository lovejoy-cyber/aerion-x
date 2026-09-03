"""Validates anomaly detectors actually find an injected anomaly in deterministic
synthetic data — and don't fire constantly on normal data. Uses only NumPy-backed
detectors (no sklearn dependency) so these run regardless of scikit-learn install
status.
"""
from core.sensors.anomaly import RollingThresholdDetector, ZScoreDetector, cusum_change_points
from core.sensors.synthetic_data import generate_vibration_stream
from core.sensors.telemetry import DataProvenance


def test_synthetic_stream_is_labeled_synthetic():
    stream, _ = generate_vibration_stream()
    assert stream.provenance == DataProvenance.SYNTHETIC


def test_zscore_detects_injected_anomaly():
    stream, anomaly_indices = generate_vibration_stream()
    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    detected_timestamps = {r.timestamp for r in results}
    injected_timestamps = {stream.readings[i].timestamp for i in anomaly_indices}
    assert detected_timestamps & injected_timestamps, "z-score detector missed the injected anomaly entirely"


def test_zscore_does_not_flag_normal_baseline_only():
    stream, anomaly_indices = generate_vibration_stream(anomaly_magnitude=0.0)  # no anomaly injected
    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    assert len(results) <= 2  # a few borderline points from noise is acceptable; a flood is not


def test_rolling_threshold_detects_injected_anomaly():
    stream, anomaly_indices = generate_vibration_stream()
    detector = RollingThresholdDetector(window=15, n_std=3.0)
    results = detector.detect(stream)
    detected_timestamps = {r.timestamp for r in results}
    injected_timestamps = {stream.readings[i].timestamp for i in anomaly_indices}
    assert detected_timestamps & injected_timestamps


def test_cusum_flags_change_near_injected_anomaly():
    stream, anomaly_indices = generate_vibration_stream()
    change_points = cusum_change_points(stream.values(), threshold=3.0, drift=0.3)
    assert change_points, "CUSUM found no change points at all"
    nearest = min(abs(cp - anomaly_indices[0]) for cp in change_points)
    assert nearest <= 5, f"nearest CUSUM change point was {nearest} samples from the injected anomaly start"


def test_every_anomaly_result_carries_measurable_evidence():
    stream, _ = generate_vibration_stream()
    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    assert results
    for r in results:
        assert r.score > 0
        assert r.threshold > 0
        assert r.timestamp is not None
        assert r.signal_name == "vibration"
        assert r.algorithm == "z-score"
        assert r.reason  # a stated, measurable reason — never a bare flag
