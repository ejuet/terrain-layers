from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.tunnels.create_tunnel_modifier import (
    create_tunnel_portal_cutter_group,
)
from terrain_layers.tunnels.tunnel_types import TunnelShape
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

    cutter_group = create_tunnel_portal_cutter_group(shape=tunnel.shape)

    path_geometry, source_nodes = add_path_source_nodes(
        ng,
        group_namespace="TunnelEntrypointSource",
        path_object_name=tunnel.curve_object_name,
        path_collection_name=None,
    )

    portal_cutter = nodes.new("GeometryNodeGroup")
    portal_cutter.node_tree = cutter_group
    portal_cutter.label = "Tunnel Portal Cutter"
    links.new(path_geometry, portal_cutter.inputs["Path Geometry"])

    dimensions = (
        {"Radius": tunnel.radius}
        if tunnel.shape == TunnelShape.CIRCLE
        else {"Width": tunnel.width, "Height": tunnel.height}
    )
    dimension_nodes = []
    for name, size in dimensions.items():
        value = nodes.new("ShaderNodeValue")
        value.label = f"Tunnel {name}"
        value.outputs[0].default_value = float(size)

        clearance = nodes.new("ShaderNodeMath")
        clearance.operation = "MULTIPLY"
        clearance.inputs[1].default_value = 1.02
        links.new(value.outputs[0], clearance.inputs[0])
        links.new(clearance.outputs["Value"], portal_cutter.inputs[name])
        dimension_nodes.extend((value, clearance))

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

    # Smooth the boolean cut without changing the terrain mesh topology.
    shade_smooth = nodes.new("GeometryNodeSetShadeSmooth")
    shade_smooth.label = "Smooth Tunnel Cut"
    links.new(mesh_boolean.outputs["Mesh"], shade_smooth.inputs["Mesh"])
    links.new(shade_smooth.outputs["Mesh"], gout.inputs["Geometry"])

    entrypoint_nodes = [
        *source_nodes,
        *dimension_nodes,
        portal_cutter,
        mesh_boolean,
        shade_smooth,
    ]
    frame_nodes(ng, "Tunnel Entrypoints MVP", entrypoint_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
