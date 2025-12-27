import bpy
from bpy.types import Node
from utility.geo_nodes import (
    remove_node_group,
)
from utility.nodes import (
    gn_math_multiply,
    gn_math_subtract,
    gn_clamp_0_1,
)
from masks.mask_types.type_helpers import MaskSocket


def create_priority_resolve_group(group_name: str = "TerrainPriorityResolve"):
    """Creates a node group that resolves priority masks."""
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Raw Mask", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Strength", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Remaining", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Actual Mask", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Remaining Out", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )

    gin, gout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")

    # weighted = clamp(raw * strength)
    w = gn_clamp_0_1(
        ng,
        gn_math_multiply(
            ng, gin.outputs["Raw Mask"], gin.outputs["Strength"], label="R*S"
        ),
    )

    # actual = w * remaining
    a = gn_math_multiply(ng, w, gin.outputs["Remaining"], label="A=w*R")

    # remaining_out = clamp(remaining - actual)
    r = gn_math_subtract(ng, gin.outputs["Remaining"], a, clamp=True, label="R-A")

    ng.links.new(a, gout.inputs["Actual Mask"])
    ng.links.new(r, gout.inputs["Remaining Out"])
    return ng


def add_priority_resolve_node(
    nt,
    *,
    raw_mask: MaskSocket,
    strength_value: float,
    remaining_socket: MaskSocket,
    group_name: str = "TerrainPriorityResolve",
) -> tuple[MaskSocket, MaskSocket, Node]:
    resolve_group = bpy.data.node_groups.get(
        group_name
    ) or create_priority_resolve_group(group_name)
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = resolve_group

    nt.links.new(raw_mask, node.inputs["Raw Mask"])
    node.inputs["Strength"].default_value = float(strength_value)
    nt.links.new(remaining_socket, node.inputs["Remaining"])

    return node.outputs["Actual Mask"], node.outputs["Remaining Out"], node
