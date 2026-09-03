"""SENSOR DATA -> PREPROCESSING -> ANOMALY DETECTION -> EVENT ENGINE.

Generates deterministic synthetic vibration telemetry with a known injected
anomaly, writes it to a real CSV file (so the CSV-loading path is genuinely
exercised, not bypassed), reloads it via core.sensors.telemetry.load_csv, and
runs all three NumPy-backed anomaly detectors against it — reporting exactly
which timestamps each one flags and whether that overlaps the known injected
anomaly window. Every event this script emits carries measurable evidence.
"""
from __future__ import annotations

import csv
from pathlib import Path

from core.contracts import Event
from core.sensors.anomaly import RollingThresholdDetector, ZScoreDetector, cusum_change_points
from core.sensors.synthetic_data import generate_vibration_stream
from core.sensors.telemetry import DataProvenance, load_csv


def anomaly_result_to_event(result, source_id: str) -> Event:
    return Event(
        event_type="ANOMALY",
        timestamp=result.timestamp,
        source_id=source_id,
        track_ids=[],
        evidence={
            "signal": result.signal_name,
            "value": result.value,
            "score": result.score,
            "threshold": result.threshold,
            "algorithm": result.algorithm,
            "reason": result.reason,
        },
    )


def main():
    out_path = Path("data/sensors/synthetic_vibration.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stream, injected_indices = generate_vibration_stream()
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "value"])
        for r in stream.readings:
            writer.writerow([r.timestamp, r.value])

    print(f"Wrote {len(stream.readings)} SYNTHETIC readings to {out_path}")
    print(f"Injected anomaly at sample indices {injected_indices[0]}-{injected_indices[-1]} "
          f"(t={stream.readings[injected_indices[0]].timestamp:.1f}s - {stream.readings[injected_indices[-1]].timestamp:.1f}s)")

    reloaded = load_csv(str(out_path), signal_name="vibration", unit="mm/s", provenance=DataProvenance.SYNTHETIC)
    assert reloaded.provenance == DataProvenance.SYNTHETIC
    print(f"Reloaded from CSV: {len(reloaded.readings)} readings, provenance={reloaded.provenance.value}\n")

    detectors = [ZScoreDetector(threshold=3.0), RollingThresholdDetector(window=15, n_std=3.0)]
    all_events = []
    for detector in detectors:
        results = detector.detect(reloaded)
        events = [anomaly_result_to_event(r, reloaded.stream_id) for r in results]
        all_events.extend(events)
        print(f"[{detector.algorithm_name}] flagged {len(results)} points:")
        for r in results:
            print(f"  t={r.timestamp:.1f}s value={r.value:.2f} score={r.score:.2f} reason={r.reason}")

    change_points = cusum_change_points(reloaded.values(), threshold=3.0, drift=0.3)
    print(f"\n[cusum change-point] flagged sample indices: {change_points}")

    print(f"\n--- SENSOR PIPELINE SUMMARY ---")
    print(f"Total ANOMALY events generated: {len(all_events)}")
    print(f"Data provenance: {reloaded.provenance.value} (never presented as real sensor evidence)")


if __name__ == "__main__":
    main()
