from __future__ import annotations

import bpy
from utility.geo_nodes import (
    active_mesh_object,
    remove_node_group,
    ensure_geo_nodes_modifier,
)
from utility.rearrange import arrange_nodes
from utility.nodes import (
    gn_value_float,
)
from utility.frame_nodes import frame_nodes
from masks.mask_types.type_helpers import MaskSocket, Node
from masks.mask_types.height import add_height_mask_node, HeightMask
from masks.mask_types.slope import SlopeMask, add_slope_mask_node
from masks.mask_types.paint import PaintMask, add_paint_mask_node
from masks.noise import (
    DualNoiseConfig,
    MaskNoiseConfig,
    create_dual_noise_cache,
    add_apply_mask_noise_from_attribute,
)
from masks.priority_resolving import add_priority_resolve_node

from config.config_types import Layer, TerrainConfig
from config.helpers import sort_layers_by_priority

"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""


def no_mask(nt) -> tuple[MaskSocket, list[Node]]:
    """Default raw mask active everywhere."""
    outp = gn_value_float(nt, 1.0, label="RawMask:Full")
    node_of_outp = outp.node
    return outp, [node_of_outp]


def create_terrain_layers(config: TerrainConfig):
    obj = active_mesh_object()

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

    frames = []
    for layer in layers_sorted:
        layer_nodes = []

        # Raw mask
        if isinstance(layer.mask, HeightMask):
            mask, new_nodes = add_height_mask_node(ng, layer.mask)
        elif isinstance(layer.mask, SlopeMask):
            mask, new_nodes = add_slope_mask_node(ng, layer.mask)
        elif isinstance(layer.mask, PaintMask):
            mask, new_nodes = add_paint_mask_node(ng, layer.mask, obj=obj)
        else:
            mask, new_nodes = no_mask(ng)
        layer_nodes.extend(new_nodes)

        # Optional mask noise: pick attribute based on layer.mask_noise.dual
        if layer.mask_noise is not None:
            attr = dual_to_attr[layer.mask_noise.dual]
            mask, noise_nodes = add_apply_mask_noise_from_attribute(
                ng,
                base_mask=mask,
                noise=layer.mask_noise,
                attr_name=attr,
            )
            layer_nodes.extend(noise_nodes)

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

        # Frame the layer nodes
        frame = frame_nodes(ng, f"Layer: {layer.name}", layer_nodes)
        frames.append(frame)

    frame_nodes(ng, "Terrain Layers", frames)

    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng


def run():
    # Two dual noise configs: default and an alternate for "Rock"
    dual_default = DualNoiseConfig(
        scale=6.0, large_scale=1.5, large_mix=0.35, detail=1.0
    )
    dual_alt = DualNoiseConfig(scale=10.0, large_scale=2.2, large_mix=0.55, detail=0.8)

    config = TerrainConfig(
        geometry_modifier_name="Terrain_Layer_Masks",
        layers=[
            Layer(name="Underwater", priority=0, strength=1.0),
            Layer(
                name="Beach",
                priority=10,
                strength=1.0,
                mask=HeightMask(
                    min_height=1.5,
                    max_height=7.5,
                    ramp_low=0.35,
                    ramp_high=0.55,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,
                    amount=2.0,
                    sharpness=1.6,
                    bias=0.0,
                    zone_width=0.35,
                    zone_softness=1.0,
                ),
            ),
            Layer(
                name="Sand Painted",
                priority=20,
                strength=1.0,
                mask=PaintMask(
                    image_name="IMG_Terrain_SandPaint",
                    uv_map_name="UV_TerrainPaint",
                    width=2048,
                    height=2048,
                    alpha=True,
                    ramp_low=0.0,
                    ramp_high=1.0,
                    interpolation="Linear",
                    extension="CLIP",
                ),
            ),
            Layer(
                name="Grass",
                priority=20,
                strength=1.0,
                mask=HeightMask(
                    min_height=3.5,
                    max_height=8.0,
                    ramp_low=0.45,
                    ramp_high=0.65,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,  # reuses the same stored dual noise as Beach
                    amount=1.8,
                    sharpness=1.8,
                    bias=0.0,
                    zone_width=0.5,
                    zone_softness=1.0,
                ),
            ),
            Layer(
                name="Rock",
                priority=25,
                strength=1.0,
                mask=SlopeMask(
                    min_angle=25.0,
                    max_angle=60.0,
                    ramp_low=0.4,
                    ramp_high=0.6,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_alt,  # different dual noise => second stored attribute
                    amount=2.2,
                    sharpness=2.0,
                    bias=0.0,
                    zone_width=0.4,
                    zone_softness=1.0,
                ),
            ),
            Layer(
                name="Snow",
                priority=30,
                strength=1.0,
                mask=HeightMask(
                    min_height=9.0,
                    max_height=15.0,
                    ramp_low=0.45,
                    ramp_high=0.65,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,  # reuses default dual noise
                    amount=1.2,
                    sharpness=2.2,
                    bias=0.0,
                    zone_width=0.3,
                    zone_softness=1.2,
                ),
            ),
        ],
    )

    create_terrain_layers(config)
