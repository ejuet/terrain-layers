import bpy
from bpy.types import Node
from typing import Any
from dataclasses import dataclass
from utility.geo_nodes import remove_node_group, clear_group_interface
from masks.mask_types.type_helpers import MaskSocket
from utility.frame_nodes import frame_nodes

NOISE_ATTR_PREFIX = "__MaskNoiseCentered"


@dataclass(frozen=True, slots=True)
class DualNoiseConfig:
    # expensive/shared sampler params
    scale: float = 6.0
    large_scale: float = 1.5
    large_mix: float = 0.35
    detail: float = 1.0


@dataclass(frozen=True, slots=True)
class MaskNoiseConfig:
    # ties together sampler + application params
    dual: DualNoiseConfig = DualNoiseConfig()

    # cheap “apply to mask” params
    amount: float = 2.8
    sharpness: float = 1.8
    bias: float = 0.0
    zone_width: float = 0.5
    zone_softness: float = 1.0


def _dual_noise_attr_name(dual: DualNoiseConfig) -> str:
    # Stable, readable name. Round floats to keep names short & stable.
    s = round(float(dual.scale), 4)
    ls = round(float(dual.large_scale), 4)
    lm = round(float(dual.large_mix), 4)
    d = round(float(dual.detail), 4)
    # Avoid weird characters; keep underscore only.
    return f"{NOISE_ATTR_PREFIX}_s{s}_ls{ls}_lm{lm}_d{d}"


# ============================================================
# Noise node groups (Geometry Nodes)
# ============================================================


def create_dual_noise_centered_group(group_name: str = "GN_DualNoise2D_Centered"):
    """
    Outputs centered dual noise (all float math, Geometry Nodes-safe):

      small_fac and large_fac are floats.
      mix = small_fac * (1 - LargeMix) + large_fac * LargeMix
      centered = mix - 0.5

    Inputs:
      Vector, Scale, Large Scale, Large Mix, Detail
    Output:
      Noise Centered
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket("Vector", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("Scale", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        "Large Scale", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket("Large Mix", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Detail", in_out="INPUT", socket_type="NodeSocketFloat")

    ng.interface.new_socket(
        "Noise Centered", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    # Noise textures (shader nodes are allowed in GN trees; the issue was SeparateColor)
    n_small = nodes.new("ShaderNodeTexNoise")
    n_small.noise_dimensions = "2D"
    n_small.inputs["Roughness"].default_value = 0.5
    n_small.inputs["Distortion"].default_value = 0.0

    n_large = nodes.new("ShaderNodeTexNoise")
    n_large.noise_dimensions = "2D"
    n_large.inputs["Roughness"].default_value = 0.5
    n_large.inputs["Distortion"].default_value = 0.0

    # mix floats: small*(1-f) + large*f
    inv = nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0  # 1 - f

    mul_small = nodes.new("ShaderNodeMath")
    mul_small.operation = "MULTIPLY"

    mul_large = nodes.new("ShaderNodeMath")
    mul_large.operation = "MULTIPLY"

    add_mix = nodes.new("ShaderNodeMath")
    add_mix.operation = "ADD"

    center = nodes.new("ShaderNodeMath")
    center.operation = "SUBTRACT"
    center.inputs[1].default_value = 0.5

    # Inputs -> noise
    links.new(gin.outputs["Vector"], n_small.inputs["Vector"])
    links.new(gin.outputs["Scale"], n_small.inputs["Scale"])
    links.new(gin.outputs["Detail"], n_small.inputs["Detail"])

    links.new(gin.outputs["Vector"], n_large.inputs["Vector"])
    links.new(gin.outputs["Large Scale"], n_large.inputs["Scale"])
    links.new(gin.outputs["Detail"], n_large.inputs["Detail"])

    # fac wiring
    links.new(gin.outputs["Large Mix"], inv.inputs[1])  # inv = 1 - f
    links.new(gin.outputs["Large Mix"], mul_large.inputs[1])  # large * f
    links.new(inv.outputs["Value"], mul_small.inputs[1])  # small * (1-f)

    # noise wiring
    links.new(n_small.outputs["Fac"], mul_small.inputs[0])
    links.new(n_large.outputs["Fac"], mul_large.inputs[0])

    # sum + center
    links.new(mul_small.outputs["Value"], add_mix.inputs[0])
    links.new(mul_large.outputs["Value"], add_mix.inputs[1])
    links.new(add_mix.outputs["Value"], center.inputs[0])
    links.new(center.outputs["Value"], gout.inputs["Noise Centered"])

    # Layout
    gin.location = (-900, 0)
    n_small.location = (-640, 140)
    n_large.location = (-640, -40)
    inv.location = (-420, 120)
    mul_small.location = (-240, 140)
    mul_large.location = (-240, -20)
    add_mix.location = (-60, 60)
    center.location = (120, 60)
    gout.location = (320, 0)

    return ng


def ensure_dual_noise_centered_group(group_name: str = "GN_DualNoise2D_Centered"):
    return bpy.data.node_groups.get(group_name) or create_dual_noise_centered_group(
        group_name
    )


def create_apply_mask_noise_zoned_group(group_name: str = "GN_ApplyMaskNoiseZoned"):
    """
    Cheap "apply noise to mask" group matching your shader logic, simplified and 1:1:

      zone = pow( maprange( abs(mask-0.5), 0..zone_width -> 1..0 ), zone_softness )
      noisy = mask + (noise_centered * amount * zone)
      biased = noisy + bias
      sharp = clamp( ((biased-0.5) * sharpness) + 0.5 )

    Inputs:
      Mask, Noise Centered, Amount, Sharpness, Bias, Zone Width, Zone Softness
    Output:
      Mask
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    clear_group_interface(ng)
    ng.nodes.clear()

    ng.interface.new_socket("Mask", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        "Noise Centered", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket("Amount", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Sharpness", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Bias", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Zone Width", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        "Zone Softness", in_out="INPUT", socket_type="NodeSocketFloat"
    )

    ng.interface.new_socket("Mask", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

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

    gin.location = (-900, 0)
    m_sub.location = (-680, 240)
    m_abs.location = (-520, 240)
    zone_map.location = (-340, 240)
    zone_pow.location = (-160, 240)
    n_amt.location = (-340, 40)
    n_zone.location = (-160, 40)
    m_add.location = (40, 60)
    m_bias.location = (200, 60)
    s_sub.location = (40, -100)
    s_mul.location = (200, -100)
    s_add.location = (360, -100)
    clamp.location = (520, 20)
    gout.location = (700, 0)

    return ng


def ensure_apply_mask_noise_zoned_group(group_name: str = "GN_ApplyMaskNoiseZoned"):
    return bpy.data.node_groups.get(group_name) or create_apply_mask_noise_zoned_group(
        group_name
    )


def add_store_centered_noise_attribute(
    nt: bpy.types.NodeTree,
    *,
    input_geo_socket,
    attr_name: str,
    dual: DualNoiseConfig,
) -> tuple[Any, list[Node]]:
    """
    Adds nodes to:
      Position -> DualNoiseCentered(dual params) -> StoreNamedAttribute(attr_name)

    Returns:
      (output_geometry_socket, created_nodes)
    """
    nodes, links = nt.nodes, nt.links
    created: list[Node] = []

    dual_ng = ensure_dual_noise_centered_group()

    pos = nodes.new("GeometryNodeInputPosition")
    created.append(pos)

    dual_node = nodes.new("GeometryNodeGroup")
    dual_node.node_tree = dual_ng
    dual_node.label = "Shared Dual Noise (Centered)"
    created.append(dual_node)

    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.domain = "POINT"
    store.data_type = "FLOAT"
    store.inputs["Name"].default_value = attr_name
    created.append(store)

    links.new(pos.outputs["Position"], dual_node.inputs["Vector"])

    # set per-instance defaults
    dual_node.inputs["Scale"].default_value = float(dual.scale)
    dual_node.inputs["Large Scale"].default_value = float(dual.large_scale)
    dual_node.inputs["Large Mix"].default_value = float(dual.large_mix)
    dual_node.inputs["Detail"].default_value = float(dual.detail)

    links.new(input_geo_socket, store.inputs["Geometry"])
    links.new(dual_node.outputs["Noise Centered"], store.inputs["Value"])

    return store.outputs["Geometry"], created


def _named_attr_output_socket(read_node: bpy.types.Node) -> bpy.types.NodeSocket:
    # Blender version differences: some use "Attribute", some "Value".
    out = read_node.outputs.get("Attribute")
    if out is not None:
        return out
    out = read_node.outputs.get("Value")
    if out is not None:
        return out
    # Fall back to first output if needed
    return read_node.outputs[0]


def add_apply_mask_noise_from_attribute(
    nt: bpy.types.NodeTree,
    *,
    base_mask: MaskSocket,
    noise: MaskNoiseConfig,
    attr_name: str,
) -> tuple[MaskSocket, list[Node]]:
    """
    Reads centered noise from a named attribute and applies zoned mask noise
    using the cheap params in MaskNoiseConfig.
    """
    nodes, links = nt.nodes, nt.links
    created: list[Node] = []

    read = nodes.new("GeometryNodeInputNamedAttribute")
    read.data_type = "FLOAT"
    read.inputs["Name"].default_value = attr_name
    created.append(read)

    apply_ng = ensure_apply_mask_noise_zoned_group()
    apply = nodes.new("GeometryNodeGroup")
    apply.node_tree = apply_ng
    apply.label = "Mask Noise (Zoned)"
    created.append(apply)

    links.new(base_mask, apply.inputs["Mask"])
    links.new(_named_attr_output_socket(read), apply.inputs["Noise Centered"])

    apply.inputs["Amount"].default_value = float(noise.amount)
    apply.inputs["Sharpness"].default_value = float(noise.sharpness)
    apply.inputs["Bias"].default_value = float(noise.bias)
    apply.inputs["Zone Width"].default_value = float(noise.zone_width)
    apply.inputs["Zone Softness"].default_value = float(noise.zone_softness)

    return apply.outputs["Mask"], created


def create_dual_noise_cache(
    dual_noises: list[DualNoiseConfig | None], prev_geo: MaskSocket, ng
) -> tuple[dict[DualNoiseConfig, str], MaskSocket]:  # todo type
    """Creates and caches dual noise attributes for all dual noise configs used by layers."""
    duals_in_use: list[DualNoiseConfig] = []
    for d in dual_noises:
        if d is None:
            continue
        if d not in duals_in_use:
            duals_in_use.append(d)
    dual_to_attr: dict[DualNoiseConfig, str] = {}
    all_created_frames = []
    for i, d in enumerate(duals_in_use):
        attr = _dual_noise_attr_name(d)
        dual_to_attr[d] = attr

        prev_geo, created = add_store_centered_noise_attribute(
            ng,
            input_geo_socket=prev_geo,
            attr_name=attr,
            dual=d,
        )

        frame = frame_nodes(ng, f"Noise ({attr})", created)
        all_created_frames.append(frame)
    frame_nodes(ng, "Shared Centered Noises", all_created_frames)
    return dual_to_attr, prev_geo
