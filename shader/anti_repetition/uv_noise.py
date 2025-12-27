import bpy
from utility.blender import (
    add_socket,
    rebuild_group_if_missing_inputs,
)


# ---------------------------------------------------------
# NEW: Shared Dual Noise (expensive part, reusable per params)
# ---------------------------------------------------------
def _make_dual_noise_group(group_name="NG_DualNoise2D"):
    ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gin.location = (-900, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (420, 0)

    add_socket(
        ng,
        in_out="INPUT",
        name="Vector",
        socket_type="NodeSocketVector",
        default=(0.0, 0.0, 0.0),
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Scale",
        socket_type="NodeSocketFloat",
        default=6.0,
        min_val=0.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Large Scale",
        socket_type="NodeSocketFloat",
        default=1.5,
        min_val=0.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Large Mix",
        socket_type="NodeSocketFloat",
        default=0.35,
        min_val=0.0,
        max_val=1.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Detail",
        socket_type="NodeSocketFloat",
        default=1.0,
        min_val=0.0,
        max_val=2.0,
    )

    add_socket(
        ng, in_out="OUTPUT", name="Noise Centered", socket_type="NodeSocketFloat"
    )

    n_small = nodes.new("ShaderNodeTexNoise")
    n_small.location = (-640, 140)
    n_small.noise_dimensions = "2D"
    n_small.inputs["Roughness"].default_value = 0.5
    n_small.inputs["Distortion"].default_value = 0.0

    n_large = nodes.new("ShaderNodeTexNoise")
    n_large.location = (-640, -40)
    n_large.noise_dimensions = "2D"
    n_large.inputs["Roughness"].default_value = 0.5
    n_large.inputs["Distortion"].default_value = 0.0

    mix_n = nodes.new("ShaderNodeMix")
    mix_n.location = (-420, 50)
    mix_n.data_type = "FLOAT"

    center = nodes.new("ShaderNodeMath")
    center.location = (-220, 50)
    center.operation = "SUBTRACT"
    center.inputs[1].default_value = 0.5

    links.new(gin.outputs["Vector"], n_small.inputs["Vector"])
    links.new(gin.outputs["Scale"], n_small.inputs["Scale"])
    links.new(gin.outputs["Detail"], n_small.inputs["Detail"])

    links.new(gin.outputs["Vector"], n_large.inputs["Vector"])
    links.new(gin.outputs["Large Scale"], n_large.inputs["Scale"])
    links.new(gin.outputs["Detail"], n_large.inputs["Detail"])

    links.new(gin.outputs["Large Mix"], mix_n.inputs["Factor"])
    links.new(n_small.outputs["Fac"], mix_n.inputs["A"])
    links.new(n_large.outputs["Fac"], mix_n.inputs["B"])

    links.new(mix_n.outputs["Result"], center.inputs[0])
    links.new(center.outputs["Value"], gout.inputs["Noise Centered"])

    return ng


def _ensure_dual_noise_group():
    required = {"Vector", "Scale", "Large Scale", "Large Mix", "Detail"}
    ng = rebuild_group_if_missing_inputs(
        "NG_DualNoise2D",
        required,
        lambda: _make_dual_noise_group("NG_DualNoise2D"),
    )
    return ng


# ---------------------------------------------------------
# NEW: Apply Zoned Noise to Mask (cheap part, per-mask)
# ---------------------------------------------------------
def _make_apply_mask_noise_group(group_name="NG_ApplyMaskNoiseZoned"):
    ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gin.location = (-900, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (520, 0)

    add_socket(
        ng,
        in_out="INPUT",
        name="Mask",
        socket_type="NodeSocketFloat",
        default=0.5,
        min_val=0.0,
        max_val=1.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Noise Centered",
        socket_type="NodeSocketFloat",
        default=0.0,
    )

    add_socket(
        ng,
        in_out="INPUT",
        name="Amount",
        socket_type="NodeSocketFloat",
        default=0.75,
        min_val=0.0,
        max_val=5.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Sharpness",
        socket_type="NodeSocketFloat",
        default=1.8,
        min_val=0.1,
        max_val=10.0,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Bias",
        socket_type="NodeSocketFloat",
        default=0.0,
        min_val=-1.0,
        max_val=1.0,
    )

    add_socket(
        ng,
        in_out="INPUT",
        name="Zone Width",
        socket_type="NodeSocketFloat",
        default=0.15,
        min_val=0.0,
        max_val=0.5,
    )
    add_socket(
        ng,
        in_out="INPUT",
        name="Zone Softness",
        socket_type="NodeSocketFloat",
        default=2.0,
        min_val=0.1,
        max_val=10.0,
    )

    add_socket(ng, in_out="OUTPUT", name="Mask", socket_type="NodeSocketFloat")

    m_sub = nodes.new("ShaderNodeMath")
    m_sub.location = (-680, 240)
    m_sub.operation = "SUBTRACT"
    m_sub.inputs[1].default_value = 0.5
    m_abs = nodes.new("ShaderNodeMath")
    m_abs.location = (-520, 240)
    m_abs.operation = "ABSOLUTE"

    zone_map = nodes.new("ShaderNodeMapRange")
    zone_map.location = (-340, 240)
    zone_map.clamp = True
    zone_map.inputs["From Min"].default_value = 0.0
    zone_map.inputs["To Min"].default_value = 1.0
    zone_map.inputs["To Max"].default_value = 0.0

    zone_pow = nodes.new("ShaderNodeMath")
    zone_pow.location = (-160, 240)
    zone_pow.operation = "POWER"

    n_amt = nodes.new("ShaderNodeMath")
    n_amt.location = (-340, 40)
    n_amt.operation = "MULTIPLY"
    n_zone = nodes.new("ShaderNodeMath")
    n_zone.location = (-160, 40)
    n_zone.operation = "MULTIPLY"

    m_add = nodes.new("ShaderNodeMath")
    m_add.location = (40, 60)
    m_add.operation = "ADD"
    m_bias = nodes.new("ShaderNodeMath")
    m_bias.location = (200, 60)
    m_bias.operation = "ADD"

    s_sub = nodes.new("ShaderNodeMath")
    s_sub.location = (40, -100)
    s_sub.operation = "SUBTRACT"
    s_sub.inputs[1].default_value = 0.5
    s_mul = nodes.new("ShaderNodeMath")
    s_mul.location = (200, -100)
    s_mul.operation = "MULTIPLY"
    s_add = nodes.new("ShaderNodeMath")
    s_add.location = (360, -100)
    s_add.operation = "ADD"
    s_add.inputs[1].default_value = 0.5

    clamp = nodes.new("ShaderNodeClamp")
    clamp.location = (460, 20)

    links.new(gin.outputs["Mask"], m_sub.inputs[0])
    links.new(m_sub.outputs["Value"], m_abs.inputs[0])
    links.new(m_abs.outputs["Value"], zone_map.inputs["Value"])
    links.new(gin.outputs["Zone Width"], zone_map.inputs["From Max"])
    links.new(zone_map.outputs["Result"], zone_pow.inputs[0])
    links.new(gin.outputs["Zone Softness"], zone_pow.inputs[1])

    links.new(gin.outputs["Noise Centered"], n_amt.inputs[0])
    links.new(gin.outputs["Amount"], n_amt.inputs[1])
    links.new(n_amt.outputs["Value"], n_zone.inputs[0])
    links.new(zone_pow.outputs["Value"], n_zone.inputs[1])

    links.new(gin.outputs["Mask"], m_add.inputs[0])
    links.new(n_zone.outputs["Value"], m_add.inputs[1])

    links.new(m_add.outputs["Value"], m_bias.inputs[0])
    links.new(gin.outputs["Bias"], m_bias.inputs[1])

    links.new(m_bias.outputs["Value"], s_sub.inputs[0])
    links.new(s_sub.outputs["Value"], s_mul.inputs[0])
    links.new(gin.outputs["Sharpness"], s_mul.inputs[1])
    links.new(s_mul.outputs["Value"], s_add.inputs[0])

    links.new(s_add.outputs["Value"], clamp.inputs["Value"])
    links.new(clamp.outputs["Result"], gout.inputs["Mask"])

    return ng


def ensure_apply_mask_noise_group():
    required = {
        "Mask",
        "Noise Centered",
        "Amount",
        "Sharpness",
        "Bias",
        "Zone Width",
        "Zone Softness",
    }
    return rebuild_group_if_missing_inputs(
        "NG_ApplyMaskNoiseZoned",
        required,
        lambda: _make_apply_mask_noise_group("NG_ApplyMaskNoiseZoned"),
    )


# ---------------------------------------------------------
# Per-node-tree cache for shared DualNoise nodes
# ---------------------------------------------------------
global _DUAL_NOISE_NODE_CACHE
_DUAL_NOISE_NODE_CACHE = {}


def _dual_noise_cache_key(nt, *, scale, large_scale, large_mix, detail):
    return (
        nt.as_pointer(),
        round(float(scale), 6),
        round(float(large_scale), 6),
        round(float(large_mix), 6),
        round(float(detail), 6),
    )


def get_or_create_shared_dual_noise_node(
    nt, *, mapping_node, scale, large_scale, large_mix, detail
):
    """
    Creates ONE DualNoise sampler node per (node_tree + params). Reuses it across the node tree.
    Returns the output socket "Noise Centered".
    """
    key = _dual_noise_cache_key(
        nt, scale=scale, large_scale=large_scale, large_mix=large_mix, detail=detail
    )

    existing = _DUAL_NOISE_NODE_CACHE.get(key)
    if existing and existing.id_data == nt:
        return existing.outputs["Noise Centered"]

    nodes, links = nt.nodes, nt.links
    ng_dual = _ensure_dual_noise_group()

    g = nodes.new("ShaderNodeGroup")
    g.node_tree = ng_dual
    g.label = "Shared Dual Noise (Cached)"
    g.name = f"__SharedDualNoise_{abs(hash(key)) % 10_000_000}"

    # tuck it near mapping, but out of the main flow
    g.location = (mapping_node.location.x + 260, mapping_node.location.y - 320)

    links.new(mapping_node.outputs["Vector"], g.inputs["Vector"])
    g.inputs["Scale"].default_value = float(scale)
    g.inputs["Large Scale"].default_value = float(large_scale)
    g.inputs["Large Mix"].default_value = float(large_mix)
    g.inputs["Detail"].default_value = float(detail)

    _DUAL_NOISE_NODE_CACHE[key] = g
    return g.outputs["Noise Centered"]


def create_mask_noise(nt, *, base_mask, mapping_node, noise_def):

    nodes, links = nt.nodes, nt.links
    created_nodes = []

    scale = float(noise_def.get("scale", 6.0))
    large_scale = float(noise_def.get("large_scale", 1.5))
    large_mix = float(noise_def.get("large_mix", 0.35))
    detail = float(noise_def.get("detail", 1.0))

    noise_centered = get_or_create_shared_dual_noise_node(
        nt,
        mapping_node=mapping_node,
        scale=scale,
        large_scale=large_scale,
        large_mix=large_mix,
        detail=detail,
    )

    ng_apply = ensure_apply_mask_noise_group()
    g_apply = nodes.new("ShaderNodeGroup")
    g_apply.node_tree = ng_apply
    g_apply.label = "Mask Noise (Zoned, Cheap)"
    g_apply.location = (-720, 260)
    created_nodes.append(g_apply)

    links.new(base_mask, g_apply.inputs["Mask"])
    links.new(noise_centered, g_apply.inputs["Noise Centered"])

    g_apply.inputs["Amount"].default_value = float(noise_def.get("amount", 2.8))
    g_apply.inputs["Sharpness"].default_value = float(noise_def.get("sharpness", 1.8))
    g_apply.inputs["Bias"].default_value = float(noise_def.get("bias", 0.0))
    g_apply.inputs["Zone Width"].default_value = float(noise_def.get("zone_width", 0.5))
    g_apply.inputs["Zone Softness"].default_value = float(
        noise_def.get("zone_softness", 1.0)
    )

    return g_apply.outputs["Mask"], created_nodes
