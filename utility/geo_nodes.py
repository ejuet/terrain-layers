import bpy


# -----------------------------
# Basic helpers
# -----------------------------
def get_terrain_object(object_name: str | None = None):
    """
    Returns the terrain object specified by name or the active object if no name is given.
    Has to be a mesh.
    Raises RuntimeError if the object is missing or not a mesh.
    """
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            raise RuntimeError(f"Object '{object_name}' was not found.")
    else:
        obj = bpy.context.object
    if obj is None:
        raise RuntimeError("No active object. Select a mesh first.")
    if obj.type != "MESH":
        if object_name:
            raise RuntimeError(f"Object '{object_name}' must be MESH, got: {obj.type}")
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
