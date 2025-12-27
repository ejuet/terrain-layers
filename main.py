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

# --------------------------------------------------------------------
# Run the script
# --------------------------------------------------------------------
import pipeline

importlib.reload(pipeline)

pipeline.run()
