from utility.blender import add_socket, get_or_create_group, rebuild_group_if_missing_inputs
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

    gin = nodes.new("NodeGroupInput"); gin.location = (-920, 0)
    gout = nodes.new("NodeGroupOutput"); gout.location = (520, 0)

    add_socket(ng, in_out="INPUT", name="Vector", socket_type="NodeSocketVector", default=(0.0, 0.0, 0.0))
    add_socket(ng, in_out="INPUT", name="UV Scale", socket_type="NodeSocketFloat", default=1.0, min_val=0.0)
    add_socket(ng, in_out="INPUT", name="Warp Noise Centered", socket_type="NodeSocketFloat", default=0.0)
    add_socket(ng, in_out="INPUT", name="UV Warp Amount", socket_type="NodeSocketFloat", default=0.0, min_val=0.0, max_val=1.0)

    add_socket(ng, in_out="OUTPUT", name="Warped Vector", socket_type="NodeSocketVector")

    # scaled_vec = Vector * UV Scale
    uv_scale = nodes.new("ShaderNodeVectorMath"); uv_scale.location = (-640, 120)
    uv_scale.operation = "SCALE"
    links.new(gin.outputs["Vector"], uv_scale.inputs[0])
    links.new(gin.outputs["UV Scale"], uv_scale.inputs[3])

    # dy = fract(n * phi) - 0.5
    phi_mul = nodes.new("ShaderNodeMath"); phi_mul.location = (-640, -120)
    phi_mul.operation = "MULTIPLY"
    phi_mul.inputs[1].default_value = 1.61803398875
    links.new(gin.outputs["Warp Noise Centered"], phi_mul.inputs[0])

    phi_frac = nodes.new("ShaderNodeMath"); phi_frac.location = (-460, -120)
    phi_frac.operation = "FRACT"
    links.new(phi_mul.outputs["Value"], phi_frac.inputs[0])

    phi_sub = nodes.new("ShaderNodeMath"); phi_sub.location = (-280, -120)
    phi_sub.operation = "SUBTRACT"
    phi_sub.inputs[1].default_value = 0.5
    links.new(phi_frac.outputs["Value"], phi_sub.inputs[0])

    warp_vec = nodes.new("ShaderNodeCombineXYZ"); warp_vec.location = (-100, -120)
    links.new(gin.outputs["Warp Noise Centered"], warp_vec.inputs["X"])
    links.new(phi_sub.outputs["Value"], warp_vec.inputs["Y"])
    # Z stays 0

    # warp_scaled = warp_vec * UV Warp Amount
    warp_scale = nodes.new("ShaderNodeVectorMath"); warp_scale.location = (-100, 40)
    warp_scale.operation = "SCALE"
    links.new(warp_vec.outputs["Vector"], warp_scale.inputs[0])
    links.new(gin.outputs["UV Warp Amount"], warp_scale.inputs[3])

    # warped = scaled + warp_scaled
    addv = nodes.new("ShaderNodeVectorMath"); addv.location = (220, 80)
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

    ng = get_or_create_group("NG_PBR_WarpedUV_FromDualNoise", _build)
    # Ensure inputs exist (handles older versions)
    return rebuild_group_if_missing_inputs("NG_PBR_WarpedUV_FromDualNoise", required, _build)