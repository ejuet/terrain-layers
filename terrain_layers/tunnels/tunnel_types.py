from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from terrain_layers.shader.material_types import GroundMaterial


class TunnelShape(str, Enum):
    CIRCLE = "circle"
    RECTANGLE = "rectangle"


class TunnelEntryDecoration(str, Enum):
    """Optional structures generated at every tunnel endpoint."""

    MINE_SHAFT_ENTRY = "MineShaftEntry"


@dataclass(frozen=True, slots=True)
class Tunnel:
    curve_object_name: str
    # Tunnel walls use their own material instead of the terrain-layer shader.
    ground_material: GroundMaterial
    radius: float = 1.0
    shape: TunnelShape = TunnelShape.CIRCLE
    width: float = 2.0
    height: float = 2.0
    # For rectangular tunnels, orient the profile from world Z instead of
    # following the curve's roll, so its floor stays parallel to the XY plane.
    keep_floor_level: bool = False
    entry_decoration: TunnelEntryDecoration | None = None
    entry_log_thickness: float = 0.3
