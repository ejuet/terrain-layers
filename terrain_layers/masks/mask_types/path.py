from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal

import bpy

from terrain_layers.masks.mask_types.type_helpers import MaskSocket
from terrain_layers.utility.type_helpers import Node
from terrain_layers.paths.path_source import add_path_source_nodes, path_source_label
from terrain_layers.paths.path_types import DeformationSettings
from terrain_layers.utility.geo_nodes import (
    clear_group_interface,
    group_has_io,
    remove_node_group,
)


@dataclass(frozen=True, slots=True)
class RoadPathSettings:
    width: float = 2.5
    falloff: float = 1.0
    sample_count: int = 256
    ray_length: float = 10000.0
    ramp_low: float = 0.0
    ramp_high: float = 1.0
    deformation_settings: DeformationSettings = field(
        default_factory=DeformationSettings
    )


@dataclass(frozen=True, slots=True)
class RoadPathSettingsOverride:
    width: float | None = None
    falloff: float | None = None
    sample_count: int | None = None
    ray_length: float | None = None
    ramp_low: float | None = None
    ramp_high: float | None = None
    deformation_settings: DeformationSettings | None = None


@dataclass(frozen=True, slots=True)
class RoadNetworkPath:
    """
    One road source inside a road network.
    Exactly one of path_object_name or path_collection_name must be set.
    path_settings overrides the network-level defaults for this source only.
    """

    path_object_name: str | None = None
    path_collection_name: str | None = None
    path_settings: RoadPathSettingsOverride | None = None


@dataclass(frozen=True, slots=True)
class RoadNetworkMask:
    """
    Mask that creates a road network from multiple curve objects and/or
    collections of curve objects. Shared defaults live in path_settings and can
    be overridden per source.
    """

    type: Literal["road_network"] = "road_network"
    paths: list[RoadNetworkPath] = field(default_factory=list)
    path_settings: RoadPathSettings = field(default_factory=RoadPathSettings)


def _merge_path_settings(
    base: RoadPathSettings,
    override: RoadPathSettingsOverride | None,
) -> RoadPathSettings:
    if override is None:
        return base
    values = {}
    for field in fields(RoadPathSettings):
        override_value = getattr(override, field.name)
        values[field.name] = (
            getattr(base, field.name) if override_value is None else override_value
        )
    return RoadPathSettings(**values)


def _path_source_label(path_def: RoadNetworkPath) -> str:
    return path_source_label(
        path_object_name=path_def.path_object_name,
        path_collection_name=path_def.path_collection_name,
    )


def _safe_key(value: str | None) -> str:
    value = (value or "").strip()
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in value) or "Path"


def _add_path_source_nodes(
    nt: bpy.types.NodeTree,
    path_def: RoadNetworkPath,
    *,
    group_namespace: str = "RoadPathSource",
) -> tuple[bpy.types.NodeSocket, list[Node]]:
    return add_path_source_nodes(
        nt,
        group_namespace=group_namespace,
        path_object_name=path_def.path_object_name,
        path_collection_name=path_def.path_collection_name,
    )


def _road_network_mask_group_name(mask_def: RoadNetworkMask) -> str:
    parts: list[str] = []
    for path_def in mask_def.paths:
        settings = _merge_path_settings(mask_def.path_settings, path_def.path_settings)
        parts.append(
            "_".join(
                [
                    _safe_key(_path_source_label(path_def)),
                    f"W{settings.width:g}",
                    f"F{settings.falloff:g}",
                    f"S{settings.sample_count}",
                    f"R{settings.ray_length:g}",
                    f"L{settings.ramp_low:g}",
                    f"H{settings.ramp_high:g}",
                ]
            ).replace(".", "_")
        )
    suffix = "__".join(parts)[:180] or "Empty"
    return f"TerrainRoadNetworkMask_{suffix}"


def create_road_network_mask_stack_group(
    mask_def: RoadNetworkMask,
    *,
    mask_group: bpy.types.NodeTree,
) -> bpy.types.NodeTree:
    group_name = _road_network_mask_group_name(mask_def)
    ng = bpy.data.node_groups.get(group_name)
    if ng is None:
        ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Terrain", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Position", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(name="Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    combined_mask: bpy.types.NodeSocket | None = None

    for path_def in mask_def.paths:
        settings = _merge_path_settings(mask_def.path_settings, path_def.path_settings)
        path_geometry, _ = _add_path_source_nodes(
            ng,
            path_def,
            group_namespace="RoadPathMaskSource",
        )

        mask_node = nodes.new("GeometryNodeGroup")
        mask_node.node_tree = mask_group
        mask_node.label = f"Road Path Mask: {_path_source_label(path_def)}"

        links.new(gin.outputs["Terrain"], mask_node.inputs["Terrain"])
        links.new(gin.outputs["Position"], mask_node.inputs["Position"])
        links.new(path_geometry, mask_node.inputs["Path Geometry"])
        mask_node.inputs["Width"].default_value = float(settings.width)
        mask_node.inputs["Falloff"].default_value = float(settings.falloff)
        mask_node.inputs["Sample Count"].default_value = int(settings.sample_count)
        mask_node.inputs["Ray Length"].default_value = float(settings.ray_length)
        mask_node.inputs["Ramp Low"].default_value = float(settings.ramp_low)
        mask_node.inputs["Ramp High"].default_value = float(settings.ramp_high)

        if combined_mask is None:
            combined_mask = mask_node.outputs["Mask"]
            continue

        max_node = nodes.new("ShaderNodeMath")
        max_node.operation = "MAXIMUM"
        links.new(combined_mask, max_node.inputs[0])
        links.new(mask_node.outputs["Mask"], max_node.inputs[1])
        combined_mask = max_node.outputs["Value"]

    if combined_mask is None:
        raise RuntimeError("RoadNetworkMask must contain at least one path source.")

    links.new(combined_mask, gout.inputs["Mask"])

    return ng


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
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
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
    invert_hit = nodes.new("FunctionNodeBooleanMath")
    invert_hit.operation = "NOT"

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

    links.new(gin.outputs["Path Geometry"], resample.inputs["Curve"])
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
    links.new(is_hit, invert_hit.inputs[0])
    links.new(invert_hit.outputs["Boolean"], delete_geometry.inputs["Selection"])

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


def add_road_network_mask_node(
    nt,
    mask_def: RoadNetworkMask,
    *,
    terrain_socket: bpy.types.NodeSocket,
    group_name: str = "TerrainPathMask",
) -> tuple[MaskSocket, list[Node]]:
    mask_group = bpy.data.node_groups.get(group_name)
    if mask_group is None or not group_has_io(
        mask_group,
        ins=[
            "Terrain",
            "Position",
            "Path Geometry",
            "Width",
            "Falloff",
            "Sample Count",
            "Ray Length",
            "Ramp Low",
            "Ramp High",
        ],
        outs=["Mask"],
    ):
        mask_group = create_path_mask_group(group_name)

    if not mask_def.paths:
        raise RuntimeError("RoadNetworkMask must contain at least one path source.")

    created_nodes: list[Node] = []
    pos_node = nt.nodes.new("GeometryNodeInputPosition")
    created_nodes.append(pos_node)

    network_node = nt.nodes.new("GeometryNodeGroup")
    network_node.node_tree = create_road_network_mask_stack_group(
        mask_def,
        mask_group=mask_group,
    )
    network_node.label = "Road Network Mask"

    nt.links.new(terrain_socket, network_node.inputs["Terrain"])
    nt.links.new(pos_node.outputs["Position"], network_node.inputs["Position"])
    created_nodes.append(network_node)

    return network_node.outputs["Mask"], created_nodes
