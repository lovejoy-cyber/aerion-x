"""Service layer: wraps the core intelligence engine for the API/WebSocket
layer. PipelineManager runs the real detection/tracking/temporal/zone/safety
chain in a background thread so the API never blocks on a 227ms/frame CPU
inference call. Events are persisted to SQLite as they're produced and also
pushed to any registered broadcast callback (used by the WebSocket layer) —
the intelligence core itself never imports FastAPI or sqlite3.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from adapters.synthetic.synthetic_source import SyntheticSource
from adapters.video.file_source import VideoFileSource
from backend import repositories
from backend.db import get_connection, init_db
from core.config import settings
from core.cv.detector import YoloDetector
from core.events.event_engine import EventEngine
from core.safety.aviation_ops import AviationOpsEngine, OperationsConfig
from core.safety.safety_engine import SafetyThresholds, WorkerSafetyEngine
from core.spatial.zones import Zone, ZoneRegistry
from core.temporal.state_engine import update_track_state
from core.tracking.tracker import CentroidIoUTracker


@dataclass
class PipelineStatus:
    run_id: str
    status: str = "IDLE"  # IDLE | RUNNING | STOPPED | COMPLETED | ERROR
    source_id: str = ""
    frames_processed: int = 0
    fps: float = 0.0
    last_inference_ms: float = 0.0
    active_tracks: int = 0
    error_message: Optional[str] = None
    started_at: Optional[float] = None


class PipelineManager:
    """One pipeline run at a time, by design — this is a monitoring/inspection
    tool for a single camera/video source, not a multi-tenant video platform.
    Real thread, real stop signal, real DB writes, real broadcast hook."""

    def __init__(self, db_path: str = "data/db/aerionx.sqlite3"):
        self.db_path = db_path
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.status = PipelineStatus(run_id="")
        self._broadcast_callbacks: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()

    def on_broadcast(self, callback: Callable[[dict], None]) -> None:
        self._broadcast_callbacks.append(callback)

    def _broadcast(self, message: dict) -> None:
        for cb in list(self._broadcast_callbacks):
            try:
                cb(message)
            except Exception:
                pass  # a slow/broken client must never take down the pipeline thread

    def start(self, source_type: str, path: Optional[str] = None, max_frames: Optional[int] = None,
              zone: bool = False) -> str:
        # Validated synchronously, before any thread is spawned — this used to
        # be checked only inside _run() on the background thread, which meant
        # start() returned success (run_id + status="RUNNING") for a request
        # that was always going to fail moments later. Caught by an API test
        # asserting an invalid source_type gets a 400, not a 200.
        if source_type not in ("video", "synthetic"):
            raise ValueError(f"Unsupported source_type: {source_type}")
        if source_type == "video" and not path:
            raise ValueError("path is required for source_type=video")

        with self._lock:
            if self.status.status == "RUNNING":
                raise RuntimeError("A pipeline is already running. Stop it before starting another.")
            run_id = str(uuid.uuid4())
            self._stop_event.clear()
            self.status = PipelineStatus(run_id=run_id, status="RUNNING", started_at=time.time())
            self._thread = threading.Thread(
                target=self._run, args=(run_id, source_type, path, max_frames, zone), daemon=True,
            )
            self._thread.start()
            return run_id

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> bool:
        """Blocks until the background thread has actually exited (including
        its `finally: conn.close()`) — not just until `status` looks done.
        Polling status alone raced with connection cleanup on Windows, where a
        SQLite file stays locked until close() truly returns; callers that need
        the DB file free afterward (tests, CLI tools) must join, not poll."""
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self, run_id: str, source_type: str, path: Optional[str], max_frames: Optional[int], zone: bool) -> None:
        conn = get_connection(self.db_path)
        init_db(conn)

        try:
            if source_type == "synthetic":
                source = SyntheticSource(num_frames=max_frames or 150)
            elif source_type == "video":
                if not path:
                    raise ValueError("path is required for source_type=video")
                source = VideoFileSource(path)
            else:
                raise ValueError(f"Unsupported source_type: {source_type}")

            self.status.source_id = source.source_id
            repositories.create_pipeline_run(conn, run_id, source.source_id)

            detector = YoloDetector(confidence_threshold=settings.detector_confidence_threshold)
            tracker = CentroidIoUTracker(
                iou_threshold=settings.tracker_iou_threshold,
                max_missed_frames=settings.tracker_max_missed_frames,
                max_centroid_distance=settings.tracker_max_centroid_distance,
            )
            zones = ZoneRegistry()
            if zone:
                zones.add(Zone("zone_1", "RESTRICTED ZONE", [(400, 0), (768, 0), (768, 576), (400, 576)]))
            event_engine = EventEngine(zones, stationary_alert_seconds=settings.stationary_alert_seconds)
            safety = WorkerSafetyEngine(zones, SafetyThresholds(restricted_zone_ids=("zone_1",) if zone else ()))
            ops = AviationOpsEngine(zones, OperationsConfig())

            frame_count = 0
            t_start = time.monotonic()

            for frame in source.frames():
                if self._stop_event.is_set():
                    self.status.status = "STOPPED"
                    break
                if max_frames and frame_count >= max_frames:
                    break

                detections = detector.detect(frame)
                detections = tracker.update(detections, frame.frame_id, frame.timestamp)

                state_changed = {}
                for track in tracker.active_tracks():
                    state_changed[track.track_id] = update_track_state(track, frame.timestamp)

                events = []
                events += event_engine.process(tracker.active_tracks(), source.source_id, frame.timestamp, state_changed)
                events += safety.process(tracker.active_tracks(), source.source_id, frame.timestamp)
                events += ops.process(tracker.active_tracks(), source.source_id, frame.timestamp)

                if events:
                    repositories.save_events(conn, events)
                    for e in events:
                        self._broadcast({"type": "event", "event_type": e.event_type, "timestamp": e.timestamp,
                                          "track_ids": e.track_ids, "zone_id": e.zone_id, "severity": e.severity.value})

                frame_count += 1
                elapsed = time.monotonic() - t_start
                self.status.frames_processed = frame_count
                self.status.fps = frame_count / elapsed if elapsed > 0 else 0.0
                self.status.last_inference_ms = detector.last_inference_ms
                self.status.active_tracks = len(tracker.active_tracks())

                self._broadcast({"type": "status", "frames_processed": frame_count, "fps": self.status.fps,
                                  "latency_ms": detector.last_inference_ms, "active_tracks": self.status.active_tracks})

                repositories.update_pipeline_run(conn, run_id, status="RUNNING", frames_processed=frame_count)

            source.close()
            if self.status.status != "STOPPED":
                self.status.status = "COMPLETED"
            repositories.update_pipeline_run(conn, run_id, status=self.status.status,
                                              frames_processed=frame_count, ended=True)

        except Exception as exc:
            self.status.status = "ERROR"
            self.status.error_message = str(exc)
            repositories.update_pipeline_run(conn, run_id, status="ERROR", frames_processed=self.status.frames_processed,
                                              error_message=str(exc), ended=True)
        finally:
            conn.close()
