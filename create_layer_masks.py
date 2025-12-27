import bpy
from utility.geo_nodes import active_mesh_object, remove_node_group, ensure_geo_nodes_modifier
from utility.rearrange import arrange_nodes

"""
Terrain Layer Mask Utilities (only has to work for Blender 5.0.0+)
"""

# -----------------------------
# Mask groups
# -----------------------------
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

# -----------------------------
# Utility nodes
# -----------------------------
def const_float(nt, value: float, label=None):
    n = nt.nodes.new("ShaderNodeValue")
    n.outputs[0].default_value = float(value)
    if label:
        n.label = label
    return n.outputs[0]

def clamp_01(nt, value_socket):
    c = nt.nodes.new("ShaderNodeClamp")
    c.inputs["Min"].default_value = 0.0
    c.inputs["Max"].default_value = 1.0
    nt.links.new(value_socket, c.inputs["Value"])
    return c.outputs["Result"]

def mul(nt, a, b, label=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = "MULTIPLY"
    if label:
        n.label = label
    nt.links.new(a, n.inputs[0])
    nt.links.new(b, n.inputs[1])
    return n.outputs["Value"]

def sub(nt, a, b, clamp=False, label=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = "SUBTRACT"
    n.use_clamp = bool(clamp)
    if label:
        n.label = label
    nt.links.new(a, n.inputs[0])
    nt.links.new(b, n.inputs[1])
    return n.outputs["Value"]

# -----------------------------
# No mask fallback
# -----------------------------
def no_mask(nt):
    """
    Default mask that is active everywhere (outputs 1.0).
    """
    return const_float(nt, 1.0, label="No Mask (Full)")

# -----------------------------
# Main builder
# -----------------------------
def create_terrain_layers(config):
    obj = active_mesh_object()

    mod_name = config.get("geometry_modifier_name", "Terrain_Layer_Masks")
    layers = config.get("layers", [])
    if not layers:
        raise RuntimeError("Config has no layers.")

    # Stable sort by priority desc, preserving original order for ties
    indexed_layers = list(enumerate(layers))
    def _prio(item):
        idx, layer = item
        return (int(layer.get("priority", 0)), -idx)  # -idx so earlier entries win ties after reverse
    indexed_layers.sort(key=_prio, reverse=True)
    layers_sorted = [layer for _, layer in indexed_layers]

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

    # Remaining weight starts at 1.0
    remaining = const_float(ng, 1.0, label="Remaining (start=1)")

    for layer in layers_sorted:
        name = layer["name"]
        mask_def = layer.get("mask")
        strength_val = float(layer.get("strength", 1.0))

        # Raw mask
        if isinstance(mask_def, dict) and mask_def.get("type") == "height":
            raw = add_height_mask_node(ng, mask_def)
        else:
            raw = no_mask(ng)

        # weighted = clamp(raw * strength)
        strength = const_float(ng, strength_val, label=f"{name} Strength")
        weighted = mul(ng, raw, strength, label=f"{name} Weighted")
        weighted = clamp_01(ng, weighted)

        # actual = weighted * remaining
        actual = mul(ng, weighted, remaining, label=f"{name} Actual")

        # remaining = clamp(remaining - actual)
        remaining = sub(ng, remaining, actual, clamp=True, label="Remaining")

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
