import bpy

from utility.frame_nodes import frame_nodes
from utility.geo_nodes import clear_group_interface, remove_node_group
from utility.rearrange import arrange_nodes


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


def _add_object_info_nodes(
    nt: bpy.types.NodeTree,
    *,
    objects: list[bpy.types.Object],
    transform_space: str,
    as_instance: bool,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
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


def create_object_info_group(
    *,
    group_name: str,
    objects: list[bpy.types.Object],
    transform_space: str = "RELATIVE",
    as_instance: bool = False,
    output_name: str = "Geometry",
    frame_label: str | None = None,
) -> bpy.types.NodeTree:
    """
    Build a reusable node group that outputs one or more Object Info geometries.
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name=output_name,
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes, links = ng.nodes, ng.links
    gout = nodes.new("NodeGroupOutput")

    output_socket, created_nodes = _add_object_info_nodes(
        ng,
        objects=objects,
        transform_space=transform_space,
        as_instance=as_instance,
    )
    links.new(output_socket, gout.inputs[output_name])

    if frame_label:
        frame_nodes(ng, frame_label, created_nodes)
    arrange_nodes(ng)
    return ng
