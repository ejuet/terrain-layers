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

    path_geometry, source_nodes = add_path_source_nodes(
        ng,
        group_namespace="TunnelEntrypointSource",
        path_object_name=tunnel.curve_object_name,
        path_collection_name=None,
    )

    resample = nodes.new("GeometryNodeResampleCurve")
    try:
        resample.mode = "COUNT"
    except Exception:
        pass
    resample.inputs["Count"].default_value = 2
    links.new(path_geometry, resample.inputs["Curve"])

    curve_to_points = nodes.new("GeometryNodeCurveToPoints")
    try:
        curve_to_points.mode = "EVALUATED"
    except Exception:
        pass
    links.new(resample.outputs["Curve"], curve_to_points.inputs["Curve"])

    radius_value = nodes.new("ShaderNodeValue")
    radius_value.label = "Tunnel Radius"
    radius_value.outputs[0].default_value = float(tunnel.radius)

    portal_radius = nodes.new("ShaderNodeMath")
    portal_radius.operation = "MULTIPLY"
    portal_radius.inputs[1].default_value = 1.15
    links.new(radius_value.outputs[0], portal_radius.inputs[0])

    proximity = nodes.new("GeometryNodeProximity")
    try:
        proximity.target_element = "POINTS"
    except Exception:
        pass
    links.new(curve_to_points.outputs["Points"], proximity.inputs["Target"])

    terrain_position = nodes.new("GeometryNodeInputPosition")
    links.new(terrain_position.outputs["Position"], proximity.inputs["Source Position"])

    compare = nodes.new("FunctionNodeCompare")
    compare.data_type = "FLOAT"
    compare.operation = "LESS_EQUAL"
    links.new(proximity.outputs["Distance"], compare.inputs[0])
    links.new(portal_radius.outputs["Value"], compare.inputs[1])

    delete_portal_faces = nodes.new("GeometryNodeDeleteGeometry")
    if hasattr(delete_portal_faces, "domain"):
        try:
            delete_portal_faces.domain = "FACE"
        except Exception:
            pass
    links.new(gin.outputs["Geometry"], delete_portal_faces.inputs["Geometry"])
    links.new(compare.outputs["Result"], delete_portal_faces.inputs["Selection"])
    links.new(delete_portal_faces.outputs["Geometry"], gout.inputs["Geometry"])

    entrypoint_nodes = [
        *source_nodes,
        resample,
        curve_to_points,
        radius_value,
        portal_radius,
        terrain_position,
        proximity,
        compare,
        delete_portal_faces,
    ]
    frame_nodes(ng, "Tunnel Entrypoints MVP", entrypoint_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
