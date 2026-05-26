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

    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(gin.outputs["Geometry"], join.inputs["Geometry"])
    links.new(tunnel_mesh.outputs["Tunnel Mesh"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], gout.inputs["Geometry"])

    tunnel_nodes = [*source_nodes, radius_value, tunnel_mesh, join]
    frame_nodes(ng, "Tunnel MVP", tunnel_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng
