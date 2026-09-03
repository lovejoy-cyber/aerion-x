from core.assets.domain import (
    Asset,
    AssetRegistry,
    AssetType,
    Component,
    MaintenanceRecord,
    Observation,
)


def test_asset_registry_links_components():
    registry = AssetRegistry()
    aircraft = Asset(asset_id="ac1", asset_type=AssetType.AIRCRAFT, name="Test Aircraft")
    registry.add_asset(aircraft)
    registry.add_component(Component(component_id="c1", name="Left Wing", parent_asset_id="ac1"))

    stored = registry.get_asset("ac1")
    assert len(stored.components) == 1
    assert stored.components[0].name == "Left Wing"


def test_maintenance_record_links_to_asset():
    registry = AssetRegistry()
    registry.add_asset(Asset(asset_id="v1", asset_type=AssetType.GROUND_VEHICLE, name="Tug 1"))
    registry.add_maintenance_record(MaintenanceRecord(
        record_id="m1", asset_id="v1", timestamp=0.0, description="Oil change", performed_by="tech_1"
    ))
    asset = registry.get_asset("v1")
    assert "m1" in asset.maintenance_record_ids


def test_observation_links_to_asset_and_optional_event():
    registry = AssetRegistry()
    registry.add_asset(Asset(asset_id="w1", asset_type=AssetType.WORKER, name="Worker A"))
    registry.add_observation(Observation(
        observation_id="o1", asset_id="w1", timestamp=1.0, source_event_id="evt_42",
        description="Entered restricted zone",
    ))
    asset = registry.get_asset("w1")
    assert "o1" in asset.observation_ids


def test_asset_graph_links_sensor_inspection_and_anomaly():
    registry = AssetRegistry()
    registry.add_asset(Asset(asset_id="ac1", asset_type=AssetType.AIRCRAFT, name="A1"))
    registry.link_sensor_stream("ac1", "stream_1")
    registry.link_inspection("ac1", "insp_1")
    registry.link_anomaly("ac1", "anom_1")
    registry.link_anomaly("ac1", "anom_1")  # duplicate link should not double up

    graph = registry.asset_graph("ac1")
    assert graph["sensor_stream_ids"] == ["stream_1"]
    assert graph["inspection_ids"] == ["insp_1"]
    assert graph["anomaly_ids"] == ["anom_1"]


def test_assets_by_type_filters_correctly():
    registry = AssetRegistry()
    registry.add_asset(Asset(asset_id="ac1", asset_type=AssetType.AIRCRAFT, name="A1"))
    registry.add_asset(Asset(asset_id="ac2", asset_type=AssetType.AIRCRAFT, name="A2"))
    registry.add_asset(Asset(asset_id="e1", asset_type=AssetType.ENGINE, name="E1"))

    aircraft = registry.assets_by_type(AssetType.AIRCRAFT)
    assert len(aircraft) == 2
    assert all(a.asset_type == AssetType.AIRCRAFT for a in aircraft)
