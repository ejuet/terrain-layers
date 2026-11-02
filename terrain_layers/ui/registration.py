"""Blender class registration for the terrain-layer UI."""

import bpy
from bpy.props import StringProperty

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
    bpy.types.Scene.terrain_layers_config_path = StringProperty(
        name="Terrain Config",
        description="Terrain configuration JSON file to use when rebuilding",
        subtype="FILE_PATH",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.terrain_layers_config_path
