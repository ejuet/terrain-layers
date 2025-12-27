import bpy


# -----------------------------
# Basic helpers
# -----------------------------
def active_mesh_object():
    """
    Returns the active mesh object in the scene.
    Raises RuntimeError if no active object or not a mesh.
    """
    obj = bpy.context.object
    if obj is None:
        raise RuntimeError("No active object. Select a mesh first.")
    if obj.type != "MESH":
        raise RuntimeError(f"Active object must be MESH, got: {obj.type}")
    return obj


def remove_node_group(name: str):
    """
    Removes a node group by name if it exists.
    """
    ng = bpy.data.node_groups.get(name)
    if ng:
        bpy.data.node_groups.remove(ng)


def ensure_geo_nodes_modifier(obj, name: str):
    """
    Ensures that the given object has a Geometry Nodes modifier with the specified name.
    Returns the modifier.
    """
    mod = obj.modifiers.get(name)
    if mod is None or mod.type != "NODES":
        mod = obj.modifiers.new(name, "NODES")
    return mod
