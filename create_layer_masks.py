import bpy
from utility.geo_nodes import active_mesh_object, remove_node_group, ensure_geo_nodes_modifier
from utility.rearrange import arrange_nodes
from utility.nodes import gn_value_float, gn_math_multiply, gn_math_subtract, gn_clamp_0_1
"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""

def sort_layers_by_priority(layers: list[dict], priority_key="priority") -> list[dict]:
    """
    Returns layers sorted by priority DESC (higher priority first).
    Stable for equal priorities: earlier items in the config win ties.
    """
    indexed = list(enumerate(layers))

    def key(item):
        idx, layer = item
        prio = int(layer.get(priority_key, 0))
        # sort by prio DESC, then idx ASC (stable tiebreak)
        return (-prio, idx)

    indexed.sort(key=key)
    return [layer for _, layer in indexed]


# ============================================================
# Mask groups
# ============================================================

def create_height_mask_group(group_name="TerrainHeightMask"):
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(name="Position", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket(name="Min Height", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(name="Max Height", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(name="Ramp Low", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(name="Ramp High", in_out="INPUT", socket_type="NodeSocketFloat")
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


def add_height_mask_node(nt, mask_def: dict, *, group_name="TerrainHeightMask"):
    mask_group = bpy.data.node_groups.get(group_name) or create_height_mask_group(group_name)
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = mask_group

    pos_node = nt.nodes.new("GeometryNodeInputPosition")
    nt.links.new(pos_node.outputs["Position"], node.inputs["Position"])

    node.inputs["Min Height"].default_value = float(mask_def.get("min_height", 0.0))
    node.inputs["Max Height"].default_value = float(mask_def.get("max_height", 10.0))
    node.inputs["Ramp Low"].default_value = float(mask_def.get("ramp_low", 0.4))
    node.inputs["Ramp High"].default_value = float(mask_def.get("ramp_high", 0.6))

    return node.outputs["Mask"]


def no_mask(nt):
    """Default raw mask active everywhere."""
    return gn_value_float(nt, 1.0, label="RawMask:Full")


def create_priority_resolve_group(group_name="TerrainPriorityResolve"):
    """Creates a node group that resolves priority masks."""
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket("Raw Mask","INPUT","NodeSocketFloat")
    ng.interface.new_socket("Strength","INPUT","NodeSocketFloat")
    ng.interface.new_socket("Remaining","INPUT","NodeSocketFloat")
    ng.interface.new_socket("Actual Mask","OUTPUT","NodeSocketFloat")
    ng.interface.new_socket("Remaining Out","OUTPUT","NodeSocketFloat")

    gin, gout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")

    # weighted = clamp(raw * strength)
    w = gn_clamp_0_1(ng, gn_math_multiply(ng, gin.outputs["Raw Mask"], gin.outputs["Strength"], label="R*S"))
    
    # actual = w * remaining
    a = gn_math_multiply(ng, w, gin.outputs["Remaining"], label="A=w*R")
    
    # remaining_out = clamp(remaining - actual)
    r = gn_math_subtract(ng, gin.outputs["Remaining"], a, clamp=True, label="R-A")

    ng.links.new(a, gout.inputs["Actual Mask"])
    ng.links.new(r, gout.inputs["Remaining Out"])
    return ng



def add_priority_resolve_node(nt, *, raw_mask, strength_value: float, remaining_socket, group_name="TerrainPriorityResolve"):
    resolve_group = bpy.data.node_groups.get(group_name) or create_priority_resolve_group(group_name)
    node = nt.nodes.new("GeometryNodeGroup")
    node.node_tree = resolve_group

    nt.links.new(raw_mask, node.inputs["Raw Mask"])
    node.inputs["Strength"].default_value = float(strength_value)
    nt.links.new(remaining_socket, node.inputs["Remaining"])

    actual = node.outputs["Actual Mask"]
    remaining_out = node.outputs["Remaining Out"]
    return actual, remaining_out


# ============================================================
# Main builder
# ============================================================

def create_terrain_layers(config):
    obj = active_mesh_object()

    mod_name = config.get("geometry_modifier_name", "Terrain_Layer_Masks")
    layers = config.get("layers", [])
    if not layers:
        raise RuntimeError("Config has no layers.")

    layers_sorted = sort_layers_by_priority(layers)

    group_name = mod_name
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.items_tree.remove(it)

    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    prev_geo = gin.outputs["Geometry"]

    # Remaining starts at 1.0
    remaining = gn_value_float(ng, 1.0, label="Remaining:Start")

    for layer in layers_sorted:
        name = layer["name"]
        mask_def = layer.get("mask")
        strength = float(layer.get("strength", 1.0))

        # Raw mask
        if isinstance(mask_def, dict) and mask_def.get("type") == "height":
            raw = add_height_mask_node(ng, mask_def)
        else:
            raw = no_mask(ng)

        # Resolve priority via node group
        actual, remaining = add_priority_resolve_node(
            ng,
            raw_mask=raw,
            strength_value=strength,
            remaining_socket=remaining,
        )

        # Store resulting (priority-resolved) mask
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.domain = "POINT"
        store.data_type = "FLOAT"
        store.inputs["Name"].default_value = name

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
    config = {
        "geometry_modifier_name": "Terrain_Layer_Masks",
        "layers": [
            {"name": "Underwater", "priority": 0, "strength": 1.0},
            {
                "name": "Beach",
                "priority": 10,
                "strength": 1.0,
                "mask": {"type": "height", "min_height": 1.5, "max_height": 7.5, "ramp_low": 0.35, "ramp_high": 0.55},
            },
            {
                "name": "Grass",
                "priority": 20,
                "strength": 1.0,
                "mask": {"type": "height", "min_height": 3.5, "max_height": 8.0, "ramp_low": 0.45, "ramp_high": 0.65},
            },
            {
                "name": "Snow",
                "priority": 30,
                "strength": 1.0,
                "mask": {"type": "height", "min_height": 9.0, "max_height": 15.0, "ramp_low": 0.45, "ramp_high": 0.65},
            },
        ],
    }

    create_terrain_layers(config)
