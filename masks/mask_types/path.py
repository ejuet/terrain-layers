from dataclasses import dataclass
from typing import Literal

import bpy

from masks.mask_types.type_helpers import MaskSocket, Node
from utility.geo_nodes import remove_node_group


@dataclass(frozen=True, slots=True)
class PathMask:
    """
    Mask that creates a gradient based on proximity to a curve object (e.g. for roads or paths).
    path_object_name: Name of the curve object in the Blender scene that defines the path. This object must be of type CURVE.
    width: Width of the road/ The distance from the path at which the mask will reach its maximum value.
    falloff: Additional distance beyond the width where the mask will fall off to zero. Total effective distance of the mask is width + falloff.
    sample_count: Number of points to sample along the curve for raycasting. Higher values can produce smoother masks but may impact performance.
    ray_length: Maximum distance for raycasting downwards to find the terrain surface. Should be set high enough to accommodate the tallest expected terrain features.
    ramp_low: The distance from the path at which the mask will start to ramp up from 0.
    ramp_high: The distance from the path at which the mask will reach its maximum value of 1. Should be greater than or equal to ramp_low and less than or equal to width.
    """

    type: Literal["path"] = "path"
    path_object_name: str = "RoadPath"
    width: float = 2.5
    falloff: float = 1.0
    sample_count: int = 256
    ray_length: float = 10000.0
    ramp_low: float = 0.0
    ramp_high: float = 1.0


def _ensure_path_object(path_object_name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(path_object_name)
    if obj is None:
        raise RuntimeError(f"Path mask references missing object '{path_object_name}'.")
    if obj.type != "CURVE":
        raise RuntimeError(
            f"Path mask object '{path_object_name}' must be CURVE for the MVP, "
            f"got: {obj.type}"
        )
    return obj


def create_path_mask_group(group_name: str = "TerrainPathMask"):
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Terrain", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Position", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(
        name="Path Object", in_out="INPUT", socket_type="NodeSocketObject"
    )
    ng.interface.new_socket(name="Width", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        name="Falloff", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Sample Count", in_out="INPUT", socket_type="NodeSocketInt"
    )
    ng.interface.new_socket(
        name="Ray Length", in_out="INPUT", socket_type="NodeSocketFloat"
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

    object_info = nodes.new("GeometryNodeObjectInfo")
    object_info.transform_space = "RELATIVE"

    resample = nodes.new("GeometryNodeResampleCurve")
    try:
        resample.mode = "COUNT"
    except Exception:
        pass

    curve_to_points = nodes.new("GeometryNodeCurveToPoints")
    try:
        curve_to_points.mode = "EVALUATED"
    except Exception:
        pass

    path_pos = nodes.new("GeometryNodeInputPosition")

    raycast = nodes.new("GeometryNodeRaycast")
    try:
        raycast.data_type = "FLOAT"
    except Exception:
        pass
    if "Ray Direction" in raycast.inputs:
        raycast.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)

    set_position = nodes.new("GeometryNodeSetPosition")
    delete_geometry = nodes.new("GeometryNodeDeleteGeometry")

    proximity = nodes.new("GeometryNodeProximity")
    try:
        proximity.target_element = "POINTS"
    except Exception:
        pass

    add_total = nodes.new("ShaderNodeMath")
    add_total.operation = "ADD"

    denom_safe = nodes.new("ShaderNodeMath")
    denom_safe.operation = "MAXIMUM"
    denom_safe.inputs[1].default_value = 1e-6

    sub_dist = nodes.new("ShaderNodeMath")
    sub_dist.operation = "SUBTRACT"

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"

    inv = nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0

    max0 = nodes.new("ShaderNodeMath")
    max0.operation = "MAXIMUM"
    max0.inputs[1].default_value = 0.0

    min1 = nodes.new("ShaderNodeMath")
    min1.operation = "MINIMUM"
    min1.inputs[1].default_value = 1.0

    num = nodes.new("ShaderNodeMath")
    num.operation = "SUBTRACT"

    ramp_denom = nodes.new("ShaderNodeMath")
    ramp_denom.operation = "SUBTRACT"

    ramp_denom_safe = nodes.new("ShaderNodeMath")
    ramp_denom_safe.operation = "MAXIMUM"
    ramp_denom_safe.inputs[1].default_value = 1e-6

    ramp_div = nodes.new("ShaderNodeMath")
    ramp_div.operation = "DIVIDE"

    ramp_max0 = nodes.new("ShaderNodeMath")
    ramp_max0.operation = "MAXIMUM"
    ramp_max0.inputs[1].default_value = 0.0

    ramp_min1 = nodes.new("ShaderNodeMath")
    ramp_min1.operation = "MINIMUM"
    ramp_min1.inputs[1].default_value = 1.0

    links.new(gin.outputs["Path Object"], object_info.inputs["Object"])
    links.new(object_info.outputs["Geometry"], resample.inputs["Curve"])
    links.new(gin.outputs["Sample Count"], resample.inputs["Count"])
    links.new(resample.outputs["Curve"], curve_to_points.inputs["Curve"])

    links.new(curve_to_points.outputs["Points"], set_position.inputs["Geometry"])

    links.new(gin.outputs["Terrain"], raycast.inputs["Target Geometry"])
    links.new(path_pos.outputs["Position"], raycast.inputs["Source Position"])
    if "Ray Length" in raycast.inputs:
        links.new(gin.outputs["Ray Length"], raycast.inputs["Ray Length"])

    hit_position = raycast.outputs.get("Hit Position") or raycast.outputs[1]
    links.new(hit_position, set_position.inputs["Position"])
    is_hit = raycast.outputs.get("Is Hit") or raycast.outputs[0]
    links.new(set_position.outputs["Geometry"], delete_geometry.inputs["Geometry"])
    links.new(is_hit, delete_geometry.inputs["Selection"])

    links.new(delete_geometry.outputs["Geometry"], proximity.inputs["Target"])
    links.new(gin.outputs["Position"], proximity.inputs["Source Position"])

    distance = proximity.outputs.get("Distance") or proximity.outputs[1]

    links.new(gin.outputs["Width"], add_total.inputs[0])
    links.new(gin.outputs["Falloff"], add_total.inputs[1])

    links.new(add_total.outputs["Value"], denom_safe.inputs[0])

    links.new(distance, sub_dist.inputs[0])
    links.new(gin.outputs["Width"], sub_dist.inputs[1])

    links.new(sub_dist.outputs["Value"], div.inputs[0])
    links.new(denom_safe.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], inv.inputs[1])
    links.new(inv.outputs["Value"], max0.inputs[0])
    links.new(max0.outputs["Value"], min1.inputs[0])

    links.new(min1.outputs["Value"], num.inputs[0])
    links.new(gin.outputs["Ramp Low"], num.inputs[1])

    links.new(gin.outputs["Ramp High"], ramp_denom.inputs[0])
    links.new(gin.outputs["Ramp Low"], ramp_denom.inputs[1])

    links.new(ramp_denom.outputs["Value"], ramp_denom_safe.inputs[0])

    links.new(num.outputs["Value"], ramp_div.inputs[0])
    links.new(ramp_denom_safe.outputs["Value"], ramp_div.inputs[1])

    links.new(ramp_div.outputs["Value"], ramp_max0.inputs[0])
    links.new(ramp_max0.outputs["Value"], ramp_min1.inputs[0])

    links.new(ramp_min1.outputs["Value"], gout.inputs["Mask"])

    return ng


def add_path_mask_node(
    nt,
    mask_def: PathMask,
    *,
    terrain_socket: bpy.types.NodeSocket,
    group_name: str = "TerrainPathMask",
) -> tuple[MaskSocket, list[Node]]:
    path_obj = _ensure_path_object(mask_def.path_object_name)

    mask_group = bpy.data.node_groups.get(group_name) or create_path_mask_group(
        group_name
    )

    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group
    node.label = f"Mask: Path ({mask_def.path_object_name})"

    pos_node = nt.nodes.new("GeometryNodeInputPosition")
    nt.links.new(terrain_socket, node.inputs["Terrain"])
    nt.links.new(pos_node.outputs["Position"], node.inputs["Position"])

    try:
        node.inputs["Path Object"].default_value = path_obj
    except Exception:
        pass
    node.inputs["Width"].default_value = float(mask_def.width)
    node.inputs["Falloff"].default_value = float(mask_def.falloff)
    node.inputs["Sample Count"].default_value = int(mask_def.sample_count)
    node.inputs["Ray Length"].default_value = float(mask_def.ray_length)
    node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    return node.outputs["Mask"], [pos_node, node]
