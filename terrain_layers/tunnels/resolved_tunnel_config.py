from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from terrain_layers.paths.path_source import ensure_curve_object
from terrain_layers.shader.material_types import GroundMaterial
from terrain_layers.tunnels.tunnel_types import (
    MineShaftEntry,
    TunnelEntryDecoration,
    TunnelShape,
)

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


@dataclass(frozen=True, slots=True)
class ResolvedPath:
    object: bpy.types.Object
    shape: TunnelShape
    radius: float
    width: float
    height: float
    keep_floor_level: bool
    ground_material: GroundMaterial
    texture_scale: float
    entry_decoration: TunnelEntryDecoration | None

    @property
    def batch_key(self) -> tuple[object, ...]:
        return (
            self.shape,
            self.radius if self.shape == TunnelShape.CIRCLE else None,
            self.width if self.shape == TunnelShape.RECTANGLE else None,
            self.height if self.shape == TunnelShape.RECTANGLE else None,
            self.keep_floor_level if self.shape == TunnelShape.RECTANGLE else None,
            self.ground_material,
            self.texture_scale,
        )


@dataclass(frozen=True, slots=True)
class ResolvedCave:
    object: bpy.types.Object
    ground_material: GroundMaterial
    texture_scale: float
    fuse_group: str | None


def _ensure_cave_object(cave_object_name: str) -> bpy.types.Object:
    cave = bpy.data.objects.get(cave_object_name)
    if cave is None:
        raise RuntimeError(f"Tunnel references missing cave object '{cave_object_name}'.")
    if cave.type != "MESH":
        raise RuntimeError(
            f"Tunnel cave object '{cave_object_name}' must be MESH, got: {cave.type}"
        )
    return cave


def resolve_tunnel_system(
    config: "TerrainConfig",
) -> tuple[list[ResolvedPath], list[ResolvedCave]]:
    system = config.tunnel_system
    if system is None:
        return [], []
    if system.solidify_depth <= 0:
        raise ValueError("Tunnel system solidify_depth must be positive.")

    seen_names: set[str] = set()

    def unique(name: str) -> None:
        if name in seen_names:
            raise ValueError(f"Tunnel system references object '{name}' more than once.")
        seen_names.add(name)

    paths: list[ResolvedPath] = []
    for path in system.paths:
        unique(path.curve_object_name)
        shape = TunnelShape(path.shape if path.shape is not None else system.shape)
        radius = float(path.radius if path.radius is not None else system.radius)
        width = float(path.width if path.width is not None else system.width)
        height = float(path.height if path.height is not None else system.height)
        if (shape == TunnelShape.CIRCLE and radius <= 0) or (
            shape == TunnelShape.RECTANGLE and (width <= 0 or height <= 0)
        ):
            raise ValueError(
                f"Tunnel path '{path.curve_object_name}' has non-positive resolved dimensions."
            )
        decoration = (
            system.entry_decoration
            if path.entry_decoration is None
            else path.entry_decoration
        )
        if decoration is False:
            decoration = None
        elif not isinstance(decoration, (TunnelEntryDecoration, type(None))):
            raise ValueError(
                f"Tunnel path '{path.curve_object_name}' has an invalid entry decoration."
            )
        if isinstance(decoration, MineShaftEntry) and shape != TunnelShape.RECTANGLE:
            raise ValueError(
                "MineShaftEntry decoration requires a rectangular tunnel "
                f"(path '{path.curve_object_name}')."
            )
        paths.append(
            ResolvedPath(
                ensure_curve_object(path.curve_object_name),
                shape,
                radius,
                width,
                height,
                bool(
                    path.keep_floor_level
                    if path.keep_floor_level is not None
                    else system.keep_floor_level
                ),
                path.ground_material or system.ground_material,
                float(
                    path.texture_scale
                    if path.texture_scale is not None
                    else system.texture_scale
                ),
                decoration,
            )
        )

    caves: list[ResolvedCave] = []
    group_settings: dict[str, tuple[GroundMaterial, float]] = {}
    for cave in system.caves:
        unique(cave.cave_object_name)
        if cave.fuse_group is not None and not cave.fuse_group:
            raise ValueError("Tunnel cave fuse_group must be a non-empty name or None.")
        resolved = ResolvedCave(
            _ensure_cave_object(cave.cave_object_name),
            cave.ground_material or system.ground_material,
            float(
                cave.texture_scale
                if cave.texture_scale is not None
                else system.texture_scale
            ),
            cave.fuse_group,
        )
        if resolved.fuse_group is not None:
            settings = (resolved.ground_material, resolved.texture_scale)
            previous = group_settings.setdefault(resolved.fuse_group, settings)
            if previous != settings:
                raise ValueError(
                    f"Tunnel cave fuse group '{resolved.fuse_group}' must resolve to one material and texture scale."
                )
        caves.append(resolved)
    return paths, caves
