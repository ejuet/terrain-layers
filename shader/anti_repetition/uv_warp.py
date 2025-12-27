from shader.helpers import (
    rebuild_group_if_missing_inputs,
)
import bpy


def _make_pbr_warped_uv_group(group_name="NG_PBR_WarpedUV_FromDualNoise"):
    """
    Creates warped UVs using ONE centered dual-noise float.
    Inputs:
      Vector (Vector)
      UV Scale (Float)
      Warp Noise Centered (Float)  ~ [-0.5..0.5]
      UV Warp Amount (Float)       0..1
    Output:
      Warped Vector (Vector)

    Warped Vector = (Vector * UV Scale) + (WarpVecFromNoise(WarpNoise) * UV Warp Amount)

    WarpVecFromNoise:
      dx = n
      dy = fract(n * phi) - 0.5
      z  = 0
    """
    ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    s = ng.inputs.new("NodeSocketVector", "Vector")
    s.default_value = (0.0, 0.0, 0.0)

    s = ng.inputs.new("NodeSocketFloat", "UV Scale")
    s.default_value = 1.0
    if hasattr(s, "min_value"):
        s.min_value = 0.0

    s = ng.inputs.new("NodeSocketFloat", "Warp Noise Centered")
    s.default_value = 0.0

    s = ng.inputs.new("NodeSocketFloat", "UV Warp Amount")
    s.default_value = 0.0
    if hasattr(s, "min_value"):
        s.min_value = 0.0
    if hasattr(s, "max_value"):
        s.max_value = 1.0

    ng.outputs.new("NodeSocketVector", "Warped Vector")

    # scaled_vec = Vector * UV Scale
    uv_scale = nodes.new("ShaderNodeVectorMath")
    uv_scale.operation = "SCALE"
    links.new(gin.outputs["Vector"], uv_scale.inputs[0])
    links.new(gin.outputs["UV Scale"], uv_scale.inputs[3])

    # dy = fract(n * phi) - 0.5
    phi_mul = nodes.new("ShaderNodeMath")
    phi_mul.operation = "MULTIPLY"
    phi_mul.inputs[1].default_value = 1.61803398875
    links.new(gin.outputs["Warp Noise Centered"], phi_mul.inputs[0])

    phi_frac = nodes.new("ShaderNodeMath")
    phi_frac.operation = "FRACT"
    links.new(phi_mul.outputs["Value"], phi_frac.inputs[0])

    phi_sub = nodes.new("ShaderNodeMath")
    phi_sub.operation = "SUBTRACT"
    phi_sub.inputs[1].default_value = 0.5
    links.new(phi_frac.outputs["Value"], phi_sub.inputs[0])

    warp_vec = nodes.new("ShaderNodeCombineXYZ")
    links.new(gin.outputs["Warp Noise Centered"], warp_vec.inputs["X"])
    links.new(phi_sub.outputs["Value"], warp_vec.inputs["Y"])
    # Z stays 0

    # warp_scaled = warp_vec * UV Warp Amount
    warp_scale = nodes.new("ShaderNodeVectorMath")
    warp_scale.operation = "SCALE"
    links.new(warp_vec.outputs["Vector"], warp_scale.inputs[0])
    links.new(gin.outputs["UV Warp Amount"], warp_scale.inputs[3])

    # warped = scaled + warp_scaled
    addv = nodes.new("ShaderNodeVectorMath")
    addv.operation = "ADD"
    links.new(uv_scale.outputs["Vector"], addv.inputs[0])
    links.new(warp_scale.outputs["Vector"], addv.inputs[1])

    links.new(addv.outputs["Vector"], gout.inputs["Warped Vector"])
    return ng


def ensure_pbr_warped_uv_group():
    required = {"Vector", "UV Scale", "Warp Noise Centered", "UV Warp Amount"}

    # Using get_or_create_group for cache + rebuild_group_if_missing_inputs for compatibility
    def _build():
        return _make_pbr_warped_uv_group("NG_PBR_WarpedUV_FromDualNoise")

    # Ensure inputs exist (handles older versions)
    return rebuild_group_if_missing_inputs(
        "NG_PBR_WarpedUV_FromDualNoise", required, _build
    )
