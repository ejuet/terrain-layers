"""Blender class registration for the terrain-layer UI."""

import bpy

from .panel import (
    TERRAINLAYERS_OT_rebuild_terrain,
    TERRAINLAYERS_OT_reload_addon,
    VIEW3D_PT_terrain_layers,
)


_CLASSES = (
    TERRAINLAYERS_OT_reload_addon,
    TERRAINLAYERS_OT_rebuild_terrain,
    VIEW3D_PT_terrain_layers,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
