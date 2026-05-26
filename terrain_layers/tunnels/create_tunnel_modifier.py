from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.paths.path_source import add_path_source_nodes, ensure_curve_object
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    ensure_geo_nodes_modifier,
    get_terrain_object,
    remove_node_group,
)
from terrain_layers.utility.rearrange import arrange_nodes

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


def _move_modifier_before(
    obj: bpy.types.Object,
    modifier_name: str,
    before_modifier_name: str,
) -> None:
    from_index = obj.modifiers.find(modifier_name)
    to_index = obj.modifiers.find(before_modifier_name)
    if from_index == -1 or to_index == -1 or from_index <= to_index:
        return
    try:
        obj.modifiers.move(from_index, to_index)
    except Exception:
        pass


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

    path_geometry, source_nodes = add_path_source_nodes(
        ng,
        group_namespace="TunnelSource",
        path_object_name=tunnel.curve_object_name,
        path_collection_name=None,
    )

    radius_value = nodes.new("ShaderNodeValue")
    radius_value.label = "Tunnel Radius"
    radius_value.outputs[0].default_value = float(tunnel.radius)

    reroute = nodes.new("NodeReroute")
    links.new(gin.outputs["Geometry"], reroute.inputs[0])
    links.new(reroute.outputs[0], gout.inputs["Geometry"])

    path_socket = path_geometry
    if path_socket is not None:
        # Keep the path source live in the node tree so the curve reference is
        # validated and ready for the next tunnel implementation step.
        viewer = nodes.new("NodeReroute")
        links.new(path_socket, viewer.inputs[0])
        source_nodes.append(viewer)

    tunnel_nodes = [*source_nodes, radius_value, reroute]
    frame_nodes(ng, "Tunnel MVP", tunnel_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
