"""3D Viewport UI and development actions for terrain layers."""

import runpy
import sys
import traceback
from pathlib import Path

import bpy


_MAIN_SCRIPT = Path(__file__).resolve().parents[2] / "main.py"


def _reload_addon() -> None:
    """Run the developer bootstrap after the invoking operator has returned."""
    try:
        runpy.run_path(str(_MAIN_SCRIPT), run_name="__main__")
    except Exception:
        traceback.print_exc()


def _reload_and_rebuild(config_path: str | None = None) -> None:
    """Reload the package, then run its freshly imported terrain pipeline."""
    _reload_addon()
    try:
        sys.modules["terrain_layers.pipeline"].run(config_path)
    except Exception:
        traceback.print_exc()


class TERRAINLAYERS_OT_reload_addon(bpy.types.Operator):
    bl_idname = "terrain_layers.reload_addon"
    bl_label = "Reload Addon"
    bl_description = "Reload all terrain-layer Python modules and the UI"

    def execute(self, _context):
        bpy.app.timers.register(_reload_addon, first_interval=0.0)
        return {"FINISHED"}


class TERRAINLAYERS_OT_rebuild_terrain(bpy.types.Operator):
    bl_idname = "terrain_layers.rebuild"
    bl_label = "Rebuild Terrain"
    bl_description = "Reload all terrain-layer Python modules and rebuild the terrain"

    def execute(self, context):
        config_path = context.scene.terrain_layers_config_path
        # Resolve Blender-relative paths before the timer runs outside this context.
        resolved_path = bpy.path.abspath(config_path) if config_path else None
        bpy.app.timers.register(
            lambda: _reload_and_rebuild(resolved_path),
            first_interval=0.0,
        )
        return {"FINISHED"}


class VIEW3D_PT_terrain_layers(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_terrain_layers"
    bl_label = "Terrain Layers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Terrain"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "terrain_layers_config_path")
        layout.operator(TERRAINLAYERS_OT_reload_addon.bl_idname, text="Reload Addon")
        layout.operator(
            TERRAINLAYERS_OT_rebuild_terrain.bl_idname,
            text="Rebuild Terrain",
        )
