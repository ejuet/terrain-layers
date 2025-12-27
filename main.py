import sys
import importlib

sys.path.append("/home/lisa/Repositories/Private/terrain-layers")

"""
Reload all modules to reflect recent changes without restarting Blender.
"Ctrl+shift+O > reopen current world" is not sufficient.
"""
import create_layer_masks

importlib.reload(create_layer_masks)

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
import masks.mask_types.__init__

importlib.reload(masks.mask_types.__init__)

import masks.mask_types.type_helpers

importlib.reload(masks.mask_types.type_helpers)

# --------------------------------------------------------------------
# Run the script
# --------------------------------------------------------------------
from create_layer_masks import run

run()
