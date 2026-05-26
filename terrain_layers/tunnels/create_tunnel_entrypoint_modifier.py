from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.tunnels.create_tunnel_modifier import (
    create_tunnel_portal_cutter_group,
)
from terrain_layers.paths.path_source import add_path_source_nodes, ensure_curve_object
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    ensure_geo_nodes_modifier,
    get_terrain_object,
    group_has_io,
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


def create_tunnel_entrypoint_modifier(config: "TerrainConfig"):
    tunnel = config.tunnel
    if tunnel is None:
        return None

    obj = get_terrain_object(config.object_name)
    ensure_curve_object(tunnel.curve_object_name)

    mod_name = config.tunnel_entrypoint_modifier_name
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

    cutter_group = bpy.data.node_groups.get("TerrainTunnelPortalCutter")
    if cutter_group is None or not group_has_io(
        cutter_group,
        ins=["Path Geometry", "Radius"],
        outs=["Cutter Mesh"],
    ):
        cutter_group = create_tunnel_portal_cutter_group()

    path_geometry, source_nodes = add_path_source_nodes(
        ng,
        group_namespace="TunnelEntrypointSource",
        path_object_name=tunnel.curve_object_name,
        path_collection_name=None,
    )

    radius_value = nodes.new("ShaderNodeValue")
    radius_value.label = "Tunnel Radius"
    radius_value.outputs[0].default_value = float(tunnel.radius)

    cutter_radius = nodes.new("ShaderNodeMath")
    cutter_radius.operation = "MULTIPLY"
    cutter_radius.inputs[1].default_value = 1.02
    links.new(radius_value.outputs[0], cutter_radius.inputs[0])

    portal_cutter = nodes.new("GeometryNodeGroup")
    portal_cutter.node_tree = cutter_group
    portal_cutter.label = "Tunnel Portal Cutter"
    links.new(path_geometry, portal_cutter.inputs["Path Geometry"])
    links.new(cutter_radius.outputs["Value"], portal_cutter.inputs["Radius"])

    mesh_boolean = nodes.new("GeometryNodeMeshBoolean")
    try:
        mesh_boolean.operation = "DIFFERENCE"
    except Exception:
        pass
    try:
        mesh_boolean.solver = "EXACT"
    except Exception:
        pass
    if hasattr(mesh_boolean, "self_intersection"):
        try:
            mesh_boolean.self_intersection = True
        except Exception:
            pass
    links.new(gin.outputs["Geometry"], mesh_boolean.inputs["Mesh 1"])
    links.new(portal_cutter.outputs["Cutter Mesh"], mesh_boolean.inputs["Mesh 2"])
    links.new(mesh_boolean.outputs["Mesh"], gout.inputs["Geometry"])

    entrypoint_nodes = [
        *source_nodes,
        radius_value,
        cutter_radius,
        portal_cutter,
        mesh_boolean,
    ]
    frame_nodes(ng, "Tunnel Entrypoints MVP", entrypoint_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
