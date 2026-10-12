from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TunnelShape(str, Enum):
    CIRCLE = "circle"
    RECTANGLE = "rectangle"


@dataclass(frozen=True, slots=True)
class Tunnel:
    curve_object_name: str
    radius: float = 1.0
    shape: TunnelShape = TunnelShape.CIRCLE
    width: float = 2.0
    height: float = 2.0
