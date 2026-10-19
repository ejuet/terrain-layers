from __future__ import annotations

import bpy
from terrain_layers.utility.geo_nodes import (
    get_terrain_object,
    remove_node_group,
    ensure_geo_nodes_modifier,
)
from terrain_layers.utility.rearrange import arrange_nodes
from terrain_layers.utility.nodes import (
    gn_clamp_0_1,
    gn_math_multiply,
    gn_value_float,
)
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.type_helpers import Node
from terrain_layers.masks.mask_types.type_helpers import MaskSocket
from terrain_layers.masks.mask_types.height import add_height_mask_node, HeightMask
from terrain_layers.masks.mask_types.slope import SlopeMask, add_slope_mask_node
from terrain_layers.masks.mask_types.paint import PaintMask, add_paint_mask_node
from terrain_layers.masks.mask_types.path import (
    RoadNetworkMask,
    add_road_network_mask_node,
)
from terrain_layers.masks.mask_types.scatter_footprint import (
    ScatterFootprintMask,
    add_scatter_footprint_mask_node,
)
from terrain_layers.masks.noise import (
    DualNoiseConfig,
    MaskNoiseConfig,
    create_dual_noise_cache,
    add_apply_mask_noise_from_attribute,
)
from terrain_layers.masks.priority_resolving import add_priority_resolve_node

from terrain_layers.config.config_types import Layer, TerrainConfig
from terrain_layers.config.helpers import sort_layers_by_priority, validate_terrain_config
from terrain_layers.biomes.create_scatter_biomes import (
    add_scatter_payload_and_join,
    add_scatter_point_distribution,
    tunnel_interior_materials,
    validate_scatter_collections,
)

"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""


def no_mask(nt) -> tuple[MaskSocket, list[Node]]:
    """Default raw mask active everywhere."""
    outp = gn_value_float(nt, 1.0, label="RawMask:Full")
    node_of_outp = outp.node
    return outp, [node_of_outp]


def add_raw_layer_mask(
    ng: bpy.types.NodeTree,
    *,
    layer: Layer,
    obj: bpy.types.Object,
    terrain_socket: bpy.types.NodeSocket,
    dual_to_attr: dict[DualNoiseConfig, str],
) -> tuple[MaskSocket, list[Node]]:
    """Build a static layer mask before it participates in priority resolution."""
    if isinstance(layer.mask, HeightMask):
        mask, nodes = add_height_mask_node(ng, layer.mask)
    elif isinstance(layer.mask, SlopeMask):
        mask, nodes = add_slope_mask_node(ng, layer.mask)
    elif isinstance(layer.mask, PaintMask):
        mask, nodes = add_paint_mask_node(ng, layer.mask, obj=obj)
    elif isinstance(layer.mask, RoadNetworkMask):
        mask, nodes = add_road_network_mask_node(
            ng,
            layer.mask,
            terrain_socket=terrain_socket,
        )
    elif isinstance(layer.mask, ScatterFootprintMask):
        raise ValueError("Scatter footprint masks require generated scatter points.")
    else:
        mask, nodes = no_mask(ng)

    if layer.mask_noise is not None:
        attr = dual_to_attr[layer.mask_noise.dual]
        mask, noise_nodes = add_apply_mask_noise_from_attribute(
            ng,
            base_mask=mask,
            noise=layer.mask_noise,
            attr_name=attr,
        )
        nodes.extend(noise_nodes)
    return mask, nodes


def add_provisional_eligibility_mask(
    ng: bpy.types.NodeTree,
    *,
    layer: Layer,
    raw_mask: MaskSocket,
    remaining: MaskSocket,
) -> tuple[MaskSocket, list[Node]]:
    """Evaluate an eligibility layer against area claimed by higher priorities."""
    strength = gn_value_float(
        ng, layer.strength, label=f"EligibilityStrength:{layer.name}"
    )
    weighted = gn_math_multiply(
        ng, raw_mask, strength, label=f"EligibilityWeighted:{layer.name}"
    )
    clamped = gn_clamp_0_1(ng, weighted, label=f"EligibilityClamp:{layer.name}")
    eligible = gn_math_multiply(
        ng, clamped, remaining, label=f"Eligibility:{layer.name}"
    )
    frame = frame_nodes(
        ng,
        f"Provisional Eligibility: {layer.name}",
        [strength.node, weighted.node, clamped.node, eligible.node],
    )
    return eligible, [frame] if frame is not None else []


def create_terrain_layers(config: TerrainConfig):
    validate_terrain_config(config)
    validate_scatter_collections(config.scatter_biomes)
    obj = get_terrain_object(config.object_name)

    if not config.layers:
        raise RuntimeError("Config has no layers.")

    mod_name = config.geometry_modifier_name
    layers_sorted = sort_layers_by_priority(config.layers)

    group_name = mod_name
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

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

    prev_geo = gin.outputs["Geometry"]

    # Remaining starts at 1.0
    remaining: MaskSocket = gn_value_float(ng, 1.0, label="Remaining:Start")

    # Create and cache dual noise attributes
    dual_to_attr, prev_geo = create_dual_noise_cache(
        [
            layer.mask_noise.dual if layer.mask_noise else None
            for layer in layers_sorted
        ],
        prev_geo,
        ng,
    )

    terrain_geo = prev_geo
    raw_masks: dict[str, MaskSocket] = {}
    raw_mask_nodes: dict[str, list[Node]] = {}
    for layer in layers_sorted:
        if isinstance(layer.mask, ScatterFootprintMask):
            continue
        raw_masks[layer.name], raw_mask_nodes[layer.name] = add_raw_layer_mask(
            ng,
            layer=layer,
            obj=obj,
            terrain_socket=terrain_geo,
            dual_to_attr=dual_to_attr,
        )

    resolved_layer_masks: dict[str, MaskSocket] = {}
    scatter_points: dict[str, bpy.types.NodeSocket] = {}
    scatter_biomes_by_id = {biome.id: biome for biome in config.scatter_biomes}
    layers_by_name = {layer.name: layer for layer in config.layers}
    interior_materials = tunnel_interior_materials()
    for layer in layers_sorted:
        if isinstance(layer.mask, ScatterFootprintMask):
            footprint = layer.mask
            biome = scatter_biomes_by_id[footprint.scatter_biome_id]
            layer_nodes = []
            if biome.id not in scatter_points:
                eligibility_layer = layers_by_name[biome.eligibility_layer_name]
                eligibility, eligibility_nodes = add_provisional_eligibility_mask(
                    ng,
                    layer=eligibility_layer,
                    raw_mask=raw_masks[eligibility_layer.name],
                    remaining=remaining,
                )
                points, _ = add_scatter_point_distribution(
                    ng,
                    biome=biome,
                    source_geo=terrain_geo,
                    eligibility_mask=eligibility,
                    interior_materials=interior_materials,
                )
                scatter_points[biome.id] = points
                # Keep the biome's spawn frame top-level. The Soil layer owns
                # only the footprint calculation that consumes those points.
                layer_nodes.extend(eligibility_nodes)
            mask, footprint_nodes = add_scatter_footprint_mask_node(
                ng,
                footprint,
                points=scatter_points[biome.id],
            )
            layer_nodes.extend(footprint_nodes)
        else:
            mask = raw_masks[layer.name]
            layer_nodes = list(raw_mask_nodes[layer.name])

        # Resolve priority via node group
        actual, remaining, node = add_priority_resolve_node(
            ng,
            raw_mask=mask,
            strength_value=layer.strength,
            remaining_socket=remaining,
        )
        layer_nodes.append(node)

        # Store resulting (priority-resolved) mask
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        layer_nodes.append(store)
        store.domain = "POINT"
        store.data_type = "FLOAT"
        store.inputs["Name"].default_value = layer.name

        links.new(prev_geo, store.inputs["Geometry"])
        links.new(actual, store.inputs["Value"])

        prev_geo = store.outputs["Geometry"]
        resolved_layer_masks[layer.name] = actual

        # Keep layer frames flat; the node links express cross-layer dependencies.
        frame_nodes(ng, layer.name, layer_nodes)

    # Footprint users already have priority-positioned point branches. All
    # other biomes keep the previous behavior and use final resolved masks.
    resolved_terrain_geo = prev_geo
    for biome in config.scatter_biomes:
        if biome.id not in scatter_points:
            points, _ = add_scatter_point_distribution(
                ng,
                biome=biome,
                source_geo=resolved_terrain_geo,
                eligibility_mask=resolved_layer_masks[biome.eligibility_layer_name],
                interior_materials=interior_materials,
            )
            scatter_points[biome.id] = points
        prev_geo, _ = add_scatter_payload_and_join(
            ng,
            biome=biome,
            points=scatter_points[biome.id],
            prev_geo=prev_geo,
        )

    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    # Migrate the default modifier created by versions that compiled scatter
    # separately.  It would otherwise duplicate instances after this breaking
    # configuration change.
    legacy_scatter = obj.modifiers.get("Terrain_Scatter_Biomes")
    if legacy_scatter is not None and legacy_scatter is not mod:
        obj.modifiers.remove(legacy_scatter)

    arrange_nodes(ng)
    return ng
