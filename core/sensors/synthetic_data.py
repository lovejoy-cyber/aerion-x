"""Deterministic synthetic telemetry with a known, injected anomaly — used only
to validate that the anomaly algorithms actually detect what they're supposed to.
Always tagged DataProvenance.SYNTHETIC; never presented as real sensor evidence.
"""
from __future__ import annotations

import numpy as np

from core.sensors.telemetry import DataProvenance, SensorReading, TelemetryStream


def generate_vibration_stream(
    n_samples: int = 200,
    sample_rate_hz: float = 10.0,
    baseline: float = 2.0,
    noise_std: float = 0.15,
    anomaly_start: int = 140,
    anomaly_len: int = 8,
    anomaly_magnitude: float = 6.0,
    seed: int = 7,
) -> tuple[TelemetryStream, list[int]]:
    """Returns (stream, injected_anomaly_indices) so tests can assert the
    detector actually finds the indices we injected, not just "some" anomaly."""
    rng = np.random.default_rng(seed)
    values = baseline + rng.normal(0, noise_std, n_samples)

    anomaly_indices = list(range(anomaly_start, min(anomaly_start + anomaly_len, n_samples)))
    for i in anomaly_indices:
        values[i] += anomaly_magnitude

    readings = [
        SensorReading(timestamp=i / sample_rate_hz, signal_name="vibration", value=float(v), unit="mm/s")
        for i, v in enumerate(values)
    ]
    stream = TelemetryStream(
        stream_id="synthetic:vibration_v1",
        signal_name="vibration",
        unit="mm/s",
        provenance=DataProvenance.SYNTHETIC,
        readings=readings,
    )
    return stream, anomaly_indices
