from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.paths.path_source import add_path_source_nodes, ensure_curve_object
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    clear_group_interface,
    ensure_geo_nodes_modifier,
    get_terrain_object,
    group_has_io,
    remove_node_group,
)
from terrain_layers.utility.rearrange import arrange_nodes

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


def _add_portal_segment_nodes(
    ng: bpy.types.NodeTree,
    *,
    path_socket: bpy.types.NodeSocket,
    radius_socket: bpy.types.NodeSocket,
    trim_start: float,
    trim_end: float,
    flare_max: float,
    flare_zone: float,
    fill_caps: bool,
    label: str,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    nodes, links = ng.nodes, ng.links

    trim = nodes.new("GeometryNodeTrimCurve")
    trim.label = label
    try:
        trim.mode = "FACTOR"
    except Exception:
        pass
    trim.inputs["Start"].default_value = trim_start
    trim.inputs["End"].default_value = trim_end
    links.new(path_socket, trim.inputs["Curve"])

    resample = nodes.new("GeometryNodeResampleCurve")
    try:
        resample.mode = "COUNT"
    except Exception:
        pass
    resample.inputs["Count"].default_value = 32
    links.new(trim.outputs["Curve"], resample.inputs["Curve"])

    spline_parameter = nodes.new("GeometryNodeSplineParameter")

    one_minus_factor = nodes.new("ShaderNodeMath")
    one_minus_factor.operation = "SUBTRACT"
    one_minus_factor.inputs[0].default_value = 1.0
    links.new(spline_parameter.outputs["Factor"], one_minus_factor.inputs[1])

    distance_to_end = nodes.new("ShaderNodeMath")
    distance_to_end.operation = "MINIMUM"
    links.new(spline_parameter.outputs["Factor"], distance_to_end.inputs[0])
    links.new(one_minus_factor.outputs["Value"], distance_to_end.inputs[1])

    flare = nodes.new("ShaderNodeMapRange")
    flare.clamp = True
    flare.inputs["From Min"].default_value = 0.0
    flare.inputs["From Max"].default_value = flare_zone
    flare.inputs["To Min"].default_value = flare_max
    flare.inputs["To Max"].default_value = 1.0
    links.new(distance_to_end.outputs["Value"], flare.inputs["Value"])

    scaled_radius = nodes.new("ShaderNodeMath")
    scaled_radius.operation = "MULTIPLY"
    links.new(radius_socket, scaled_radius.inputs[0])
    links.new(flare.outputs["Result"], scaled_radius.inputs[1])

    set_curve_radius = nodes.new("GeometryNodeSetCurveRadius")
    links.new(resample.outputs["Curve"], set_curve_radius.inputs["Curve"])
    links.new(scaled_radius.outputs["Value"], set_curve_radius.inputs["Radius"])

    curve_circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    try:
        curve_circle.mode = "RADIUS"
    except Exception:
        pass
    curve_circle.inputs["Resolution"].default_value = 24
    curve_circle.inputs["Radius"].default_value = 1.0

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    if "Fill Caps" in curve_to_mesh.inputs:
        curve_to_mesh.inputs["Fill Caps"].default_value = fill_caps
    links.new(set_curve_radius.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    links.new(curve_circle.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])

    created_nodes = [
        trim,
        resample,
        spline_parameter,
        one_minus_factor,
        distance_to_end,
        flare,
        scaled_radius,
        set_curve_radius,
        curve_circle,
        curve_to_mesh,
    ]
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
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Radius", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Tunnel Mesh", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    curve_circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    try:
        curve_circle.mode = "RADIUS"
    except Exception:
        pass
    curve_circle.inputs["Resolution"].default_value = 20
    links.new(gin.outputs["Radius"], curve_circle.inputs["Radius"])

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    if "Fill Caps" in curve_to_mesh.inputs:
        curve_to_mesh.inputs["Fill Caps"].default_value = False
    links.new(gin.outputs["Path Geometry"], curve_to_mesh.inputs["Curve"])
    links.new(curve_circle.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])

    set_smooth = nodes.new("GeometryNodeSetShadeSmooth")
    if "Shade Smooth" in set_smooth.inputs:
        set_smooth.inputs["Shade Smooth"].default_value = True
    links.new(curve_to_mesh.outputs["Mesh"], set_smooth.inputs["Geometry"])
    links.new(set_smooth.outputs["Geometry"], gout.inputs["Tunnel Mesh"])

    frame_nodes(ng, "Tunnel Tube", [curve_circle, curve_to_mesh, set_smooth])
    arrange_nodes(ng)
    return ng


def create_tunnel_portal_collar_group(
    group_name: str = "TerrainTunnelPortalCollar",
) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(group_name)
    if ng is None:
        ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Radius", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Collar Mesh", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    join = nodes.new("GeometryNodeJoinGeometry")

    start_mesh, start_nodes = _add_portal_segment_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        radius_socket=gin.outputs["Radius"],
        trim_start=0.0,
        trim_end=0.16,
        flare_max=1.28,
        flare_zone=0.55,
        fill_caps=False,
        label="Start Collar",
    )
    end_mesh, end_nodes = _add_portal_segment_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        radius_socket=gin.outputs["Radius"],
        trim_start=0.84,
        trim_end=1.0,
        flare_max=1.28,
        flare_zone=0.55,
        fill_caps=False,
        label="End Collar",
    )

    links.new(start_mesh, join.inputs["Geometry"])
    links.new(end_mesh, join.inputs["Geometry"])

    set_smooth = nodes.new("GeometryNodeSetShadeSmooth")
    if "Shade Smooth" in set_smooth.inputs:
        set_smooth.inputs["Shade Smooth"].default_value = True
    links.new(join.outputs["Geometry"], set_smooth.inputs["Geometry"])
    links.new(set_smooth.outputs["Geometry"], gout.inputs["Collar Mesh"])

    frame_nodes(ng, "Portal Collar", [join, *start_nodes, *end_nodes, set_smooth])
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
    ng.interface.new_socket(
        name="Radius", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Cutter Mesh", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    join = nodes.new("GeometryNodeJoinGeometry")

    start_mesh, start_nodes = _add_portal_segment_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        radius_socket=gin.outputs["Radius"],
        trim_start=0.0,
        trim_end=0.2,
        flare_max=1.14,
        flare_zone=0.5,
        fill_caps=True,
        label="Start Cutter",
    )
    end_mesh, end_nodes = _add_portal_segment_nodes(
        ng,
        path_socket=gin.outputs["Path Geometry"],
        radius_socket=gin.outputs["Radius"],
        trim_start=0.8,
        trim_end=1.0,
        flare_max=1.14,
        flare_zone=0.5,
        fill_caps=True,
        label="End Cutter",
    )

    links.new(start_mesh, join.inputs["Geometry"])
    links.new(end_mesh, join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], gout.inputs["Cutter Mesh"])

    frame_nodes(ng, "Portal Cutter", [join, *start_nodes, *end_nodes])
    arrange_nodes(ng)
    return ng


def create_tunnel_modifier(config: "TerrainConfig"):
    tunnel = config.tunnel
    if tunnel is None:
        return None

    obj = get_terrain_object(config.object_name)
    ensure_curve_object(tunnel.curve_object_name)

    mod_name = config.tunnel_modifier_name
    remove_node_group(mod_name)
    ng = bpy.data.node_groups.new(mod_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    tube_group = bpy.data.node_groups.get("TerrainTunnelTube")
    if tube_group is None or not group_has_io(
        tube_group,
        ins=["Path Geometry", "Radius"],
        outs=["Tunnel Mesh"],
    ):
        tube_group = create_tunnel_tube_group()
    collar_group = bpy.data.node_groups.get("TerrainTunnelPortalCollar")
    if collar_group is None or not group_has_io(
        collar_group,
        ins=["Path Geometry", "Radius"],
        outs=["Collar Mesh"],
    ):
        collar_group = create_tunnel_portal_collar_group()

    path_geometry, source_nodes = add_path_source_nodes(
        ng,
        group_namespace="TunnelSource",
        path_object_name=tunnel.curve_object_name,
        path_collection_name=None,
    )

    radius_value = nodes.new("ShaderNodeValue")
    radius_value.label = "Tunnel Radius"
    radius_value.outputs[0].default_value = float(tunnel.radius)

    tunnel_mesh = nodes.new("GeometryNodeGroup")
    tunnel_mesh.node_tree = tube_group
    tunnel_mesh.label = "Tunnel Tube"
    links.new(path_geometry, tunnel_mesh.inputs["Path Geometry"])
    links.new(radius_value.outputs[0], tunnel_mesh.inputs["Radius"])

    collar_mesh = nodes.new("GeometryNodeGroup")
    collar_mesh.node_tree = collar_group
    collar_mesh.label = "Tunnel Portal Collar"
    links.new(path_geometry, collar_mesh.inputs["Path Geometry"])
    links.new(radius_value.outputs[0], collar_mesh.inputs["Radius"])

    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(gin.outputs["Geometry"], join.inputs["Geometry"])
    links.new(tunnel_mesh.outputs["Tunnel Mesh"], join.inputs["Geometry"])
    links.new(collar_mesh.outputs["Collar Mesh"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], gout.inputs["Geometry"])

    tunnel_nodes = [*source_nodes, radius_value, tunnel_mesh, collar_mesh, join]
    frame_nodes(ng, "Tunnel MVP", tunnel_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng
