import sys
import importlib
from pathlib import Path

sys.path.append("/home/lisa/Repositories/Private/terrain-layers/")

"""
Reload all modules to reflect recent changes without restarting Blender.
"Ctrl+shift+O > reopen current world" is not sufficient.
"""

# ------------------------------
# Extra precautions to prevent blender from keeping stale modules
# ------------------------------

REPO_ROOT = Path("/home/lisa/Repositories/Private/terrain-layers").resolve()
repo_root_str = str(REPO_ROOT)

if repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

# Blender can keep stale modules alive across text reloads. Drop the package tree
# so imports come from the refactored repository layout above.
for module_name in list(sys.modules):
    if module_name == "terrain_layers" or module_name.startswith("terrain_layers."):
        del sys.modules[module_name]

# ----------------------------
# Utility
# ----------------------------
import terrain_layers.utility.geo_nodes

importlib.reload(terrain_layers.utility.geo_nodes)
import terrain_layers.utility.rearrange

importlib.reload(terrain_layers.utility.rearrange)

import terrain_layers.utility.nodes

importlib.reload(terrain_layers.utility.nodes)

import terrain_layers.utility.object_info_group

importlib.reload(terrain_layers.utility.object_info_group)
import terrain_layers.utility.frame_nodes

importlib.reload(terrain_layers.utility.frame_nodes)

# ----------------------------
# Masks
# ----------------------------
import terrain_layers.masks.mask_types.height

importlib.reload(terrain_layers.masks.mask_types.height)
import terrain_layers.masks.mask_types.slope

importlib.reload(terrain_layers.masks.mask_types.slope)

import terrain_layers.masks.mask_types.paint

importlib.reload(terrain_layers.masks.mask_types.paint)

import terrain_layers.masks.mask_types.path

importlib.reload(terrain_layers.masks.mask_types.path)

import terrain_layers.masks.mask_types.__init__

importlib.reload(terrain_layers.masks.mask_types.__init__)

import terrain_layers.masks.noise

importlib.reload(terrain_layers.masks.noise)

import terrain_layers.masks.mask_types.type_helpers

importlib.reload(terrain_layers.masks.mask_types.type_helpers)

import terrain_layers.masks.priority_resolving

importlib.reload(terrain_layers.masks.priority_resolving)

import terrain_layers.masks.create_layer_masks

importlib.reload(terrain_layers.masks.create_layer_masks)

# ----------------------------
# Paths
# ----------------------------
import terrain_layers.paths.path_deformation

importlib.reload(terrain_layers.paths.path_deformation)

import terrain_layers.paths.path_types

importlib.reload(terrain_layers.paths.path_types)

import terrain_layers.paths.path_source

importlib.reload(terrain_layers.paths.path_source)

# ----------------------------
# Config
# ----------------------------
import terrain_layers.config.config_types

importlib.reload(terrain_layers.config.config_types)
import terrain_layers.config.helpers

importlib.reload(terrain_layers.config.helpers)

# ----------------------------
# Preview Shader
# ----------------------------
import terrain_layers.preview_shader.create_preview_terrain_shader

importlib.reload(terrain_layers.preview_shader.create_preview_terrain_shader)

# ----------------------------
# Shader
# ----------------------------
import terrain_layers.shader.material_types

importlib.reload(terrain_layers.shader.material_types)

import terrain_layers.shader.get_texture_image

importlib.reload(terrain_layers.shader.get_texture_image)

import terrain_layers.shader.anti_repetition.uv_warp

importlib.reload(terrain_layers.shader.anti_repetition.uv_warp)
import terrain_layers.shader.anti_repetition.anti_tile

importlib.reload(terrain_layers.shader.anti_repetition.anti_tile)

import terrain_layers.shader.anti_repetition.uv_noise

importlib.reload(terrain_layers.shader.anti_repetition.uv_noise)

import terrain_layers.shader.create_shader

importlib.reload(terrain_layers.shader.create_shader)

import terrain_layers.shader.helpers

importlib.reload(terrain_layers.shader.helpers)

# ----------------------------
# Biomes
# ----------------------------
import terrain_layers.biomes.create_scatter_biomes

importlib.reload(terrain_layers.biomes.create_scatter_biomes)

# --------------------------------------------------------------------
# Run the script
# --------------------------------------------------------------------
import terrain_layers.pipeline

importlib.reload(terrain_layers.pipeline)

terrain_layers.pipeline.run()
