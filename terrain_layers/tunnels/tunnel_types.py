from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeAlias
from pydantic import Field

from terrain_layers.shader.material_types import PBRMaterialSource


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

    log_thickness: float = Field(default=0.3, description="Thickness of the timber logs used to build each mine-shaft frame.")
    # When set, the logs use this PBR material instead of the fallback brown
    # material. For example, this can point at a wood texture set.
    pbr_source: PBRMaterialSource | None = Field(default=None, description="Optional PBR material used for the timber; uses the built-in brown material when omitted.")
    type: Literal["mine_shaft"] = Field(
        default="mine_shaft", description="Tunnel-entry decoration variant identifier."
    )


TunnelPathEntryDecoration: TypeAlias = MineShaftEntry | None | bool


@dataclass(frozen=True, slots=True)
class TunnelPath:
    """A tunnel whose route follows one curve in a :class:`TunnelSystem`.

    ``None`` means inherit the corresponding system setting.  ``False`` for
    ``entry_decoration`` is deliberately distinct from ``None``: it suppresses
    a decoration inherited from the system.
    """

    curve_object_name: str = Field(description="Name of the Blender curve object that defines where this tunnel runs.")
    pbr_source: PBRMaterialSource | None = Field(default=None, description="Tunnel-wall material; inherits the system material when omitted.")
    texture_scale: float | None = Field(default=None, description="Tunnel-wall texture repetitions per Blender unit; inherits the system value when omitted.")
    radius: float | None = Field(default=None, description="Radius of a circular tunnel; inherits the system value when omitted.")
    shape: TunnelShape | None = Field(default=None, description="Cross-section shape; inherits the system shape when omitted.")
    width: float | None = Field(default=None, description="Width of a rectangular tunnel; inherits the system value when omitted.")
    height: float | None = Field(default=None, description="Height of a rectangular tunnel; inherits the system value when omitted.")
    keep_floor_level: bool | None = Field(default=None, description="Keep a rectangular tunnel floor level; inherits the system value when omitted.")
    entry_decoration: TunnelPathEntryDecoration = Field(default=None, description="Endpoint decoration; null inherits the system setting and false explicitly disables it.")


@dataclass(frozen=True, slots=True)
class TunnelCave:
    """A cave whose shape comes from one mesh object in a :class:`TunnelSystem`."""

    cave_object_name: str = Field(description="Name of the mesh object that defines this cave's shape.")
    pbr_source: PBRMaterialSource | None = Field(default=None, description="Cave-wall material; inherits the system material when omitted.")
    texture_scale: float | None = Field(default=None, description="Cave-wall texture repetitions per Blender unit; inherits the system value when omitted.")
    fuse_group: str | None = Field(default=None, description="Optional group name for treating overlapping caves as one continuous cave.")


@dataclass(frozen=True, slots=True)
class TunnelSystem:
    """Tunnel defaults, routes, and cave shapes."""

    paths: tuple[TunnelPath, ...] = Field(description="Curves that define where tunnels run.")
    pbr_source: PBRMaterialSource = Field(description="Default PBR material applied to tunnel and cave walls.")
    caves: tuple[TunnelCave, ...] = Field(default=(), description="Mesh objects that define cave shapes.")
    # Object-space texture repetitions per Blender unit.
    texture_scale: float = Field(default=0.05, description="Default tunnel-wall texture repetitions per Blender unit.")
    radius: float = Field(default=1.0, description="Default radius of circular tunnels.")
    shape: TunnelShape = Field(default=TunnelShape.CIRCLE, description="Default cross-section shape for tunnel paths.")
    width: float = Field(default=2.0, description="Default width of rectangular tunnels.")
    height: float = Field(default=2.0, description="Default height of rectangular tunnels.")
    solidify_depth: float = Field(default=100.0, description="How far the terrain extends below its surface around tunnels and caves.")
    keep_floor_level: bool = Field(default=False, description="Keep rectangular tunnel floors level by default.")
    entry_decoration: MineShaftEntry | None = Field(default=None, description="Default decoration generated at both endpoints of each tunnel path.")
