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


def collect_collection_objects(
    collection: bpy.types.Collection,
) -> list[bpy.types.Object]:
    """
    Return all unique objects contained in a collection and its child collections.
    """
    result: list[bpy.types.Object] = []
    seen: set[str] = set()

    def visit(coll: bpy.types.Collection):
        for obj in coll.objects:
            if obj.name in seen:
                continue
            seen.add(obj.name)
            result.append(obj)
        for child in coll.children:
            visit(child)

    visit(collection)
    return result


def group_has_io(ng: bpy.types.NodeTree, ins: list[str], outs: list[str]) -> bool:
    """
    Return whether a node group exposes the expected input and output sockets.
    """
    try:
        in_names = {s.name for s in getattr(ng, "inputs", [])}
        out_names = {s.name for s in getattr(ng, "outputs", [])}
        return all(name in in_names for name in ins) and all(
            name in out_names for name in outs
        )
    except Exception:
        return False


def clear_group_interface(ng: bpy.types.NodeTree) -> None:
    """Remove all sockets from a node group's interface before rebuilding it."""
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)


def _set_object_info_as_instance(node: bpy.types.Node) -> None:
    """
    Configure an Object Info node to output instances across Blender versions.
    """
    as_instance_input = node.inputs.get("As Instance")
    if as_instance_input is not None:
        as_instance_input.default_value = True
        return
    if hasattr(node, "as_instance"):
        try:
            node.as_instance = True
        except Exception:
            pass


def add_object_info_nodes(
    nt: bpy.types.NodeTree,
    *,
    objects: list[bpy.types.Object],
    transform_space: str = "RELATIVE",
    as_instance: bool = False,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    """
    Add Object Info nodes for one or more objects and join them when needed.
    """
    if not objects:
        raise RuntimeError("Expected at least one object for Object Info nodes.")

    nodes, links = nt.nodes, nt.links
    created_nodes: list[bpy.types.Node] = []
    object_infos: list[bpy.types.Node] = []

    for obj in objects:
        object_info = nodes.new("GeometryNodeObjectInfo")
        object_info.transform_space = transform_space
        if as_instance:
            _set_object_info_as_instance(object_info)
        object_info.inputs["Object"].default_value = obj
        created_nodes.append(object_info)
        object_infos.append(object_info)

    if len(object_infos) == 1:
        return object_infos[0].outputs["Geometry"], created_nodes

    join = nodes.new("GeometryNodeJoinGeometry")
    created_nodes.append(join)
    for object_info in object_infos:
        links.new(object_info.outputs["Geometry"], join.inputs["Geometry"])

    return join.outputs["Geometry"], created_nodes
