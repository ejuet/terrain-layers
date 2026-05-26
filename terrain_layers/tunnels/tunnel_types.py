from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tunnel:
    curve_object_name: str
    radius: float = 2.0
