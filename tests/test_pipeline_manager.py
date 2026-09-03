"""Real threaded pipeline manager tests — actually starts a background thread,
actually runs YOLO inference (synthetic source, small frame count to keep the
test fast), actually writes to a real SQLite file, actually waits for
completion. No mocking of the pipeline itself.
"""
import os
import tempfile
import time

from backend.services import PipelineManager


def _wait_until(predicate, timeout=30.0, interval=0.1):
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_pipeline_runs_synthetic_source_to_completion():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.sqlite3")
        manager = PipelineManager(db_path=db_path)

        run_id = manager.start(source_type="synthetic", max_frames=20)
        assert run_id
        assert manager.status.status in ("RUNNING", "COMPLETED")

        completed = _wait_until(lambda: manager.status.status in ("COMPLETED", "ERROR"), timeout=60.0)
        assert completed, f"pipeline did not finish in time, status={manager.status.status}"
        assert manager.join(timeout=30.0), "background thread did not actually exit"
        assert manager.status.status == "COMPLETED"
        assert manager.status.frames_processed == 20
        assert manager.status.error_message is None


def test_pipeline_cannot_start_twice_concurrently():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.sqlite3")
        manager = PipelineManager(db_path=db_path)
        manager.start(source_type="synthetic", max_frames=50)
        try:
            raised = False
            try:
                manager.start(source_type="synthetic", max_frames=50)
            except RuntimeError:
                raised = True
            assert raised
        finally:
            manager.stop()
            manager.join(timeout=30.0)


def test_pipeline_stop_signal_halts_processing_early():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.sqlite3")
        manager = PipelineManager(db_path=db_path)
        manager.start(source_type="synthetic", max_frames=10000)  # would run "forever"
        _wait_until(lambda: manager.status.frames_processed >= 1, timeout=30.0)
        manager.stop()
        stopped = _wait_until(lambda: manager.status.status == "STOPPED", timeout=30.0)
        assert stopped
        manager.join(timeout=30.0)
        assert manager.status.frames_processed < 10000


def test_pipeline_broadcasts_status_updates_to_registered_callback():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.sqlite3")
        manager = PipelineManager(db_path=db_path)
        received = []
        manager.on_broadcast(lambda msg: received.append(msg))

        manager.start(source_type="synthetic", max_frames=10)
        _wait_until(lambda: manager.status.status == "COMPLETED", timeout=60.0)
        manager.join(timeout=30.0)

        status_messages = [m for m in received if m["type"] == "status"]
        assert len(status_messages) == 10
        assert all("fps" in m and "latency_ms" in m for m in status_messages)
