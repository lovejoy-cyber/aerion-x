"""Engineering telemetry contracts and CSV/JSON ingestion.

A telemetry stream is explicitly one of REAL / REAL_IMPORTED / SYNTHETIC — the
dataset's provenance travels with every reading so it can never be presented as
something it isn't.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DataProvenance(str, Enum):
    REAL = "REAL"
    REAL_IMPORTED = "REAL_IMPORTED"
    SYNTHETIC = "SYNTHETIC"
    SIMULATION = "SIMULATION"


@dataclass
class SensorReading:
    timestamp: float
    signal_name: str
    value: float
    unit: str = ""


@dataclass
class TelemetryStream:
    stream_id: str
    signal_name: str
    unit: str
    provenance: DataProvenance
    readings: list[SensorReading] = field(default_factory=list)

    def values(self) -> list[float]:
        return [r.value for r in self.readings]

    def timestamps(self) -> list[float]:
        return [r.timestamp for r in self.readings]


def load_csv(path: str, signal_name: str, unit: str, provenance: DataProvenance,
             time_col: str = "timestamp", value_col: str = "value") -> TelemetryStream:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Telemetry CSV not found: {path}")
    readings = []
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            readings.append(SensorReading(
                timestamp=float(row[time_col]),
                signal_name=signal_name,
                value=float(row[value_col]),
                unit=unit,
            ))
    return TelemetryStream(stream_id=f"csv:{p.name}", signal_name=signal_name, unit=unit,
                            provenance=provenance, readings=readings)


def load_json(path: str, signal_name: str, unit: str, provenance: DataProvenance) -> TelemetryStream:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Telemetry JSON not found: {path}")
    data = json.loads(p.read_text())
    readings = [SensorReading(timestamp=d["timestamp"], signal_name=signal_name, value=d["value"], unit=unit)
                for d in data]
    return TelemetryStream(stream_id=f"json:{p.name}", signal_name=signal_name, unit=unit,
                            provenance=provenance, readings=readings)
