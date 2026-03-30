from dataclasses import dataclass
from typing import Literal
from terrain_layers.utility.geo_nodes import remove_node_group
import bpy
from terrain_layers.masks.mask_types.type_helpers import MaskSocket, Node


@dataclass(frozen=True, slots=True)
class HeightMask:
    type: Literal["height"] = "height"
    min_height: float = 0.0
    max_height: float = 10.0
    ramp_low: float = 0.4
    ramp_high: float = 0.6


def create_height_mask_group(group_name: str = "TerrainHeightMask"):
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Position", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(
        name="Min Height", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Max Height", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp Low", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp High", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(name="Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    sep = nodes.new("ShaderNodeSeparateXYZ")
    mapr = nodes.new("ShaderNodeMapRange")
    mapr.clamp = True
    mapr.inputs["To Min"].default_value = 0.0
    mapr.inputs["To Max"].default_value = 1.0

    sub_low = nodes.new("ShaderNodeMath")
    sub_low.operation = "SUBTRACT"

    sub_high = nodes.new("ShaderNodeMath")
    sub_high.operation = "SUBTRACT"

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.use_clamp = True

    clamp = nodes.new("ShaderNodeClamp")

    links.new(gin.outputs["Position"], sep.inputs["Vector"])
    links.new(sep.outputs["Z"], mapr.inputs["Value"])
    links.new(gin.outputs["Min Height"], mapr.inputs["From Min"])
    links.new(gin.outputs["Max Height"], mapr.inputs["From Max"])

    links.new(mapr.outputs["Result"], sub_low.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_low.inputs[1])

    links.new(gin.outputs["Ramp High"], sub_high.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_high.inputs[1])

    links.new(sub_low.outputs["Value"], div.inputs[0])
    links.new(sub_high.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], clamp.inputs["Value"])
    links.new(clamp.outputs["Result"], gout.inputs["Mask"])

    return ng


def add_height_mask_node(
    nt, mask_def: HeightMask, *, group_name: str = "TerrainHeightMask"
) -> tuple[MaskSocket, list[Node]]:
    mask_group = bpy.data.node_groups.get(group_name) or create_height_mask_group(
        group_name
    )
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group

    pos_node = nt.nodes.new("GeometryNodeInputPosition")
    nt.links.new(pos_node.outputs["Position"], node.inputs["Position"])

    node.inputs["Min Height"].default_value = float(mask_def.min_height)
    node.inputs["Max Height"].default_value = float(mask_def.max_height)
    node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    return node.outputs["Mask"], [pos_node, node]
