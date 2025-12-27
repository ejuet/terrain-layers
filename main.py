import sys
import importlib
sys.path.append("/home/lisa/Repositories/Private/terrain-shader")

"""
Reload all modules to reflect recent changes without restarting Blender.
"Ctrl+shift+O > reopen current world" is not sufficient.
"""
import create_layer_masks
importlib.reload(create_layer_masks)


# ----------------------------
# Run the script
# ----------------------------
from create_layer_masks import run
run()