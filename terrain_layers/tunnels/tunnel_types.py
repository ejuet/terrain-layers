from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from terrain_layers.shader.material_types import PBRSourceMaterial


# Identifies materials assigned to faces created by a tunnel/cave boolean.
TUNNEL_INTERIOR_MATERIAL_MARKER = "terrain_layers.tunnel_interior"


class TunnelShape(str, Enum):
    CIRCLE = "circle"
    RECTANGLE = "rectangle"


class TunnelEntryDecoration:
    """Base type for an optional structure generated at tunnel endpoints.

    Add a new decoration as another subclass.  A tunnel accepts one decoration
    at a time, which keeps the entry-decoration configuration explicit while leaving
    room for additional decoration types.
    """


@dataclass(frozen=True, slots=True)
class MineShaftEntry(TunnelEntryDecoration):
    """A timber frame fitted to each entry of a rectangular tunnel."""

    log_thickness: float = 0.3
    # When set, the logs use this PBR material instead of the fallback brown
    # material. For example, this can point at a wood texture set.
    ground_material: PBRSourceMaterial | None = None


@dataclass(frozen=True, slots=True)
class TunnelPath:
    """One curve excavated by a :class:`TunnelSystem`.

    ``None`` means inherit the corresponding system setting.  ``False`` for
    ``entry_decoration`` is deliberately distinct from ``None``: it suppresses
    a decoration inherited from the system.
    """

    curve_object_name: str
    ground_material: PBRSourceMaterial | None = None
    texture_scale: float | None = None
    radius: float | None = None
    shape: TunnelShape | None = None
    width: float | None = None
    height: float | None = None
    keep_floor_level: bool | None = None
    entry_decoration: TunnelEntryDecoration | None | bool = None


@dataclass(frozen=True, slots=True)
class TunnelCave:
    """One mesh volume excavated by a :class:`TunnelSystem`."""

    cave_object_name: str
    ground_material: PBRSourceMaterial | None = None
    texture_scale: float | None = None
    fuse_group: str | None = None


@dataclass(frozen=True, slots=True)
class TunnelSystem:
    """Tunnel defaults plus independently configurable path and cave cuts."""

    paths: tuple[TunnelPath, ...]
    ground_material: PBRSourceMaterial
    caves: tuple[TunnelCave, ...] = ()
    # Object-space texture repetitions per Blender unit.
    texture_scale: float = 0.05
    radius: float = 1.0
    shape: TunnelShape = TunnelShape.CIRCLE
    width: float = 2.0
    height: float = 2.0
    # Depth of the closed terrain volume created before tunnel and cave cuts.
    # Increase this when cutters extend farther below the terrain surface.
    solidify_depth: float = 100.0
    # For rectangular tunnels, orient the profile from world Z instead of
    # following the curve's roll, so its floor stays parallel to the XY plane.
    keep_floor_level: bool = False
    entry_decoration: TunnelEntryDecoration | None = None
