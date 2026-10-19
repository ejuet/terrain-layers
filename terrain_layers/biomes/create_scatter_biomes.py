from __future__ import annotations

import bpy

from terrain_layers.config.config_types import ScatterBiome
from terrain_layers.masks.mask_types.type_helpers import MaskSocket
from terrain_layers.tunnels.tunnel_types import TUNNEL_INTERIOR_MATERIAL_MARKER
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import collect_collection_objects
from terrain_layers.utility.nodes import gn_math_multiply, gn_value_float
from terrain_layers.utility.object_info_group import create_object_info_group


def _safe_key(value: str) -> str:
    value = (value or "").strip()
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in value) or "Biome"


def _payload_group_name(biome: ScatterBiome) -> str:
    return f"GN_ScatterObjects_{_safe_key(biome.id)}_{_safe_key(biome.collection_name)}"


def create_scatter_payload_group(biome: ScatterBiome) -> bpy.types.NodeTree:
    """Build the reusable object-source group for one standalone biome."""
    collection = bpy.data.collections.get(biome.collection_name)
    if collection is None:
        raise RuntimeError(
            f"Scatter biome '{biome.id}' references missing collection "
            f"'{biome.collection_name}'. Link or create that collection first."
        )
    objects = collect_collection_objects(collection)
    if not objects:
        raise RuntimeError(
            f"Scatter biome '{biome.id}' references empty collection "
            f"'{biome.collection_name}'. Add at least one object or child collection."
        )
    return create_object_info_group(
        group_name=_payload_group_name(biome),
        objects=objects,
        transform_space="ORIGINAL",
        as_instance=True,
        output_name="Instances",
        frame_label=f"Objects: {biome.collection_name}",
    )


def validate_scatter_collections(biomes: list[ScatterBiome]) -> None:
    """Fail before graph construction when a configured payload is unavailable."""
    for biome in biomes:
        collection = bpy.data.collections.get(biome.collection_name)
        if collection is None:
            raise RuntimeError(
                f"Scatter biome '{biome.id}' references missing collection "
                f"'{biome.collection_name}'. Link or create that collection first."
            )
        if not collect_collection_objects(collection):
            raise RuntimeError(
                f"Scatter biome '{biome.id}' references empty collection "
                f"'{biome.collection_name}'. Add at least one object or child collection."
            )


def tunnel_interior_materials() -> list[bpy.types.Material]:
    return [
        material
        for material in bpy.data.materials
        if material.get(TUNNEL_INTERIOR_MATERIAL_MARKER, False)
    ]


def _add_exterior_surface_selection(ng, interior_materials):
    """Build a face selection which excludes tunnel/cave interior materials."""
    if not interior_materials:
        return None, []
    nodes, links = ng.nodes, ng.links
    selections, created = [], []
    for material in interior_materials:
        selection = nodes.new("GeometryNodeMaterialSelection")
        selection.label = f"Tunnel Interior: {material.name}"
        selection.inputs["Material"].default_value = material
        selections.append(selection.outputs["Selection"])
        created.append(selection)
    interior = selections[0]
    for selection in selections[1:]:
        either = nodes.new("FunctionNodeBooleanMath")
        either.operation = "OR"
        links.new(interior, either.inputs[0])
        links.new(selection, either.inputs[1])
        interior = either.outputs["Boolean"]
        created.append(either)
    exterior = nodes.new("FunctionNodeBooleanMath")
    exterior.operation = "NOT"
    links.new(interior, exterior.inputs[0])
    created.append(exterior)
    return exterior.outputs["Boolean"], created


def add_scatter_point_distribution(
    ng: bpy.types.NodeTree,
    *,
    biome: ScatterBiome,
    source_geo: bpy.types.NodeSocket,
    eligibility_mask: MaskSocket,
    interior_materials: list[bpy.types.Material],
) -> tuple[bpy.types.NodeSocket, bpy.types.Node]:
    """Return a biome's point cloud, deliberately separate from instancing.

    A future footprint layer can consume this point branch at its own priority
    position without changing the payload-instancing graph.
    """
    nodes, links = ng.nodes, ng.links
    key = _safe_key(biome.id)
    density = gn_value_float(ng, biome.density, label=f"Density:{key}")
    clamp = nodes.new("ShaderNodeClamp")
    clamp.inputs["Min"].default_value = 0.0
    clamp.inputs["Max"].default_value = 1.0
    links.new(eligibility_mask, clamp.inputs["Value"])
    masked_density = gn_math_multiply(
        ng, clamp.outputs["Result"], density, label=f"MaskedDensity:{key}"
    )
    distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
    distribute.distribute_method = "RANDOM"
    distribute.inputs["Seed"].default_value = int(biome.seed)
    links.new(source_geo, distribute.inputs["Mesh"])
    links.new(masked_density, distribute.inputs["Density"])
    exterior, selection_nodes = _add_exterior_surface_selection(ng, interior_materials)
    if exterior is not None:
        links.new(exterior, distribute.inputs["Selection"])
    return distribute.outputs["Points"], frame_nodes(
        ng,
        f"{biome.id} Spawn Point Distribution",
        [density.node, clamp, masked_density.node, distribute, *selection_nodes],
    )


def add_scatter_payload_and_join(
    ng: bpy.types.NodeTree,
    *,
    biome: ScatterBiome,
    points: bpy.types.NodeSocket,
    prev_geo: bpy.types.NodeSocket,
) -> tuple[bpy.types.NodeSocket, bpy.types.Node]:
    """Instance a biome payload onto its points and join it with terrain."""
    nodes, links = ng.nodes, ng.links
    payload = nodes.new("GeometryNodeGroup")
    payload.node_tree = create_scatter_payload_group(biome)
    payload.label = f"Objects: {biome.collection_name}"
    instance = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(points, instance.inputs["Points"])
    links.new(payload.outputs["Instances"], instance.inputs["Instance"])
    distribute = points.node
    if not biome.keep_upright and "Rotation" in distribute.outputs and "Rotation" in instance.inputs:
        links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])
    collection = bpy.data.collections.get(biome.collection_name)
    if collection is not None and len(collect_collection_objects(collection)) > 1:
        instance.inputs["Pick Instance"].default_value = True
    scale_nodes = []
    if biome.scale_min == biome.scale_max:
        instance.inputs["Scale"].default_value = (biome.scale_min,) * 3
    else:
        scale = nodes.new("FunctionNodeRandomValue")
        scale.data_type = "FLOAT"
        scale.inputs["Min"].default_value = float(biome.scale_min)
        scale.inputs["Max"].default_value = float(biome.scale_max)
        scale.inputs["Seed"].default_value = int(biome.seed)
        combine = nodes.new("ShaderNodeCombineXYZ")
        for axis in ("X", "Y", "Z"):
            links.new(scale.outputs["Value"], combine.inputs[axis])
        links.new(combine.outputs["Vector"], instance.inputs["Scale"])
        scale_nodes = [scale, combine]
    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(prev_geo, join.inputs["Geometry"])
    links.new(instance.outputs["Instances"], join.inputs["Geometry"])
    return join.outputs["Geometry"], frame_nodes(
        ng,
        f"{biome.id} Scatter Objects",
        [payload, instance, *scale_nodes, join],
    )
