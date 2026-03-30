import bpy
from terrain_layers.shader.helpers import (
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
    gout = nodes.new("NodeGroupOutput")

    # --- Inline sockets (no add_socket) ---
    iface = getattr(ng, "interface", None)

    if iface is not None:
        s = iface.new_socket(
            name="Vector", in_out="INPUT", socket_type="NodeSocketVector"
        )
        if hasattr(s, "default_value"):
            s.default_value = (0.0, 0.0, 0.0)

        s = iface.new_socket(
            name="Scale", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 6.0
        if hasattr(s, "min_value"):
            s.min_value = 0.0

        s = iface.new_socket(
            name="Large Scale", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 1.5
        if hasattr(s, "min_value"):
            s.min_value = 0.0

        s = iface.new_socket(
            name="Large Mix", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 0.35
        if hasattr(s, "min_value"):
            s.min_value = 0.0
        if hasattr(s, "max_value"):
            s.max_value = 1.0

        s = iface.new_socket(
            name="Detail", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 1.0
        if hasattr(s, "min_value"):
            s.min_value = 0.0
        if hasattr(s, "max_value"):
            s.max_value = 2.0

        iface.new_socket(
            name="Noise Centered", in_out="OUTPUT", socket_type="NodeSocketFloat"
        )
    else:
        # Fallback for older Blender builds
        s = ng.inputs.new("NodeSocketVector", "Vector")
        s.default_value = (0.0, 0.0, 0.0)

        s = ng.inputs.new("NodeSocketFloat", "Scale")
        s.default_value = 6.0
        s.min_value = 0.0

        s = ng.inputs.new("NodeSocketFloat", "Large Scale")
        s.default_value = 1.5
        s.min_value = 0.0

        s = ng.inputs.new("NodeSocketFloat", "Large Mix")
        s.default_value = 0.35
        s.min_value = 0.0
        s.max_value = 1.0

        s = ng.inputs.new("NodeSocketFloat", "Detail")
        s.default_value = 1.0
        s.min_value = 0.0
        s.max_value = 2.0

        ng.outputs.new("NodeSocketFloat", "Noise Centered")

    n_small = nodes.new("ShaderNodeTexNoise")
    n_small.noise_dimensions = "2D"
    n_small.inputs["Roughness"].default_value = 0.5
    n_small.inputs["Distortion"].default_value = 0.0

    n_large = nodes.new("ShaderNodeTexNoise")
    n_large.noise_dimensions = "2D"
    n_large.inputs["Roughness"].default_value = 0.5
    n_large.inputs["Distortion"].default_value = 0.0

    mix_n = nodes.new("ShaderNodeMix")
    mix_n.data_type = "FLOAT"

    center = nodes.new("ShaderNodeMath")
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
    gout = nodes.new("NodeGroupOutput")

    # --- Inline sockets (no add_socket) ---
    iface = getattr(ng, "interface", None)

    if iface is not None:
        s = iface.new_socket(name="Mask", in_out="INPUT", socket_type="NodeSocketFloat")
        if hasattr(s, "default_value"):
            s.default_value = 0.5
        if hasattr(s, "min_value"):
            s.min_value = 0.0
        if hasattr(s, "max_value"):
            s.max_value = 1.0

        s = iface.new_socket(
            name="Noise Centered", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 0.0

        s = iface.new_socket(
            name="Amount", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 0.75
        if hasattr(s, "min_value"):
            s.min_value = 0.0
        if hasattr(s, "max_value"):
            s.max_value = 5.0

        s = iface.new_socket(
            name="Sharpness", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 1.8
        if hasattr(s, "min_value"):
            s.min_value = 0.1
        if hasattr(s, "max_value"):
            s.max_value = 10.0

        s = iface.new_socket(name="Bias", in_out="INPUT", socket_type="NodeSocketFloat")
        if hasattr(s, "default_value"):
            s.default_value = 0.0
        if hasattr(s, "min_value"):
            s.min_value = -1.0
        if hasattr(s, "max_value"):
            s.max_value = 1.0

        s = iface.new_socket(
            name="Zone Width", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 0.15
        if hasattr(s, "min_value"):
            s.min_value = 0.0
        if hasattr(s, "max_value"):
            s.max_value = 0.5

        s = iface.new_socket(
            name="Zone Softness", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        if hasattr(s, "default_value"):
            s.default_value = 2.0
        if hasattr(s, "min_value"):
            s.min_value = 0.1
        if hasattr(s, "max_value"):
            s.max_value = 10.0

        iface.new_socket(name="Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")
    else:
        # Fallback for older Blender builds
        s = ng.inputs.new("NodeSocketFloat", "Mask")
        s.default_value = 0.5
        s.min_value = 0.0
        s.max_value = 1.0

        s = ng.inputs.new("NodeSocketFloat", "Noise Centered")
        s.default_value = 0.0

        s = ng.inputs.new("NodeSocketFloat", "Amount")
        s.default_value = 0.75
        s.min_value = 0.0
        s.max_value = 5.0

        s = ng.inputs.new("NodeSocketFloat", "Sharpness")
        s.default_value = 1.8
        s.min_value = 0.1
        s.max_value = 10.0

        s = ng.inputs.new("NodeSocketFloat", "Bias")
        s.default_value = 0.0
        s.min_value = -1.0
        s.max_value = 1.0

        s = ng.inputs.new("NodeSocketFloat", "Zone Width")
        s.default_value = 0.15
        s.min_value = 0.0
        s.max_value = 0.5

        s = ng.inputs.new("NodeSocketFloat", "Zone Softness")
        s.default_value = 2.0
        s.min_value = 0.1
        s.max_value = 10.0

        ng.outputs.new("NodeSocketFloat", "Mask")

    m_sub = nodes.new("ShaderNodeMath")
    m_sub.operation = "SUBTRACT"
    m_sub.inputs[1].default_value = 0.5

    m_abs = nodes.new("ShaderNodeMath")
    m_abs.operation = "ABSOLUTE"

    zone_map = nodes.new("ShaderNodeMapRange")
    zone_map.clamp = True
    zone_map.inputs["From Min"].default_value = 0.0
    zone_map.inputs["To Min"].default_value = 1.0
    zone_map.inputs["To Max"].default_value = 0.0

    zone_pow = nodes.new("ShaderNodeMath")
    zone_pow.operation = "POWER"

    n_amt = nodes.new("ShaderNodeMath")
    n_amt.operation = "MULTIPLY"

    n_zone = nodes.new("ShaderNodeMath")
    n_zone.operation = "MULTIPLY"

    m_add = nodes.new("ShaderNodeMath")
    m_add.operation = "ADD"

    m_bias = nodes.new("ShaderNodeMath")
    m_bias.operation = "ADD"

    s_sub = nodes.new("ShaderNodeMath")
    s_sub.operation = "SUBTRACT"
    s_sub.inputs[1].default_value = 0.5

    s_mul = nodes.new("ShaderNodeMath")
    s_mul.operation = "MULTIPLY"

    s_add = nodes.new("ShaderNodeMath")
    s_add.operation = "ADD"
    s_add.inputs[1].default_value = 0.5

    clamp = nodes.new("ShaderNodeClamp")

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
