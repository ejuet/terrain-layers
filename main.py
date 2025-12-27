import sys
import importlib

sys.path.append("/home/lisa/Repositories/Private/terrain-layers")

"""
Reload all modules to reflect recent changes without restarting Blender.
"Ctrl+shift+O > reopen current world" is not sufficient.
"""

# ----------------------------
# Utility
# ----------------------------
import utility.geo_nodes

importlib.reload(utility.geo_nodes)
import utility.rearrange

importlib.reload(utility.rearrange)

import utility.nodes

importlib.reload(utility.nodes)

# ----------------------------
# Masks
# ----------------------------
import masks.mask_types.height

importlib.reload(masks.mask_types.height)
import masks.mask_types.slope

importlib.reload(masks.mask_types.slope)

import masks.mask_types.paint

importlib.reload(masks.mask_types.paint)

import masks.mask_types.__init__

importlib.reload(masks.mask_types.__init__)

import masks.noise

importlib.reload(masks.noise)

import masks.mask_types.type_helpers

importlib.reload(masks.mask_types.type_helpers)

import masks.priority_resolving

importlib.reload(masks.priority_resolving)

import masks.create_layer_masks

importlib.reload(masks.create_layer_masks)


# ----------------------------
# Config
# ----------------------------
import config.config_types

importlib.reload(config.config_types)
import config.helpers

importlib.reload(config.helpers)

# ----------------------------
# Shader
# ----------------------------
import shader.material_types

importlib.reload(shader.material_types)

import shader.get_texture_image

importlib.reload(shader.get_texture_image)

import shader.anti_repetition.uv_warp

importlib.reload(shader.anti_repetition.uv_warp)
import shader.anti_repetition.anti_tile

importlib.reload(shader.anti_repetition.anti_tile)

import shader.anti_repetition.uv_noise

importlib.reload(shader.anti_repetition.uv_noise)

import shader.create_shader

importlib.reload(shader.create_shader)
# --------------------------------------------------------------------
# Run the script
# --------------------------------------------------------------------
import pipeline

importlib.reload(pipeline)

shader.create_shader.run()
