import bpy
from typing import TypeAlias

# Semantic alias for “this socket is a 0..1 mask”
MaskSocket: TypeAlias = bpy.types.NodeSocket
Node: TypeAlias = bpy.types.Node
