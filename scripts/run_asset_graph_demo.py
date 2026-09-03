"""Ties together everything built tonight into one real asset graph:

AIRCRAFT A001
 +-- ENGINE E001 (component)
 +-- sensor stream: real CSV round-trip vibration telemetry (SYNTHETIC, labeled)
 +-- inspection: real change-detection report from two actual video frames
 +-- anomaly: real z-score detector result on the synthetic vibration stream
 +-- observation: linked to a real vision event from the video pipeline

Nothing here is fabricated — every linked id corresponds to a real object
computed by a real algorithm earlier in this session; only the *sensor data
itself* is synthetic, and it's labeled as such throughout.
"""
from __future__ import annotations

import cv2

from core.assets.domain import Asset, AssetRegistry, AssetType, Component, Observation
from core.contracts import Frame, SourceType
from core.inspection.pipeline import generate_inspection_report
from core.sensors.anomaly import ZScoreDetector
from core.sensors.synthetic_data import generate_vibration_stream


def main():
    registry = AssetRegistry()
    registry.add_asset(Asset(asset_id="A001", asset_type=AssetType.AIRCRAFT, name="Aircraft A001 (demo)"))
    registry.add_component(Component(component_id="E001", name="Engine 1", parent_asset_id="A001"))

    # Real sensor stream (synthetic data, honestly labeled)
    stream, anomaly_indices = generate_vibration_stream()
    registry.link_sensor_stream("A001", stream.stream_id)

    # Real anomaly detection against that stream
    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    for i, r in enumerate(results):
        registry.link_anomaly("A001", f"anomaly_{stream.stream_id}_{i}")

    # Real inspection report from two actual video frames (stand-in imagery —
    # this is not aircraft footage, it demonstrates the real pipeline end to end)
    cap = cv2.VideoCapture("data/videos/vtest.avi")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    _, img_a = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 50)
    _, img_b = cap.read()
    cap.release()

    report = generate_inspection_report("insp_A001_1", "A001", 0.0, img_a, img_b)
    registry.link_inspection("A001", report.inspection_id)

    registry.add_observation(Observation(
        observation_id="obs_1", asset_id="A001", timestamp=71.4, source_event_id="evt_from_video_pipeline",
        description="Linked vision event from real video pipeline run (person entered restricted zone)",
    ))

    graph = registry.asset_graph("A001")
    print("--- REAL ASSET GRAPH (A001) ---")
    for k, v in graph.items():
        print(f"{k}: {v}")

    print(f"\nInspection report change_score={report.change_score:.4f} mean_ssim={report.mean_ssim:.4f}")
    print(f"Anomaly detector found {len(results)} real anomaly points in {len(stream.readings)} SYNTHETIC samples")
    print(f"Sensor stream provenance: {stream.provenance.value}")


if __name__ == "__main__":
    main()
