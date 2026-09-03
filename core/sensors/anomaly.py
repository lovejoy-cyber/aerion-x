"""Real anomaly-detection algorithms over telemetry streams.

Z-score, rolling-statistics threshold, and CUSUM change-point detection are pure
NumPy and always available. IsolationForestDetector wraps scikit-learn and is
optional — imported lazily so this module still loads while sklearn installs.

Every result carries score, threshold, timestamp, and the measurable reason —
never an invented accuracy number.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.interfaces import AnomalyDetector
from core.sensors.telemetry import TelemetryStream


@dataclass
class AnomalyResult:
    timestamp: float
    signal_name: str
    value: float
    score: float
    threshold: float
    algorithm: str
    reason: str


class ZScoreDetector(AnomalyDetector):
    """Flags points more than `threshold` standard deviations from the stream mean."""

    algorithm_name = "z-score"

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold
        self._mean = 0.0
        self._std = 1.0

    def fit(self, values: list[float]) -> None:
        arr = np.asarray(values, dtype=float)
        self._mean = float(arr.mean())
        self._std = float(arr.std()) or 1.0

    def score(self, values: list[float]) -> list[float]:
        arr = np.asarray(values, dtype=float)
        return list(np.abs((arr - self._mean) / self._std))

    def detect(self, stream: TelemetryStream) -> list[AnomalyResult]:
        self.fit(stream.values())
        scores = self.score(stream.values())
        results = []
        for reading, s in zip(stream.readings, scores):
            if s >= self.threshold:
                results.append(AnomalyResult(
                    timestamp=reading.timestamp, signal_name=stream.signal_name, value=reading.value,
                    score=s, threshold=self.threshold, algorithm=self.algorithm_name,
                    reason=f"{s:.2f} std devs from mean {self._mean:.3f}",
                ))
        return results


class RollingThresholdDetector(AnomalyDetector):
    """Flags points outside `n_std` standard deviations of a trailing rolling window."""

    algorithm_name = "rolling-threshold"

    def __init__(self, window: int = 10, n_std: float = 3.0):
        self.window = window
        self.n_std = n_std

    def fit(self, values: list[float]) -> None:
        pass  # stateless — computed per-call over the trailing window

    def score(self, values: list[float]) -> list[float]:
        arr = np.asarray(values, dtype=float)
        scores = np.zeros(len(arr))
        for i in range(len(arr)):
            start = max(0, i - self.window)
            window_vals = arr[start:i] if i > 0 else arr[:1]
            if len(window_vals) < 2:
                continue
            mean, std = window_vals.mean(), window_vals.std() or 1.0
            scores[i] = abs(arr[i] - mean) / std
        return list(scores)

    def detect(self, stream: TelemetryStream) -> list[AnomalyResult]:
        values = stream.values()
        scores = self.score(values)
        results = []
        for reading, s in zip(stream.readings, scores):
            if s >= self.n_std:
                results.append(AnomalyResult(
                    timestamp=reading.timestamp, signal_name=stream.signal_name, value=reading.value,
                    score=s, threshold=self.n_std, algorithm=self.algorithm_name,
                    reason=f"{s:.2f} std devs from trailing {self.window}-sample window",
                ))
        return results


def cusum_change_points(values: list[float], threshold: float = 5.0, drift: float = 0.5) -> list[int]:
    """Classic CUSUM change-point detection. Returns indices where a sustained
    shift in the mean is detected. `threshold` and `drift` are in units of the
    signal itself (caller normalizes if needed)."""
    arr = np.asarray(values, dtype=float)
    mean = arr[0]
    pos, neg = 0.0, 0.0
    change_points = []
    for i in range(1, len(arr)):
        diff = arr[i] - mean
        pos = max(0.0, pos + diff - drift)
        neg = min(0.0, neg + diff + drift)
        if pos > threshold or -neg > threshold:
            change_points.append(i)
            pos, neg = 0.0, 0.0
            mean = arr[i]
    return change_points


class IsolationForestDetector(AnomalyDetector):
    """Wraps sklearn's IsolationForest. Import is lazy: this class only requires
    scikit-learn to be installed at the moment `fit`/`score` is actually called."""

    algorithm_name = "isolation-forest"

    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.contamination = contamination
        self.random_state = random_state
        self._model = None

    def fit(self, values: list[float]) -> None:
        from sklearn.ensemble import IsolationForest
        arr = np.asarray(values, dtype=float).reshape(-1, 1)
        self._model = IsolationForest(contamination=self.contamination, random_state=self.random_state)
        self._model.fit(arr)

    def score(self, values: list[float]) -> list[float]:
        arr = np.asarray(values, dtype=float).reshape(-1, 1)
        raw = self._model.decision_function(arr)  # higher = more normal
        return list(-raw)  # flip so higher = more anomalous, consistent with other detectors

    def detect(self, stream: TelemetryStream, score_threshold: float = 0.0) -> list[AnomalyResult]:
        self.fit(stream.values())
        scores = self.score(stream.values())
        results = []
        for reading, s in zip(stream.readings, scores):
            if s >= score_threshold:
                results.append(AnomalyResult(
                    timestamp=reading.timestamp, signal_name=stream.signal_name, value=reading.value,
                    score=s, threshold=score_threshold, algorithm=self.algorithm_name,
                    reason="isolation forest anomaly score above threshold",
                ))
        return results
