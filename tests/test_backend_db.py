"""Real SQLite persistence tests — an in-memory database per test, real schema,
real repository functions, real domain objects round-tripped through actual
INSERT/SELECT, not mocked."""
import pytest

from backend import db, repositories
from core.assets.domain import Asset, AssetType
from core.contracts import Event, Severity
from core.correlation.correlation_engine import CorrelationEngine
from core.inspection.pipeline import InspectionReport
from core.model_lab.registry import ModelRecord
from core.sensors.anomaly import ZScoreDetector
from core.sensors.synthetic_data import generate_vibration_stream


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.init_db(connection)
    yield connection
    connection.close()


def test_schema_creates_all_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"assets", "events", "sensor_streams", "sensor_readings", "anomaly_results",
                "inspections", "correlations", "models", "pipeline_runs"}
    assert expected.issubset(tables)


def test_save_and_get_asset_round_trip(conn):
    asset = Asset(asset_id="A001", asset_type=AssetType.AIRCRAFT, name="Test Aircraft")
    repositories.save_asset(conn, asset)
    fetched = repositories.get_asset(conn, "A001")
    assert fetched["asset_id"] == "A001"
    assert fetched["asset_type"] == "AIRCRAFT"
    assert fetched["name"] == "Test Aircraft"


def test_save_and_list_events_preserves_evidence_json(conn):
    event = Event(event_type="ZONE_ENTER", timestamp=1.5, source_id="video:test.mp4",
                  track_ids=[3, 7], severity=Severity.WARNING, evidence={"position": [100, 200]})
    repositories.save_event(conn, event)
    events = repositories.list_events(conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "ZONE_ENTER"
    assert events[0]["track_ids"] == [3, 7]
    assert events[0]["evidence"] == {"position": [100, 200]}


def test_save_events_batch(conn):
    events = [Event(event_type="STATE_CHANGE", timestamp=float(i), source_id="test") for i in range(5)]
    count = repositories.save_events(conn, events)
    assert count == 5
    assert len(repositories.list_events(conn)) == 5


def test_list_events_filters_by_type(conn):
    repositories.save_events(conn, [
        Event(event_type="ZONE_ENTER", timestamp=1.0, source_id="test"),
        Event(event_type="ZONE_EXIT", timestamp=2.0, source_id="test"),
    ])
    zone_enters = repositories.list_events(conn, event_type="ZONE_ENTER")
    assert len(zone_enters) == 1
    assert zone_enters[0]["event_type"] == "ZONE_ENTER"


def test_sensor_stream_and_readings_round_trip_real_synthetic_data(conn):
    stream, _ = generate_vibration_stream()
    repositories.save_sensor_stream(conn, stream)
    readings = repositories.get_sensor_readings(conn, stream.stream_id)
    assert len(readings) == len(stream.readings)
    streams = repositories.list_sensor_streams(conn)
    assert streams[0]["provenance"] == "SYNTHETIC"


def test_resaving_sensor_stream_does_not_duplicate_readings(conn):
    """Regression test: save_sensor_stream used to just INSERT readings with no
    cleanup, so calling it twice for the same stream_id (e.g. a user clicking
    'generate' twice in the GUI) silently doubled every reading."""
    stream, _ = generate_vibration_stream()
    repositories.save_sensor_stream(conn, stream)
    repositories.save_sensor_stream(conn, stream)  # same stream_id, second time
    readings = repositories.get_sensor_readings(conn, stream.stream_id)
    assert len(readings) == len(stream.readings)


def test_anomaly_results_persisted_from_real_detector(conn):
    stream, _ = generate_vibration_stream()
    repositories.save_sensor_stream(conn, stream)
    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    count = repositories.save_anomaly_results(conn, stream.stream_id, results)
    assert count == len(results)
    persisted = repositories.list_anomalies(conn, stream.stream_id)
    assert len(persisted) == len(results)
    assert persisted[0]["algorithm"] == "z-score"


def test_inspection_report_round_trip(conn):
    repositories.save_asset(conn, Asset(asset_id="A001", asset_type=AssetType.AIRCRAFT, name="A1"))
    report = InspectionReport(
        inspection_id="insp_1", asset_id="A001", timestamp=0.0,
        change_score=0.05, mean_ssim=0.91,
        anomaly_regions=[{"bbox": (0, 0, 10, 10), "area_px": 100, "label": "VISUAL ANOMALY REGION"}],
    )
    repositories.save_inspection(conn, report)
    fetched = repositories.list_inspections(conn, asset_id="A001")
    assert len(fetched) == 1
    assert fetched[0]["mean_ssim"] == 0.91
    assert fetched[0]["anomaly_regions"][0]["label"] == "VISUAL ANOMALY REGION"


def test_correlation_round_trip(conn):
    events = [
        Event(event_type="ZONE_ENTER", timestamp=10.0, source_id="video:test.mp4"),
        Event(event_type="ANOMALY", timestamp=11.0, source_id="sensor:vibration", provenance="SYNTHETIC"),
    ]
    corr_engine = CorrelationEngine(window_seconds=2.0)
    correlations = corr_engine.correlate(events)
    assert len(correlations) == 1
    repositories.save_correlation(conn, correlations[0])
    fetched = repositories.list_correlations(conn)
    assert len(fetched) == 1
    assert set(fetched[0]["event_types"]) == {"ZONE_ENTER", "ANOMALY"}


def test_model_registry_persists(conn):
    record = ModelRecord(name="YOLOv8n", version="8.4.0", framework="PyTorch", task="object_detection",
                          classes=["person", "car"], input_resolution="640x640",
                          weights_source="https://example.test/w.pt", license="AGPL-3.0", hardware="CPU")
    repositories.save_model(conn, record)
    models = repositories.list_models(conn)
    assert len(models) == 1
    assert models[0]["classes"] == ["person", "car"]


def test_pipeline_run_lifecycle(conn):
    repositories.create_pipeline_run(conn, "run_1", "video:test.mp4")
    run = repositories.get_pipeline_run(conn, "run_1")
    assert run["status"] == "RUNNING"

    repositories.update_pipeline_run(conn, "run_1", status="COMPLETED", frames_processed=100, ended=True)
    run = repositories.get_pipeline_run(conn, "run_1")
    assert run["status"] == "COMPLETED"
    assert run["frames_processed"] == 100
    assert run["ended_at"] is not None


def test_end_to_end_sensor_to_database_retrieval(conn):
    """REAL SENSOR INPUT -> ANOMALY DETECTION -> DATABASE -> RETRIEVAL, all real
    objects and real SQL, no mocking."""
    stream, injected_indices = generate_vibration_stream()
    repositories.save_sensor_stream(conn, stream)

    detector = ZScoreDetector(threshold=3.0)
    results = detector.detect(stream)
    repositories.save_anomaly_results(conn, stream.stream_id, results)

    persisted_anomalies = repositories.list_anomalies(conn, stream.stream_id)
    injected_timestamps = {stream.readings[i].timestamp for i in injected_indices}
    persisted_timestamps = {a["timestamp"] for a in persisted_anomalies}
    assert injected_timestamps & persisted_timestamps, "injected anomaly did not survive the DB round trip"
