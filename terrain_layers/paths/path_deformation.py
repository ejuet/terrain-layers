from __future__ import annotations

import bpy

from terrain_layers.config.helpers import sort_layers_by_priority
from terrain_layers.config.config_types import TerrainConfig
from terrain_layers.masks.mask_types.path import (
    RoadNetworkMask,
    _add_path_source_nodes,
    _merge_path_settings,
    _path_source_label,
)
from terrain_layers.utility.type_helpers import Node
from terrain_layers.paths.path_types import DeformationSettings
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    ensure_geo_nodes_modifier,
    get_terrain_object,
    group_has_io,
    remove_node_group,
)
from terrain_layers.utility.rearrange import arrange_nodes


def _effective_value(primary, fallback):
    return fallback if primary is None else primary


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


def has_path_deformation(mask_def: "RoadNetworkMask") -> bool:
    base_settings = mask_def.path_settings
    if base_settings.deformation_settings.enabled:
        return True

    for path_def in mask_def.paths:
        override = path_def.path_settings
        if override is None or override.deformation_settings is None:
            continue
        if override.deformation_settings.enabled:
            return True
    return False


def create_path_deformation_group(group_name: str = "TerrainPathDeformation"):
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Terrain", in_out="INPUT", socket_type="NodeSocketGeometry"
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
        name="Strength", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Vertical Offset", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

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

    set_path_position = nodes.new("GeometryNodeSetPosition")
    delete_geometry = nodes.new("GeometryNodeDeleteGeometry")
    invert_hit = nodes.new("FunctionNodeBooleanMath")
    invert_hit.operation = "NOT"

    proximity = nodes.new("GeometryNodeProximity")
    try:
        proximity.target_element = "POINTS"
    except Exception:
        pass

    terrain_pos = nodes.new("GeometryNodeInputPosition")

    sub_dist = nodes.new("ShaderNodeMath")
    sub_dist.operation = "SUBTRACT"

    overflow_max0 = nodes.new("ShaderNodeMath")
    overflow_max0.operation = "MAXIMUM"
    overflow_max0.inputs[1].default_value = 0.0

    falloff_safe = nodes.new("ShaderNodeMath")
    falloff_safe.operation = "MAXIMUM"
    falloff_safe.inputs[1].default_value = 1e-6

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"

    min1 = nodes.new("ShaderNodeMath")
    min1.operation = "MINIMUM"
    min1.inputs[1].default_value = 1.0

    inv = nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0

    max0 = nodes.new("ShaderNodeMath")
    max0.operation = "MAXIMUM"
    max0.inputs[1].default_value = 0.0

    strength_mul = nodes.new("ShaderNodeMath")
    strength_mul.operation = "MULTIPLY"

    strength_clamp = nodes.new("ShaderNodeClamp")
    strength_clamp.inputs["Min"].default_value = 0.0
    strength_clamp.inputs["Max"].default_value = 1.0

    separate_terrain = nodes.new("ShaderNodeSeparateXYZ")
    separate_nearest = nodes.new("ShaderNodeSeparateXYZ")

    add_offset = nodes.new("ShaderNodeMath")
    add_offset.operation = "ADD"

    combine_target = nodes.new("ShaderNodeCombineXYZ")

    delta = nodes.new("ShaderNodeVectorMath")
    delta.operation = "SUBTRACT"

    scaled_delta = nodes.new("ShaderNodeVectorMath")
    scaled_delta.operation = "SCALE"

    final_pos = nodes.new("ShaderNodeVectorMath")
    final_pos.operation = "ADD"

    set_position = nodes.new("GeometryNodeSetPosition")

    links.new(gin.outputs["Path Geometry"], resample.inputs["Curve"])
    links.new(gin.outputs["Sample Count"], resample.inputs["Count"])
    links.new(resample.outputs["Curve"], curve_to_points.inputs["Curve"])

    links.new(curve_to_points.outputs["Points"], set_path_position.inputs["Geometry"])

    links.new(gin.outputs["Terrain"], raycast.inputs["Target Geometry"])
    links.new(path_pos.outputs["Position"], raycast.inputs["Source Position"])
    if "Ray Length" in raycast.inputs:
        links.new(gin.outputs["Ray Length"], raycast.inputs["Ray Length"])

    hit_position = raycast.outputs.get("Hit Position") or raycast.outputs[1]
    is_hit = raycast.outputs.get("Is Hit") or raycast.outputs[0]
    links.new(hit_position, set_path_position.inputs["Position"])
    links.new(set_path_position.outputs["Geometry"], delete_geometry.inputs["Geometry"])
    links.new(is_hit, invert_hit.inputs[0])
    links.new(invert_hit.outputs["Boolean"], delete_geometry.inputs["Selection"])

    links.new(delete_geometry.outputs["Geometry"], proximity.inputs["Target"])
    links.new(terrain_pos.outputs["Position"], proximity.inputs["Source Position"])

    distance = proximity.outputs.get("Distance") or proximity.outputs[1]
    nearest_position = proximity.outputs.get("Position") or proximity.outputs[2]

    links.new(distance, sub_dist.inputs[0])
    links.new(gin.outputs["Width"], sub_dist.inputs[1])

    links.new(sub_dist.outputs["Value"], overflow_max0.inputs[0])
    links.new(gin.outputs["Falloff"], falloff_safe.inputs[0])
    links.new(overflow_max0.outputs["Value"], div.inputs[0])
    links.new(falloff_safe.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], min1.inputs[0])
    links.new(min1.outputs["Value"], inv.inputs[1])
    links.new(inv.outputs["Value"], max0.inputs[0])

    links.new(max0.outputs["Value"], strength_mul.inputs[0])
    links.new(gin.outputs["Strength"], strength_mul.inputs[1])
    links.new(strength_mul.outputs["Value"], strength_clamp.inputs["Value"])

    links.new(terrain_pos.outputs["Position"], separate_terrain.inputs["Vector"])
    links.new(nearest_position, separate_nearest.inputs["Vector"])

    links.new(separate_terrain.outputs["X"], combine_target.inputs["X"])
    links.new(separate_terrain.outputs["Y"], combine_target.inputs["Y"])
    links.new(separate_nearest.outputs["Z"], add_offset.inputs[0])
    links.new(gin.outputs["Vertical Offset"], add_offset.inputs[1])
    links.new(add_offset.outputs["Value"], combine_target.inputs["Z"])

    links.new(combine_target.outputs["Vector"], delta.inputs[0])
    links.new(terrain_pos.outputs["Position"], delta.inputs[1])
    links.new(delta.outputs["Vector"], scaled_delta.inputs["Vector"])
    links.new(strength_clamp.outputs["Result"], scaled_delta.inputs["Scale"])

    links.new(terrain_pos.outputs["Position"], final_pos.inputs[0])
    links.new(scaled_delta.outputs["Vector"], final_pos.inputs[1])

    links.new(gin.outputs["Terrain"], set_position.inputs["Geometry"])
    links.new(final_pos.outputs["Vector"], set_position.inputs["Position"])
    links.new(set_position.outputs["Geometry"], gout.inputs["Geometry"])

    return ng


def add_road_network_path_deformation(
    nt: bpy.types.NodeTree,
    mask_def: "RoadNetworkMask",
    *,
    terrain_socket: bpy.types.NodeSocket,
    group_name: str = "TerrainPathDeformation",
) -> tuple[bpy.types.NodeSocket, list[Node]]:
    deformation_group = bpy.data.node_groups.get(group_name)
    if deformation_group is None or not group_has_io(
        deformation_group,
        ins=[
            "Terrain",
            "Path Geometry",
            "Width",
            "Falloff",
            "Sample Count",
            "Ray Length",
            "Strength",
            "Vertical Offset",
        ],
        outs=["Geometry"],
    ):
        deformation_group = create_path_deformation_group(group_name)

    created_nodes: list[Node] = []
    current_geometry = terrain_socket

    for path_def in mask_def.paths:
        settings = _merge_path_settings(mask_def.path_settings, path_def.path_settings)
        deformation = settings.deformation_settings
        if not deformation.enabled:
            continue

        path_geometry, source_nodes = _add_path_source_nodes(nt, path_def)
        created_nodes.extend(source_nodes)

        node = nt.nodes.new("GeometryNodeGroup")
        node.node_tree = deformation_group
        node.label = f"Deform Terrain: {_path_source_label(path_def)}"

        nt.links.new(current_geometry, node.inputs["Terrain"])
        nt.links.new(path_geometry, node.inputs["Path Geometry"])
        node.inputs["Width"].default_value = float(
            _effective_value(deformation.width, settings.width)
        )
        node.inputs["Falloff"].default_value = float(
            _effective_value(deformation.falloff, settings.falloff)
        )
        node.inputs["Sample Count"].default_value = int(
            _effective_value(deformation.sample_count, settings.sample_count)
        )
        node.inputs["Ray Length"].default_value = float(
            _effective_value(deformation.ray_length, settings.ray_length)
        )
        node.inputs["Strength"].default_value = float(deformation.strength)
        node.inputs["Vertical Offset"].default_value = float(
            deformation.vertical_offset
        )
        created_nodes.append(node)
        current_geometry = node.outputs["Geometry"]

    return current_geometry, created_nodes


def create_path_deformation(config: "TerrainConfig"):
    obj = get_terrain_object(config.object_name)
    mod_name = config.path_deformation_modifier_name

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

    prev_geo = gin.outputs["Geometry"]
    frames = []

    for layer in sort_layers_by_priority(config.layers):
        if not isinstance(layer.mask, RoadNetworkMask):
            continue
        if not has_path_deformation(layer.mask):
            continue

        prev_geo, deformation_nodes = add_road_network_path_deformation(
            ng,
            layer.mask,
            terrain_socket=prev_geo,
        )
        if deformation_nodes:
            frames.append(
                frame_nodes(ng, f"Path Deformation: {layer.name}", deformation_nodes)
            )

    if frames:
        frame_nodes(ng, "Path Deformation", frames)

    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
