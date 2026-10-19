from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from terrain_layers.shader.material_types import PBRMaterialSource
from terrain_layers.tunnels.create_tunnel_path_cutter import (
    create_tunnel_path_cutter_group,
)
from terrain_layers.tunnels.mineshaft_entries import (
    clear_mineshaft_entries,
    create_mineshaft_entry_objects,
)
from terrain_layers.tunnels.resolved_tunnel_config import (
    ResolvedCave,
    ResolvedPath,
    resolve_tunnel_system,
)
from terrain_layers.tunnels.solidify import (
    get_temporary_solidify_material,
    remove_temporary_solidify_geometry,
    solidify_terrain,
)
from terrain_layers.tunnels.tunnel_types import (
    MineShaftEntry,
    TunnelShape,
    TUNNEL_INTERIOR_MATERIAL_MARKER,
)
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    ensure_geo_nodes_modifier,
    get_terrain_object,
    remove_node_group,
)
from terrain_layers.utility.object_info_group import add_object_info_nodes
from terrain_layers.utility.rearrange import arrange_nodes

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


_PREVIOUS_SYSTEM_MODIFIER_NAME = "Terrain_Tunnel_Entrypoints"


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


def _configure_boolean(
    node: bpy.types.Node,
    operation: str,
    *,
    self_intersection: bool = True,
    solver: str = "EXACT",
    hole_tolerant: bool = False,
) -> None:
    try:
        node.operation = operation
    except Exception:
        pass
    try:
        node.solver = solver
    except Exception:
        pass
    if hasattr(node, "self_intersection"):
        try:
            node.self_intersection = self_intersection
        except Exception:
            pass
    hole_tolerant_input = node.inputs.get("Hole Tolerant")
    if hole_tolerant_input is not None:
        hole_tolerant_input.default_value = hole_tolerant


def _path_batches(paths: list[ResolvedPath]) -> list[list[ResolvedPath]]:
    batches: list[list[ResolvedPath]] = []
    for path in paths:
        if batches and batches[-1][0].batch_key == path.batch_key:
            batches[-1].append(path)
        else:
            batches.append([path])
    return batches


def create_tunnel_system_modifier(config: "TerrainConfig"):
    if config.tunnel_system is None:
        return None
    paths, caves = resolve_tunnel_system(config)
    if not paths and not caves:
        return None
    obj = get_terrain_object(config.object_name)
    for cave in caves:
        cave.object.hide_render = True
        cave.object.hide_set(True)

    mod_name = config.tunnel_system_modifier_name
    # The old generated modifier must not remain active alongside the renamed
    # system modifier when a scene is rebuilt after upgrading this package.
    if mod_name != _PREVIOUS_SYSTEM_MODIFIER_NAME:
        previous_system_modifier = obj.modifiers.get(_PREVIOUS_SYSTEM_MODIFIER_NAME)
        if previous_system_modifier is not None:
            obj.modifiers.remove(previous_system_modifier)
        remove_node_group(_PREVIOUS_SYSTEM_MODIFIER_NAME)
    previous_modifier = obj.modifiers.get(mod_name)
    if previous_modifier is not None:
        previous_modifier.show_viewport = False
        bpy.context.view_layer.update()
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

    # Import lazily to avoid a configuration <-> tunnel module import cycle.
    from terrain_layers.shader.create_shader import create_ground_material_shader

    material_cache: dict[tuple[PBRMaterialSource, float], bpy.types.Material] = {}

    def material_for(
        material: PBRMaterialSource, texture_scale: float
    ) -> bpy.types.Material:
        key = (material, texture_scale)
        if key not in material_cache:
            material_cache[key] = create_ground_material_shader(
                material,
                f"{config.shader_name}_Tunnel_{len(material_cache) + 1}",
                texture_scale,
            )
            material_cache[key][TUNNEL_INTERIOR_MATERIAL_MARKER] = True
        return material_cache[key]

    child_frames: list[bpy.types.Node] = []
    temporary_solidify_material = get_temporary_solidify_material()
    cut_geometry, solidify_nodes = solidify_terrain(
        ng,
        gin.outputs["Geometry"],
        config.tunnel_system.solidify_depth,
        temporary_solidify_material,
    )
    solidify_frame = frame_nodes(ng, "Solidify Terrain", solidify_nodes)
    if solidify_frame:
        child_frames.append(solidify_frame)
    cutters: list[bpy.types.NodeSocket] = []
    for batch in _path_batches(paths):
        first = batch[0]
        path_geometry, source_nodes = add_object_info_nodes(
            ng,
            objects=[path.object for path in batch],
            transform_space="RELATIVE",
            as_instance=False,
        )
        cutter_group = create_tunnel_path_cutter_group(
            group_name=f"TerrainTunnelPathCutter_{len(child_frames) + 1}",
            shape=first.shape,
            keep_floor_level=first.keep_floor_level,
        )
        portal_cutter = nodes.new("GeometryNodeGroup")
        portal_cutter.node_tree = cutter_group
        portal_cutter.label = "Tunnel Path Cutter"
        links.new(path_geometry, portal_cutter.inputs["Path Geometry"])
        dimensions = (
            {"Radius": first.radius}
            if first.shape == TunnelShape.CIRCLE
            else {"Width": first.width, "Height": first.height}
        )
        batch_nodes = [*source_nodes]
        for name, size in dimensions.items():
            value, clearance = nodes.new("ShaderNodeValue"), nodes.new("ShaderNodeMath")
            value.label, value.outputs[0].default_value = f"Tunnel {name}", size
            clearance.operation, clearance.inputs[1].default_value = "MULTIPLY", 1.02
            links.new(value.outputs[0], clearance.inputs[0])
            links.new(clearance.outputs["Value"], portal_cutter.inputs[name])
            batch_nodes.extend((value, clearance))
        material_cutter = nodes.new("GeometryNodeSetMaterial")
        material_cutter.label = (
            f"Tunnel Material: {first.ground_material.display_name}"
        )
        material_cutter.inputs["Material"].default_value = material_for(
            first.ground_material, first.texture_scale
        )
        links.new(
            portal_cutter.outputs["Cutter Mesh"], material_cutter.inputs["Geometry"]
        )
        smooth = nodes.new("GeometryNodeSetShadeSmooth")
        smooth.label, smooth.inputs["Shade Smooth"].default_value = (
            "Smooth Tunnel Cut",
            True,
        )
        links.new(material_cutter.outputs["Geometry"], smooth.inputs["Mesh"])
        cutters.append(smooth.outputs["Mesh"])
        names = " + ".join(path.object.name for path in batch)
        frame = frame_nodes(
            ng,
            ("Path: " if len(batch) == 1 else "Paths: ") + names,
            [*batch_nodes, portal_cutter, material_cutter, smooth],
        )
        if frame:
            child_frames.append(frame)

    # A named group is cut at its first declaration, preserving the declared
    # order relative to independent caves without duplicating group work.
    cave_units: list[tuple[str | None, list[ResolvedCave]]] = []
    grouped: set[str] = set()
    for cave in caves:
        if cave.fuse_group is None:
            cave_units.append((None, [cave]))
        elif cave.fuse_group not in grouped:
            grouped.add(cave.fuse_group)
            cave_units.append(
                (
                    cave.fuse_group,
                    [item for item in caves if item.fuse_group == cave.fuse_group],
                )
            )
    for group_name, unit in cave_units:
        geometry, source_nodes = add_object_info_nodes(
            ng,
            objects=[cave.object for cave in unit],
            transform_space="RELATIVE",
            as_instance=False,
            join_multiple=not (group_name is not None and len(unit) > 1),
        )
        unit_nodes = [*source_nodes]
        if group_name is not None and len(unit) > 1:
            union = nodes.new("GeometryNodeMeshBoolean")
            union.label = "Fuse Overlapping Caves"
            _configure_boolean(union, "UNION", self_intersection=False)
            for source in source_nodes:
                if source.bl_idname == "GeometryNodeObjectInfo":
                    links.new(source.outputs["Geometry"], union.inputs[1])
            geometry = union.outputs["Mesh"]
            unit_nodes.append(union)
        material = nodes.new("GeometryNodeSetMaterial")
        material.label = f"Cave Material: {unit[0].ground_material.display_name}"
        material.inputs["Material"].default_value = material_for(
            unit[0].ground_material, unit[0].texture_scale
        )
        links.new(geometry, material.inputs["Geometry"])
        flat = nodes.new("GeometryNodeSetShadeSmooth")
        flat.label, flat.inputs["Shade Smooth"].default_value = (
            "Keep Cave Faces Flat",
            False,
        )
        links.new(material.outputs["Geometry"], flat.inputs["Mesh"])
        cutters.append(flat.outputs["Mesh"])
        label = (
            f"Caves: {group_name}"
            if group_name is not None
            else f"Cave: {unit[0].object.name}"
        )
        frame = frame_nodes(ng, label, [*unit_nodes, material, flat])
        if frame:
            child_frames.append(frame)

    # Keep Mesh 1 closed until every cutter is applied. A tunnel that exits
    # the terrain otherwise makes every later boolean much more expensive.
    final_boolean = nodes.new("GeometryNodeMeshBoolean")
    final_boolean.label = "Cut Tunnel System"
    _configure_boolean(
        final_boolean,
        "DIFFERENCE",
        self_intersection=False,
        solver="FLOAT",
    )
    links.new(cut_geometry, final_boolean.inputs["Mesh 1"])
    for cutter in cutters:
        links.new(cutter, final_boolean.inputs["Mesh 2"])
    cut_geometry = final_boolean.outputs["Mesh"]
    final_frame = frame_nodes(ng, "Cut Tunnel System", [final_boolean])
    if final_frame:
        child_frames.append(final_frame)

    if any(isinstance(path.entry_decoration, MineShaftEntry) for path in paths):
        entry_collection = clear_mineshaft_entries()
        for path in paths:
            if isinstance(path.entry_decoration, MineShaftEntry):
                create_mineshaft_entry_objects(
                    obj,
                    path.object,
                    path.width,
                    path.height,
                    path.entry_decoration,
                    entry_collection,
                )
    cut_geometry, cleanup_nodes = remove_temporary_solidify_geometry(
        ng,
        cut_geometry,
        temporary_solidify_material,
    )
    cleanup_frame = frame_nodes(ng, "Remove Temporary Solidify", cleanup_nodes)
    if cleanup_frame:
        child_frames.append(cleanup_frame)
    links.new(cut_geometry, gout.inputs["Geometry"])
    frame_nodes(ng, "Tunnel System", child_frames)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    mod.show_viewport = True
    mod.show_render = True
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
