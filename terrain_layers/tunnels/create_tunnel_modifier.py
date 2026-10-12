from __future__ import annotations

import bpy

from terrain_layers.tunnels.tunnel_types import TunnelShape
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import clear_group_interface
from terrain_layers.utility.rearrange import arrange_nodes

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
    profile_socket: bpy.types.NodeSocket,
    fill_caps: bool,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    nodes, links = ng.nodes, ng.links

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    if "Fill Caps" in curve_to_mesh.inputs:
        curve_to_mesh.inputs["Fill Caps"].default_value = fill_caps
    links.new(curve_socket, curve_to_mesh.inputs["Curve"])
    links.new(profile_socket, curve_to_mesh.inputs["Profile Curve"])

    return curve_to_mesh.outputs["Mesh"], [curve_to_mesh]


def create_tunnel_portal_cutter_group(
    group_name: str = "TerrainTunnelPortalCutter",
    *,
    shape: TunnelShape = TunnelShape.CIRCLE,
) -> bpy.types.NodeTree:
    shape = TunnelShape(shape)
    ng = bpy.data.node_groups.get(group_name)
    if ng is None:
        ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Path Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    dimensions = ("Radius",) if shape == TunnelShape.CIRCLE else ("Width", "Height")
    for name in dimensions:
        ng.interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketFloat")
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
    if shape == TunnelShape.CIRCLE:
        profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
        profile.mode = "RADIUS"
        profile.inputs["Resolution"].default_value = 24
    else:
        profile = nodes.new("GeometryNodeCurvePrimitiveQuadrilateral")
        profile.mode = "RECTANGLE"
    for name in dimensions:
        links.new(gin.outputs[name], profile.inputs[name])

    cutter_mesh, mesh_nodes = _add_curve_to_mesh_nodes(
        ng,
        curve_socket=cutter_curve,
        profile_socket=profile.outputs["Curve"],
        fill_caps=True,
    )

    links.new(cutter_mesh, gout.inputs["Cutter Mesh"])
    frame_nodes(ng, "Tunnel Cutter", [*curve_nodes, profile, *mesh_nodes])
    arrange_nodes(ng)
    return ng
