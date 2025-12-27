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


from dataclasses import dataclass, field
from typing import Literal, TypeAlias, Union

"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""

# Semantic alias for “this socket is a 0..1 mask”
MaskSocket: TypeAlias = bpy.types.NodeSocket


@dataclass(frozen=True, slots=True)
class HeightMask:
    type: Literal["height"] = "height"
    min_height: float = 0.0
    max_height: float = 10.0
    ramp_low: float = 0.4
    ramp_high: float = 0.6


@dataclass(frozen=True, slots=True)
class SlopeMask:
    type: Literal["slope"] = "slope"
    min_angle: float = 25.0
    max_angle: float = 60.0
    ramp_low: float = 0.4
    ramp_high: float = 0.6


Mask = Union[HeightMask, SlopeMask]


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


# ============================================================
# Mask groups
# ============================================================


def create_height_mask_group(group_name: str = "TerrainHeightMask"):
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Position", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(
        name="Min Height", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Max Height", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp Low", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp High", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(name="Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    sep = nodes.new("ShaderNodeSeparateXYZ")
    mapr = nodes.new("ShaderNodeMapRange")
    mapr.clamp = True
    mapr.inputs["To Min"].default_value = 0.0
    mapr.inputs["To Max"].default_value = 1.0

    sub_low = nodes.new("ShaderNodeMath")
    sub_low.operation = "SUBTRACT"

    sub_high = nodes.new("ShaderNodeMath")
    sub_high.operation = "SUBTRACT"

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.use_clamp = True

    clamp = nodes.new("ShaderNodeClamp")

    links.new(gin.outputs["Position"], sep.inputs["Vector"])
    links.new(sep.outputs["Z"], mapr.inputs["Value"])
    links.new(gin.outputs["Min Height"], mapr.inputs["From Min"])
    links.new(gin.outputs["Max Height"], mapr.inputs["From Max"])

    links.new(mapr.outputs["Result"], sub_low.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_low.inputs[1])

    links.new(gin.outputs["Ramp High"], sub_high.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_high.inputs[1])

    links.new(sub_low.outputs["Value"], div.inputs[0])
    links.new(sub_high.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], clamp.inputs["Value"])
    links.new(clamp.outputs["Result"], gout.inputs["Mask"])

    return ng


def add_height_mask_node(
    nt, mask_def: HeightMask, *, group_name: str = "TerrainHeightMask"
) -> MaskSocket:
    mask_group = bpy.data.node_groups.get(group_name) or create_height_mask_group(
        group_name
    )
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group

    pos_node = nt.nodes.new("GeometryNodeInputPosition")
    nt.links.new(pos_node.outputs["Position"], node.inputs["Position"])

    node.inputs["Min Height"].default_value = float(mask_def.min_height)
    node.inputs["Max Height"].default_value = float(mask_def.max_height)
    node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    return node.outputs["Mask"]


def create_slope_mask_group(group_name: str = "TerrainSlopeMask"):
    """
    Produces a mask based on slope angle (degrees) from the geometry normal:
      0° = perfectly flat (facing +Z), 90° = vertical.
    Uses abs(dot(N, Up)) so both sides behave the same.
    Output is a 0..1 mask with optional ramp shaping similar to height mask.
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Normal", in_out="INPUT", socket_type="NodeSocketVector"
    )
    ng.interface.new_socket(
        name="Min Angle", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Max Angle", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp Low", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        name="Ramp High", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(name="Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    # Normalize normal
    nrm = nodes.new("ShaderNodeVectorMath")
    nrm.operation = "NORMALIZE"

    # dot(N, Up)
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.0, 0.0, 1.0)

    # abs(dot)
    abs_dot = nodes.new("ShaderNodeMath")
    abs_dot.operation = "ABSOLUTE"

    # acos(abs(dot)) -> radians
    acos = nodes.new("ShaderNodeMath")
    acos.operation = "ARCCOSINE"

    # radians to degrees
    to_deg = nodes.new("ShaderNodeMath")
    to_deg.operation = "MULTIPLY"
    to_deg.inputs[1].default_value = 57.29577951308232  # 180/pi

    # Map angle range to 0..1 (clamped)
    mapr = nodes.new("ShaderNodeMapRange")
    mapr.clamp = True
    mapr.inputs["To Min"].default_value = 0.0
    mapr.inputs["To Max"].default_value = 1.0

    # Ramp shaping like height mask
    sub_low = nodes.new("ShaderNodeMath")
    sub_low.operation = "SUBTRACT"

    sub_high = nodes.new("ShaderNodeMath")
    sub_high.operation = "SUBTRACT"

    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.use_clamp = True

    clamp = nodes.new("ShaderNodeClamp")

    # Wiring
    links.new(gin.outputs["Normal"], nrm.inputs[0])
    links.new(nrm.outputs["Vector"], dot.inputs[0])

    links.new(dot.outputs["Value"], abs_dot.inputs[0])
    links.new(abs_dot.outputs["Value"], acos.inputs[0])

    links.new(acos.outputs["Value"], to_deg.inputs[0])

    links.new(to_deg.outputs["Value"], mapr.inputs["Value"])
    links.new(gin.outputs["Min Angle"], mapr.inputs["From Min"])
    links.new(gin.outputs["Max Angle"], mapr.inputs["From Max"])

    links.new(mapr.outputs["Result"], sub_low.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_low.inputs[1])

    links.new(gin.outputs["Ramp High"], sub_high.inputs[0])
    links.new(gin.outputs["Ramp Low"], sub_high.inputs[1])

    links.new(sub_low.outputs["Value"], div.inputs[0])
    links.new(sub_high.outputs["Value"], div.inputs[1])

    links.new(div.outputs["Value"], clamp.inputs["Value"])
    links.new(clamp.outputs["Result"], gout.inputs["Mask"])

    return ng


def add_slope_mask_node(
    nt, mask_def: SlopeMask, *, group_name: str = "TerrainSlopeMask"
) -> MaskSocket:
    mask_group = bpy.data.node_groups.get(group_name) or create_slope_mask_group(
        group_name
    )
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group

    nrm_node = nt.nodes.new("GeometryNodeInputNormal")
    nt.links.new(nrm_node.outputs["Normal"], node.inputs["Normal"])

    node.inputs["Min Angle"].default_value = float(mask_def.min_angle)
    node.inputs["Max Angle"].default_value = float(mask_def.max_angle)
    node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    return node.outputs["Mask"]


def no_mask(nt) -> MaskSocket:
    """Default raw mask active everywhere."""
    return gn_value_float(nt, 1.0, label="RawMask:Full")


def create_priority_resolve_group(group_name: str = "TerrainPriorityResolve"):
    """Creates a node group that resolves priority masks."""
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket("Raw Mask", "INPUT", "NodeSocketFloat")
    ng.interface.new_socket("Strength", "INPUT", "NodeSocketFloat")
    ng.interface.new_socket("Remaining", "INPUT", "NodeSocketFloat")
    ng.interface.new_socket("Actual Mask", "OUTPUT", "NodeSocketFloat")
    ng.interface.new_socket("Remaining Out", "OUTPUT", "NodeSocketFloat")

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
) -> tuple[MaskSocket, MaskSocket]:
    resolve_group = bpy.data.node_groups.get(
        group_name
    ) or create_priority_resolve_group(group_name)
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = resolve_group

    nt.links.new(raw_mask, node.inputs["Raw Mask"])
    node.inputs["Strength"].default_value = float(strength_value)
    nt.links.new(remaining_socket, node.inputs["Remaining"])

    return node.outputs["Actual Mask"], node.outputs["Remaining Out"]


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
        # Raw mask
        if isinstance(layer.mask, HeightMask):
            raw = add_height_mask_node(ng, layer.mask)
        elif isinstance(layer.mask, SlopeMask):
            raw = add_slope_mask_node(ng, layer.mask)
        else:
            raw = no_mask(ng)

        # Resolve priority via node group
        actual, remaining = add_priority_resolve_node(
            ng,
            raw_mask=raw,
            strength_value=layer.strength,
            remaining_socket=remaining,
        )

        # Store resulting (priority-resolved) mask
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.domain = "POINT"
        store.data_type = "FLOAT"
        store.inputs["Name"].default_value = layer.name

        links.new(prev_geo, store.inputs["Geometry"])
        links.new(actual, store.inputs["Value"])

        prev_geo = store.outputs["Geometry"]

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
