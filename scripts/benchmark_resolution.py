"""Real before/after performance test: does a smaller YOLO input resolution
actually speed up CPU inference on this machine, and by how much? Runs both
configurations against the same 40 real video frames and reports measured
latency — not an estimate.
"""
from __future__ import annotations

import time

from ultralytics import YOLO

from adapters.video.file_source import VideoFileSource


def benchmark(imgsz: int, frames: list, model: YOLO) -> dict:
    latencies = []
    total_detections = 0
    for frame in frames:
        t0 = time.perf_counter()
        results = model.predict(frame.image, verbose=False, conf=0.35, imgsz=imgsz)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        total_detections += len(results[0].boxes)
    return {
        "imgsz": imgsz,
        "avg_ms": sum(latencies) / len(latencies),
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "total_detections": total_detections,
    }


def main():
    source = VideoFileSource("data/videos/vtest.avi")
    frames = []
    for i, frame in enumerate(source.frames()):
        if i >= 40:
            break
        frames.append(frame)
    source.close()

    model = YOLO("yolov8n.pt")

    print("Warming up (first inference includes model JIT/graph setup, excluded from comparison)...")
    model.predict(frames[0].image, verbose=False)

    result_640 = benchmark(640, frames, model)
    result_320 = benchmark(320, frames, model)

    print(f"\n--- RESOLUTION BENCHMARK (measured, {len(frames)} real frames, same model, same hardware) ---")
    for r in (result_640, result_320):
        print(f"imgsz={r['imgsz']}: avg={r['avg_ms']:.1f}ms  min={r['min_ms']:.1f}ms  max={r['max_ms']:.1f}ms  "
              f"detections_total={r['total_detections']}  implied_fps={1000/r['avg_ms']:.2f}")

    speedup = result_640["avg_ms"] / result_320["avg_ms"]
    detection_drop = result_640["total_detections"] - result_320["total_detections"]
    print(f"\nSpeedup at imgsz=320 vs 640: {speedup:.2f}x")
    print(f"Detection count change: {result_320['total_detections']} vs {result_640['total_detections']} "
          f"({'fewer' if detection_drop > 0 else 'more or equal'} at lower res — real accuracy/speed tradeoff, not hidden)")


if __name__ == "__main__":
    main()
