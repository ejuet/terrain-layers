from dataclasses import dataclass
from typing import Literal
from utility.geo_nodes import remove_node_group
import bpy
from masks.mask_types.type_helpers import MaskSocket, Node


@dataclass(frozen=True, slots=True)
class SlopeMask:
    type: Literal["slope"] = "slope"
    min_angle: float = 25.0
    max_angle: float = 60.0
    ramp_low: float = 0.4
    ramp_high: float = 0.6


def create_slope_mask_group(group_name: str = "TerrainSlopeMask"):
    """
    Produces a mask based on slope angle (degrees) from the geometry normal:
      0° = perfectly flat (facing +Z), 90° = vertical.
    Uses abs(dot(N, Up)) so both sides behave the same.
    Output is a 0..1 mask with optional ramp shaping similar to height mask.
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Normal", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(
        name="Min Angle", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Max Angle", in_out="INPUT", socket_type="NodeSocketFloat"
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

    # Normalize normal
    nrm = nodes.new("ShaderNodeVectorMath")
    nrm.operation = "NORMALIZE"

    # dot(N, Up)
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.0, 0.0, 1.0)

    # abs(dot)
    abs_dot = nodes.new("ShaderNodeMath")
    abs_dot.operation = "ABSOLUTE"

    # acos(abs(dot)) -> radians
    acos = nodes.new("ShaderNodeMath")
    acos.operation = "ARCCOSINE"

    # radians to degrees
    to_deg = nodes.new("ShaderNodeMath")
    to_deg.operation = "MULTIPLY"
    to_deg.inputs[1].default_value = 57.29577951308232  # 180/pi

    # Map angle range to 0..1 (clamped)
    mapr = nodes.new("ShaderNodeMapRange")
    mapr.clamp = True
    mapr.inputs["To Min"].default_value = 0.0
    mapr.inputs["To Max"].default_value = 1.0

    # Ramp shaping like height mask
    sub_low = nodes.new("ShaderNodeMath")
    sub_low.operation = "SUBTRACT"

    sub_high = nodes.new("ShaderNodeMath")
    sub_high.operation = "SUBTRACT"

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.use_clamp = True

    clamp = nodes.new("ShaderNodeClamp")

    # Wiring
    links.new(gin.outputs["Normal"], nrm.inputs[0])
    links.new(nrm.outputs["Vector"], dot.inputs[0])

    links.new(dot.outputs["Value"], abs_dot.inputs[0])
    links.new(abs_dot.outputs["Value"], acos.inputs[0])

    links.new(acos.outputs["Value"], to_deg.inputs[0])

    links.new(to_deg.outputs["Value"], mapr.inputs["Value"])
    links.new(gin.outputs["Min Angle"], mapr.inputs["From Min"])
    links.new(gin.outputs["Max Angle"], mapr.inputs["From Max"])

    links.new(mapr.outputs["Result"], sub_low.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_low.inputs[1])

    links.new(gin.outputs["Ramp High"], sub_high.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_high.inputs[1])

    links.new(sub_low.outputs["Value"], div.inputs[0])
    links.new(sub_high.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], clamp.inputs["Value"])
    links.new(clamp.outputs["Result"], gout.inputs["Mask"])

    return ng


def add_slope_mask_node(
    nt, mask_def: SlopeMask, *, group_name: str = "TerrainSlopeMask"
) -> tuple[MaskSocket, list[Node]]:
    mask_group = bpy.data.node_groups.get(group_name) or create_slope_mask_group(
        group_name
    )
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group

    nrm_node = nt.nodes.new("GeometryNodeInputNormal")
    nt.links.new(nrm_node.outputs["Normal"], node.inputs["Normal"])

    node.inputs["Min Angle"].default_value = float(mask_def.min_angle)
    node.inputs["Max Angle"].default_value = float(mask_def.max_angle)
    node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    return node.outputs["Mask"], [nrm_node, node]
