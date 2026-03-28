from __future__ import annotations

import bpy

from config.config_types import Layer, ScatterBiome, TerrainConfig
from utility.frame_nodes import frame_nodes
from utility.geo_nodes import (
    get_terrain_object,
    ensure_geo_nodes_modifier,
    remove_node_group,
    collect_collection_objects,
)
from utility.nodes import gn_math_multiply, gn_value_float
from utility.rearrange import arrange_nodes


def _safe_key(s: str) -> str:
    s = (s or "").strip()
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in s) or "Biome"


def _clear_group_interface(ng: bpy.types.NodeTree) -> None:
    """Remove all sockets from a node group's interface before rebuilding it."""
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)


def _set_object_info_as_instance(node: bpy.types.Node) -> None:
    """
    Configure an Object Info node to output an instance payload when Blender
    exposes that setting.

    Blender has exposed this toggle both as a property and as an input socket
    across versions, so the helper supports either form.
    """
    as_instance_input = node.inputs.get("As Instance")
    if as_instance_input is not None:
        as_instance_input.default_value = True
        return
    if hasattr(node, "as_instance"):
        try:
            node.as_instance = True
        except Exception:
            pass


def _scatter_payload_group_name(layer: Layer, biome: ScatterBiome) -> str:
    """Build a stable node-group name for the scatter objects used by one biome."""
    return (
        f"GN_ScatterObjects_{_safe_key(layer.name)}_{_safe_key(biome.collection_name)}"
    )


def create_scatter_payload_group(
    layer: Layer,
    biome: ScatterBiome,
) -> bpy.types.NodeTree:
    """
    Build the reusable object-source node group for one scatter biome.

    The group resolves the configured collection into Object Info nodes and
    outputs either a single instance or a join of several instances. For
    multi-object collections, the joined output remains an instance list so
    Instance on Points can pick one variant per point.
    """
    collection = bpy.data.collections.get(biome.collection_name)
    if collection is None:
        raise RuntimeError(
            f"Scatter biome on layer '{layer.name}' references missing collection "
            f"'{biome.collection_name}'. Link or create that collection first."
        )

    collection_objects = collect_collection_objects(collection)
    if not collection_objects:
        raise RuntimeError(
            f"Scatter biome on layer '{layer.name}' references empty collection "
            f"'{biome.collection_name}'. Add at least one object or child collection."
        )

    group_name = _scatter_payload_group_name(layer, biome)
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    _clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Instances", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gout = nodes.new("NodeGroupOutput")

    payload_nodes: list[bpy.types.Node] = []

    if len(collection_objects) == 1:
        object_info = nodes.new("GeometryNodeObjectInfo")
        object_info.transform_space = "ORIGINAL"
        _set_object_info_as_instance(object_info)
        object_info.inputs["Object"].default_value = collection_objects[0]
        links.new(object_info.outputs["Geometry"], gout.inputs["Instances"])
        payload_nodes.append(object_info)
    else:
        join_payload = nodes.new("GeometryNodeJoinGeometry")
        payload_nodes.append(join_payload)

        for scatter_object in collection_objects:
            object_info = nodes.new("GeometryNodeObjectInfo")
            object_info.transform_space = "ORIGINAL"
            _set_object_info_as_instance(object_info)
            object_info.inputs["Object"].default_value = scatter_object
            links.new(object_info.outputs["Geometry"], join_payload.inputs["Geometry"])
            payload_nodes.append(object_info)

        links.new(join_payload.outputs["Geometry"], gout.inputs["Instances"])

    frame_nodes(ng, f"Objects: {biome.collection_name}", payload_nodes)
    arrange_nodes(ng)
    return ng


def add_scatter_biome_nodes(
    ng: bpy.types.NodeTree,
    *,
    layer: Layer,
    biome: ScatterBiome,
    source_geo: bpy.types.NodeSocket,
    prev_geo: bpy.types.NodeSocket,
) -> tuple[bpy.types.NodeSocket, bpy.types.Node | None]:
    """
    Add the node chain that scatters one biome onto the terrain.

    The generated chain reads the baked layer mask, converts it into a point
    density, distributes points on the original terrain surface, instances a
    collection-backed payload, applies optional scale variation, and joins the
    result back onto the previous geometry stream.
    """
    nodes, links = ng.nodes, ng.links
    layer_frames: list[bpy.types.Node] = []

    density = gn_value_float(
        ng, biome.density, label=f"Density:{_safe_key(layer.name)}"
    )
    density_node = density.node

    attr = nodes.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT"
    attr.inputs["Name"].default_value = layer.name
    attr.label = f"Mask Attr: {layer.name}"

    clamp = nodes.new("ShaderNodeClamp")
    clamp.inputs["Min"].default_value = 0.0
    clamp.inputs["Max"].default_value = 1.0
    links.new(attr.outputs["Attribute"], clamp.inputs["Value"])

    masked_density = gn_math_multiply(
        ng,
        clamp.outputs["Result"],
        density,
        label=f"MaskedDensity:{_safe_key(layer.name)}",
    )
    layer_frames.append(
        frame_nodes(
            ng, "Mask & Density", [density_node, attr, clamp, masked_density.node]
        )
    )

    distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
    distribute.distribute_method = "RANDOM"
    distribute.inputs["Seed"].default_value = int(biome.seed)
    links.new(source_geo, distribute.inputs["Mesh"])
    links.new(masked_density, distribute.inputs["Density"])
    layer_frames.append(frame_nodes(ng, "Distribute Points", [distribute]))

    payload_group = nodes.new("GeometryNodeGroup")
    payload_group.node_tree = create_scatter_payload_group(layer, biome)
    payload_group.label = f"Objects: {biome.collection_name}"

    instance = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(distribute.outputs["Points"], instance.inputs["Points"])
    links.new(payload_group.outputs["Instances"], instance.inputs["Instance"])
    if "Rotation" in distribute.outputs and "Rotation" in instance.inputs:
        links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])

    collection = bpy.data.collections.get(biome.collection_name)
    if collection is None:
        raise RuntimeError(
            f"Scatter biome on layer '{layer.name}' references missing collection "
            f"'{biome.collection_name}'. Link or create that collection first."
        )
    collection_objects = collect_collection_objects(collection)
    if len(collection_objects) > 1:
        instance.inputs["Pick Instance"].default_value = True

    layer_frames.append(
        frame_nodes(ng, "Objects & Instancing", [payload_group, instance])
    )

    scale_nodes: list[bpy.types.Node] = []
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

        scale_nodes.extend([scale, combine_scale])
        layer_frames.append(frame_nodes(ng, "Scale Variation", scale_nodes))

    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(prev_geo, join.inputs["Geometry"])
    links.new(instance.outputs["Instances"], join.inputs["Geometry"])
    layer_frames.append(frame_nodes(ng, "Join Result", [join]))

    layer_frame = frame_nodes(
        ng,
        f"Scatter: {layer.name}",
        [n for n in layer_frames if n is not None],
    )
    return join.outputs["Geometry"], layer_frame


def create_scatter_biomes(config: TerrainConfig):
    """Create the Geometry Nodes modifier that scatters collection instances per layer."""
    obj = get_terrain_object(config.object_name)
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
    _clear_group_interface(ng)
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
    source_geo = gin.outputs["Geometry"]
    prev_geo = gin.outputs["Geometry"]

    biome_frames: list[bpy.types.Node] = []
    for layer in scatter_layers:
        biome = layer.scatter_biome
        if biome is None:
            continue
        prev_geo, biome_frame = add_scatter_biome_nodes(
            ng,
            layer=layer,
            biome=biome,
            source_geo=source_geo,
            prev_geo=prev_geo,
        )
        if biome_frame is not None:
            biome_frames.append(biome_frame)

    frame_nodes(ng, "Scatter Biomes", biome_frames)
    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng
