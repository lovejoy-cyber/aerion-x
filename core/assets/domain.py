"""Engineering asset domain model — independent of GUI/backend.

Assets (aircraft, engines, drones, vehicles, workers, equipment, machines,
pipelines, infrastructure) accumulate observations, inspections, sensor
streams, anomalies, events, and maintenance records over time. Aircraft is the
first-class domain per the project brief; the others share the same shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AssetType(str, Enum):
    AIRCRAFT = "AIRCRAFT"
    ENGINE = "ENGINE"
    DRONE = "DRONE"
    GROUND_VEHICLE = "GROUND_VEHICLE"
    WORKER = "WORKER"
    EQUIPMENT = "EQUIPMENT"
    MACHINE = "MACHINE"
    PIPELINE = "PIPELINE"
    INFRASTRUCTURE = "INFRASTRUCTURE"


@dataclass
class Component:
    component_id: str
    name: str
    parent_asset_id: str


@dataclass
class MaintenanceRecord:
    record_id: str
    asset_id: str
    timestamp: float
    description: str
    performed_by: str


@dataclass
class Observation:
    observation_id: str
    asset_id: str
    timestamp: float
    source_event_id: str | None  # links back to a core.contracts.Event, if vision-derived
    description: str


@dataclass
class Asset:
    asset_id: str
    asset_type: AssetType
    name: str
    components: list[Component] = field(default_factory=list)
    sensor_stream_ids: list[str] = field(default_factory=list)
    inspection_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    anomaly_ids: list[str] = field(default_factory=list)
    maintenance_record_ids: list[str] = field(default_factory=list)


class AssetRegistry:
    """In-memory registry. A real backend swaps this for a DB-backed repository
    without changing any caller — that's the whole point of keeping this
    independent of persistence and GUI."""

    def __init__(self):
        self._assets: dict[str, Asset] = {}
        self._components: dict[str, Component] = {}
        self._maintenance: dict[str, MaintenanceRecord] = {}
        self._observations: dict[str, Observation] = {}

    def add_asset(self, asset: Asset) -> None:
        self._assets[asset.asset_id] = asset

    def get_asset(self, asset_id: str) -> Asset | None:
        return self._assets.get(asset_id)

    def add_component(self, component: Component) -> None:
        self._components[component.component_id] = component
        asset = self._assets.get(component.parent_asset_id)
        if asset:
            asset.components.append(component)

    def add_maintenance_record(self, record: MaintenanceRecord) -> None:
        self._maintenance[record.record_id] = record
        asset = self._assets.get(record.asset_id)
        if asset:
            asset.maintenance_record_ids.append(record.record_id)

    def add_observation(self, observation: Observation) -> None:
        self._observations[observation.observation_id] = observation
        asset = self._assets.get(observation.asset_id)
        if asset:
            asset.observation_ids.append(observation.observation_id)

    def link_sensor_stream(self, asset_id: str, stream_id: str) -> None:
        asset = self._assets.get(asset_id)
        if asset and stream_id not in asset.sensor_stream_ids:
            asset.sensor_stream_ids.append(stream_id)

    def link_inspection(self, asset_id: str, inspection_id: str) -> None:
        asset = self._assets.get(asset_id)
        if asset and inspection_id not in asset.inspection_ids:
            asset.inspection_ids.append(inspection_id)

    def link_anomaly(self, asset_id: str, anomaly_id: str) -> None:
        asset = self._assets.get(asset_id)
        if asset and anomaly_id not in asset.anomaly_ids:
            asset.anomaly_ids.append(anomaly_id)

    def assets_by_type(self, asset_type: AssetType) -> list[Asset]:
        return [a for a in self._assets.values() if a.asset_type == asset_type]

    def asset_graph(self, asset_id: str) -> dict:
        """Returns the full linked graph for one asset — components, sensor
        streams, inspections, observations, anomalies, maintenance records —
        as plain id lists. A future backend can resolve each id list against
        its own store; this stays storage-agnostic on purpose."""
        asset = self._assets.get(asset_id)
        if not asset:
            return {}
        return {
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type.value,
            "name": asset.name,
            "components": [c.component_id for c in asset.components],
            "sensor_stream_ids": asset.sensor_stream_ids,
            "inspection_ids": asset.inspection_ids,
            "observation_ids": asset.observation_ids,
            "anomaly_ids": asset.anomaly_ids,
            "maintenance_record_ids": asset.maintenance_record_ids,
        }
