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
    gn_math_multiply,
    gn_math_subtract,
    gn_clamp_0_1,
)
from utility.frame_nodes import frame_nodes
from masks.mask_types import Mask
from masks.mask_types.type_helpers import MaskSocket, Node
from masks.mask_types.height import add_height_mask_node, HeightMask
from masks.mask_types.slope import SlopeMask, add_slope_mask_node
from masks.mask_types.paint import PaintMask, add_paint_mask_node

from dataclasses import dataclass, field
from typing import Any

"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""


@dataclass(frozen=True, slots=True)
class Layer:
    name: str
    priority: int = 0
    strength: float = 1.0
    mask: Mask | None = None


@dataclass(frozen=True, slots=True)
class TerrainConfig:
    geometry_modifier_name: str = "Terrain_Layer_Masks"
    layers: list[Layer] = field(default_factory=list)


def sort_layers_by_priority(layers: list[Layer]) -> list[Layer]:
    """
    Returns layers sorted by priority DESC (higher priority first).
    Stable for equal priorities: earlier items in the config win ties.
    """
    indexed = list(enumerate(layers))

    def key(item: tuple[int, Layer]) -> tuple[int, int]:
        idx, layer = item
        # sort by prio DESC, then idx ASC (stable tiebreak)
        return (-int(layer.priority), idx)

    indexed.sort(key=key)
    return [layer for _, layer in indexed]


def no_mask(nt) -> tuple[MaskSocket, list[Node]]:
    """Default raw mask active everywhere."""
    outp = gn_value_float(nt, 1.0, label="RawMask:Full")
    node_of_outp = outp.node
    return outp, [node_of_outp]


def create_priority_resolve_group(group_name: str = "TerrainPriorityResolve"):
    """Creates a node group that resolves priority masks."""
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Raw Mask", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Strength", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Remaining", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Actual Mask", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Remaining Out", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )

    gin, gout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")

    # weighted = clamp(raw * strength)
    w = gn_clamp_0_1(
        ng,
        gn_math_multiply(
            ng, gin.outputs["Raw Mask"], gin.outputs["Strength"], label="R*S"
        ),
    )

    # actual = w * remaining
    a = gn_math_multiply(ng, w, gin.outputs["Remaining"], label="A=w*R")

    # remaining_out = clamp(remaining - actual)
    r = gn_math_subtract(ng, gin.outputs["Remaining"], a, clamp=True, label="R-A")

    ng.links.new(a, gout.inputs["Actual Mask"])
    ng.links.new(r, gout.inputs["Remaining Out"])
    return ng


def add_priority_resolve_node(
    nt,
    *,
    raw_mask: MaskSocket,
    strength_value: float,
    remaining_socket: MaskSocket,
    group_name: str = "TerrainPriorityResolve",
) -> tuple[MaskSocket, MaskSocket, Node]:
    resolve_group = bpy.data.node_groups.get(
        group_name
    ) or create_priority_resolve_group(group_name)
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = resolve_group

    nt.links.new(raw_mask, node.inputs["Raw Mask"])
    node.inputs["Strength"].default_value = float(strength_value)
    nt.links.new(remaining_socket, node.inputs["Remaining"])

    return node.outputs["Actual Mask"], node.outputs["Remaining Out"], node


# ============================================================
# Main builder
# ============================================================


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
        frame_nodes(ng, f"Layer: {layer.name}", layer_nodes)

    links.new(prev_geo, gout.inputs["Geometry"])

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    arrange_nodes(ng)
    return ng


def run():
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
            ),
        ],
    )

    create_terrain_layers(config)
