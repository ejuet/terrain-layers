from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.paths.path_source import add_path_source_nodes, ensure_curve_object
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    clear_group_interface,
    ensure_geo_nodes_modifier,
    get_terrain_object,
    remove_node_group,
)
from terrain_layers.utility.rearrange import arrange_nodes

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig

END_FLARE_ZONE = 0.14
VISIBLE_END_FLARE = 1.0
CUTTER_END_FLARE = 1.12


def _add_tunnel_curve_nodes(
    ng: bpy.types.NodeTree,
    *,
    path_socket: bpy.types.NodeSocket,
    label: str,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    nodes, links = ng.nodes, ng.links

    resample = nodes.new("GeometryNodeResampleCurve")
    try:
        resample.mode = "COUNT"
    except Exception:
        pass
    resample.inputs["Count"].default_value = 96
    resample.label = f"{label}: Resample"
    links.new(path_socket, resample.inputs["Curve"])

    created_nodes = [resample]
    return resample.outputs["Curve"], created_nodes


def _add_curve_to_mesh_nodes(
    ng: bpy.types.NodeTree,
    *,
    curve_socket: bpy.types.NodeSocket,
    width_socket: bpy.types.NodeSocket,
    fill_caps: bool,
    resolution: int = 20,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    nodes, links = ng.nodes, ng.links

    profile_radius = nodes.new("ShaderNodeMath")
    profile_radius.operation = "MULTIPLY"
    profile_radius.inputs[1].default_value = 0.5
    links.new(width_socket, profile_radius.inputs[0])

    curve_circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    try:
        curve_circle.mode = "RADIUS"
    except Exception:
        pass
    curve_circle.inputs["Resolution"].default_value = resolution
    links.new(profile_radius.outputs["Value"], curve_circle.inputs["Radius"])

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    if "Fill Caps" in curve_to_mesh.inputs:
        curve_to_mesh.inputs["Fill Caps"].default_value = fill_caps
    links.new(curve_socket, curve_to_mesh.inputs["Curve"])
    links.new(curve_circle.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])

    created_nodes = [profile_radius, curve_circle, curve_to_mesh]
    return curve_to_mesh.outputs["Mesh"], created_nodes


def create_tunnel_tube_group(
    group_name: str = "TerrainTunnelTube",
) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(group_name)
    if ng is None:
        ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Terrain Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(name="Width", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        name="Tunnel Mesh", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    tunnel_curve, curve_nodes = _add_tunnel_curve_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        label="Visible Tunnel",
    )

    curve_position = nodes.new("GeometryNodeInputPosition")

    ray_offset = nodes.new("ShaderNodeCombineXYZ")
    ray_offset.inputs["Z"].default_value = 10000.0

    ray_source = nodes.new("ShaderNodeVectorMath")
    ray_source.operation = "ADD"
    links.new(curve_position.outputs["Position"], ray_source.inputs[0])
    links.new(ray_offset.outputs["Vector"], ray_source.inputs[1])

    terrain_raycast = nodes.new("GeometryNodeRaycast")
    try:
        terrain_raycast.data_type = "FLOAT"
    except Exception:
        pass
    if "Ray Direction" in terrain_raycast.inputs:
        terrain_raycast.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)
    if "Ray Length" in terrain_raycast.inputs:
        terrain_raycast.inputs["Ray Length"].default_value = 20000.0
    links.new(
        gin.outputs["Terrain Geometry"], terrain_raycast.inputs["Target Geometry"]
    )
    links.new(ray_source.outputs["Vector"], terrain_raycast.inputs["Source Position"])

    separate_curve = nodes.new("ShaderNodeSeparateXYZ")
    separate_hit = nodes.new("ShaderNodeSeparateXYZ")
    links.new(curve_position.outputs["Position"], separate_curve.inputs["Vector"])
    hit_position = (
        terrain_raycast.outputs.get("Hit Position") or terrain_raycast.outputs[1]
    )
    links.new(hit_position, separate_hit.inputs["Vector"])

    clearance = nodes.new("ShaderNodeMath")
    clearance.operation = "MULTIPLY"
    clearance.inputs[1].default_value = 0.55
    links.new(gin.outputs["Width"], clearance.inputs[0])

    target_z = nodes.new("ShaderNodeMath")
    target_z.operation = "SUBTRACT"
    links.new(separate_hit.outputs["Z"], target_z.inputs[0])
    links.new(clearance.outputs["Value"], target_z.inputs[1])

    min_z = nodes.new("ShaderNodeMath")
    min_z.operation = "MINIMUM"
    links.new(separate_curve.outputs["Z"], min_z.inputs[0])
    links.new(target_z.outputs["Value"], min_z.inputs[1])

    adjusted_position = nodes.new("ShaderNodeCombineXYZ")
    links.new(separate_curve.outputs["X"], adjusted_position.inputs["X"])
    links.new(separate_curve.outputs["Y"], adjusted_position.inputs["Y"])
    links.new(min_z.outputs["Value"], adjusted_position.inputs["Z"])

    set_curve_position = nodes.new("GeometryNodeSetPosition")
    links.new(tunnel_curve, set_curve_position.inputs["Geometry"])
    links.new(
        adjusted_position.outputs["Vector"], set_curve_position.inputs["Position"]
    )

    tunnel_mesh, mesh_nodes = _add_curve_to_mesh_nodes(
        ng,
        curve_socket=set_curve_position.outputs["Geometry"],
        width_socket=gin.outputs["Width"],
        fill_caps=False,
    )

    set_smooth = nodes.new("GeometryNodeSetShadeSmooth")
    if "Shade Smooth" in set_smooth.inputs:
        set_smooth.inputs["Shade Smooth"].default_value = True
    links.new(tunnel_mesh, set_smooth.inputs["Geometry"])
    links.new(set_smooth.outputs["Geometry"], gout.inputs["Tunnel Mesh"])

    frame_nodes(
        ng,
        "Tunnel Tube",
        [
            *curve_nodes,
            curve_position,
            ray_offset,
            ray_source,
            terrain_raycast,
            separate_curve,
            separate_hit,
            clearance,
            target_z,
            min_z,
            adjusted_position,
            set_curve_position,
            *mesh_nodes,
            set_smooth,
        ],
    )
    arrange_nodes(ng)
    return ng


def create_tunnel_portal_cutter_group(
    group_name: str = "TerrainTunnelPortalCutter",
) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(group_name)
    if ng is None:
        ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(name="Width", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        name="Cutter Mesh", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    cutter_curve, curve_nodes = _add_tunnel_curve_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        label="Tunnel Cutter",
    )
    cutter_mesh, mesh_nodes = _add_curve_to_mesh_nodes(
        ng,
        curve_socket=cutter_curve,
        width_socket=gin.outputs["Width"],
        fill_caps=True,
        resolution=24,
    )

    links.new(cutter_mesh, gout.inputs["Cutter Mesh"])
    frame_nodes(ng, "Tunnel Cutter", [*curve_nodes, *mesh_nodes])
    arrange_nodes(ng)
    return ng
