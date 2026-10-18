from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from terrain_layers.shader.material_types import GroundMaterial


class TunnelShape(str, Enum):
    CIRCLE = "circle"
    RECTANGLE = "rectangle"


class TunnelEntryDecoration:
    """Base type for an optional structure generated at tunnel endpoints.

    Add a new decoration as another subclass.  A tunnel accepts one decoration
    at a time, which keeps the entrypoint configuration explicit while leaving
    room for additional decoration types.
    """


@dataclass(frozen=True, slots=True)
class MineShaftEntry(TunnelEntryDecoration):
    """A timber frame fitted to each entry of a rectangular tunnel."""

    log_thickness: float = 0.3
    # When set, the logs use this PBR material instead of the fallback brown
    # material. For example, this can point at a wood texture set.
    ground_material: GroundMaterial | None = None


@dataclass(frozen=True, slots=True)
class Tunnel:
    # All curve objects swept to form the tunnel.  They are combined into one
    # cutter, so paths may intersect each other and the optional cave volume.
    curve_object_names: tuple[str, ...]
    # Tunnel walls use their own material instead of the terrain-layer shader.
    ground_material: GroundMaterial
    # Optional closed mesh volumes that are joined to the tunnel excavation.
    cave_object_names: tuple[str, ...] = ()
    # Merge overlapping cave volumes before cutting them from the terrain,
    # removing the interior faces between connected caves.
    # Disabling this can yield better performance, but the mesh will not be the same.
    fuse_caves: bool = True
    # Object-space texture repetitions per Blender unit.  The default matches
    # the terrain tiling used by the example scene (about one repeat per 20 m).
    texture_scale: float = 0.05
    radius: float = 1.0
    shape: TunnelShape = TunnelShape.CIRCLE
    width: float = 2.0
    height: float = 2.0
    # For rectangular tunnels, orient the profile from world Z instead of
    # following the curve's roll, so its floor stays parallel to the XY plane.
    keep_floor_level: bool = False
    entry_decoration: TunnelEntryDecoration | None = None
