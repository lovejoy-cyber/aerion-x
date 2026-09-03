"""2D camera-space zone reasoning: point-in-polygon occupancy, nothing more.

Deliberately does not claim real-world distance or 3D position from a single
uncalibrated camera — zones are polygons in pixel space, and "occupancy" means
"track centroid falls inside this polygon in this frame."
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Zone:
    zone_id: str
    name: str
    polygon: list[tuple[float, float]]  # pixel coordinates, closed implicitly

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            ):
                inside = not inside
            j = i
        return inside


class ZoneRegistry:
    def __init__(self):
        self.zones: dict[str, Zone] = {}

    def add(self, zone: Zone) -> None:
        self.zones[zone.zone_id] = zone

    def zone_for_point(self, point: tuple[float, float]) -> str | None:
        for zone in self.zones.values():
            if zone.contains(point):
                return zone.zone_id
        return None
