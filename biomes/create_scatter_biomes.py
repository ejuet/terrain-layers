from __future__ import annotations

import bpy

from config.config_types import TerrainConfig
from utility.frame_nodes import frame_nodes
from utility.geo_nodes import (
    active_mesh_object,
    ensure_geo_nodes_modifier,
    remove_node_group,
)
from utility.nodes import gn_math_multiply, gn_value_float
from utility.rearrange import arrange_nodes


def _safe_key(s: str) -> str:
    s = (s or "").strip()
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in s) or "Biome"


def _collect_collection_objects(
    collection: bpy.types.Collection,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    seen: set[str] = set()

    def visit(coll: bpy.types.Collection):
        for obj in coll.objects:
            if obj.name in seen:
                continue
            seen.add(obj.name)
            result.append(obj)
        for child in coll.children:
            visit(child)

    visit(collection)
    return result


def _set_object_info_as_instance(node: bpy.types.Node) -> None:
    as_instance_input = node.inputs.get("As Instance")
    if as_instance_input is not None:
        as_instance_input.default_value = True
        return
    if hasattr(node, "as_instance"):
        try:
            node.as_instance = True
        except Exception:
            pass


def create_scatter_biomes(config: TerrainConfig):
    obj = active_mesh_object()
    scatter_layers = [
        layer
        for layer in config.layers
        if getattr(layer, "scatter_biome", None) is not None
    ]
    if not scatter_layers:
        return None

    mod_name = config.scatter_modifier_name
    remove_node_group(mod_name)
    ng = bpy.data.node_groups.new(mod_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.items_tree.remove(it)

    ng.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    source_geo = gin.outputs["Geometry"]
    prev_geo = gin.outputs["Geometry"]

    frames = []

    for layer in scatter_layers:
        biome = layer.scatter_biome
        if biome is None:
            continue

        layer_nodes = []

        density = gn_value_float(
            ng, biome.density, label=f"Density:{_safe_key(layer.name)}"
        )
        density_node = density.node
        layer_nodes.append(density_node)

        attr = nodes.new("GeometryNodeInputNamedAttribute")
        attr.data_type = "FLOAT"
        attr.inputs["Name"].default_value = layer.name
        attr.label = f"Mask Attr: {layer.name}"
        layer_nodes.append(attr)

        clamp = nodes.new("ShaderNodeClamp")
        clamp.inputs["Min"].default_value = 0.0
        clamp.inputs["Max"].default_value = 1.0
        links.new(attr.outputs["Attribute"], clamp.inputs["Value"])
        layer_nodes.append(clamp)

        masked_density = gn_math_multiply(
            ng,
            clamp.outputs["Result"],
            density,
            label=f"MaskedDensity:{_safe_key(layer.name)}",
        )
        layer_nodes.append(masked_density.node)

        distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
        distribute.distribute_method = "RANDOM"
        distribute.inputs["Seed"].default_value = int(biome.seed)
        links.new(source_geo, distribute.inputs["Mesh"])
        links.new(masked_density, distribute.inputs["Density"])
        layer_nodes.append(distribute)

        instance = nodes.new("GeometryNodeInstanceOnPoints")
        links.new(distribute.outputs["Points"], instance.inputs["Points"])
        if "Rotation" in distribute.outputs and "Rotation" in instance.inputs:
            links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])
        layer_nodes.append(instance)

        collection = bpy.data.collections.get(biome.collection_name)
        if collection is None:
            raise RuntimeError(
                f"Scatter biome on layer '{layer.name}' references missing collection "
                f"'{biome.collection_name}'. Link or create that collection first."
            )
        collection_objects = _collect_collection_objects(collection)
        if not collection_objects:
            raise RuntimeError(
                f"Scatter biome on layer '{layer.name}' references empty collection "
                f"'{biome.collection_name}'. Add at least one object or child collection."
            )
        if len(collection_objects) == 1:
            object_info = nodes.new("GeometryNodeObjectInfo")
            object_info.transform_space = "ORIGINAL"
            _set_object_info_as_instance(object_info)
            object_info.inputs["Object"].default_value = collection_objects[0]
            links.new(object_info.outputs["Geometry"], instance.inputs["Instance"])
            layer_nodes.append(object_info)
        else:
            join_payload = nodes.new("GeometryNodeJoinGeometry")
            layer_nodes.append(join_payload)
            instance.inputs["Pick Instance"].default_value = True
            for scatter_object in collection_objects:
                object_info = nodes.new("GeometryNodeObjectInfo")
                object_info.transform_space = "ORIGINAL"
                _set_object_info_as_instance(object_info)
                object_info.inputs["Object"].default_value = scatter_object
                links.new(
                    object_info.outputs["Geometry"], join_payload.inputs["Geometry"]
                )
                layer_nodes.append(object_info)
            links.new(join_payload.outputs["Geometry"], instance.inputs["Instance"])

        if biome.scale_min == biome.scale_max:
            instance.inputs["Scale"].default_value = (
                biome.scale_min,
                biome.scale_min,
                biome.scale_min,
            )
        else:
            scale = nodes.new("FunctionNodeRandomValue")
            scale.data_type = "FLOAT"
            scale.inputs["Min"].default_value = float(biome.scale_min)
            scale.inputs["Max"].default_value = float(biome.scale_max)
            scale.inputs["Seed"].default_value = int(biome.seed)
            combine_scale = nodes.new("ShaderNodeCombineXYZ")
            links.new(scale.outputs["Value"], combine_scale.inputs["X"])
            links.new(scale.outputs["Value"], combine_scale.inputs["Y"])
            links.new(scale.outputs["Value"], combine_scale.inputs["Z"])
            links.new(combine_scale.outputs["Vector"], instance.inputs["Scale"])
            layer_nodes.extend([scale, combine_scale])

        join = nodes.new("GeometryNodeJoinGeometry")
        links.new(prev_geo, join.inputs["Geometry"])
        links.new(instance.outputs["Instances"], join.inputs["Geometry"])
        layer_nodes.append(join)

        prev_geo = join.outputs["Geometry"]
        frames.append(frame_nodes(ng, f"Scatter: {layer.name}", layer_nodes))

    frame_nodes(ng, "Scatter Biomes", frames)
    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng
