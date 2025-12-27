from utility.blender import (
    rebuild_group_if_missing_inputs,
)
import bpy
import math


def _make_pbr_antitile_uvb_fac_group(
    group_name="NG_PBR_AntiTile_UVB_Fac_FromDualNoise",
):
    """
    Produces UV B (rotated+offset) and blend factor for BaseColor anti-tiling.
    Inputs:
      Warped Vector (Vector)
      AntiTile Noise Centered (Float) ~ [-0.5..0.5]
      AntiTile Enable (Float 0..1)
      AntiTile Blend (Float 0..1)
      AntiTile Angle (Float radians)
      AntiTile Offset (Vector)
    Outputs:
      UV B (Vector)
      Fac (Float)

    Fac = clamp( clamp(n + 0.5) * AntiTile Blend * AntiTile Enable )
    UV B = Mapping(Warped Vector, rotZ=AntiTile Angle, loc=AntiTile Offset)
    """
    ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    s = ng.interface.new_socket(
        name="Warped Vector",
        in_out="INPUT",
        socket_type="NodeSocketVector",
    )
    s.default_value = (0.0, 0.0, 0.0)

    s = ng.interface.new_socket(
        name="AntiTile Noise Centered",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    s.default_value = 0.0

    s = ng.interface.new_socket(
        name="AntiTile Enable",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    s.default_value = 0.0
    s.min_value = 0.0
    s.max_value = 1.0

    s = ng.interface.new_socket(
        name="AntiTile Blend",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    s.default_value = 1.0
    s.min_value = 0.0
    s.max_value = 1.0

    s = ng.interface.new_socket(
        name="AntiTile Angle",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    s.default_value = math.radians(60.0)
    s.min_value = -math.pi
    s.max_value = math.pi

    s = ng.interface.new_socket(
        name="AntiTile Offset",
        in_out="INPUT",
        socket_type="NodeSocketVector",
    )
    s.default_value = (0.37, 0.11, 0.0)

    ng.interface.new_socket(
        name="UV B",
        in_out="OUTPUT",
        socket_type="NodeSocketVector",
    )
    ng.interface.new_socket(
        name="Fac",
        in_out="OUTPUT",
        socket_type="NodeSocketFloat",
    )

    # Fac = clamp( clamp(n + 0.5) * blend * enable )
    addn = nodes.new("ShaderNodeMath")
    addn.location = (-640, 220)
    addn.operation = "ADD"
    addn.inputs[1].default_value = 0.5
    links.new(gin.outputs["AntiTile Noise Centered"], addn.inputs[0])

    clamp1 = nodes.new("ShaderNodeClamp")
    clamp1.location = (-460, 220)
    links.new(addn.outputs["Value"], clamp1.inputs["Value"])

    mul1 = nodes.new("ShaderNodeMath")
    mul1.location = (-280, 220)
    mul1.operation = "MULTIPLY"
    links.new(clamp1.outputs["Result"], mul1.inputs[0])
    links.new(gin.outputs["AntiTile Blend"], mul1.inputs[1])

    mul2 = nodes.new("ShaderNodeMath")
    mul2.location = (-100, 220)
    mul2.operation = "MULTIPLY"
    links.new(mul1.outputs["Value"], mul2.inputs[0])
    links.new(gin.outputs["AntiTile Enable"], mul2.inputs[1])

    clamp2 = nodes.new("ShaderNodeClamp")
    clamp2.location = (80, 220)
    links.new(mul2.outputs["Value"], clamp2.inputs["Value"])
    links.new(clamp2.outputs["Result"], gout.inputs["Fac"])

    # UV B = Mapping(warped, rotZ=angle, loc=offset)
    rot = nodes.new("ShaderNodeCombineXYZ")
    rot.location = (-460, -120)
    links.new(gin.outputs["AntiTile Angle"], rot.inputs["Z"])

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-220, -40)
    mapping.vector_type = "POINT"
    links.new(gin.outputs["Warped Vector"], mapping.inputs["Vector"])
    links.new(rot.outputs["Vector"], mapping.inputs["Rotation"])
    links.new(gin.outputs["AntiTile Offset"], mapping.inputs["Location"])

    links.new(mapping.outputs["Vector"], gout.inputs["UV B"])
    return ng


def ensure_pbr_antitile_uvb_fac_group():
    required = {
        "Warped Vector",
        "AntiTile Noise Centered",
        "AntiTile Enable",
        "AntiTile Blend",
        "AntiTile Angle",
        "AntiTile Offset",
    }

    def _build():
        return _make_pbr_antitile_uvb_fac_group("NG_PBR_AntiTile_UVB_Fac_FromDualNoise")

    return rebuild_group_if_missing_inputs(
        "NG_PBR_AntiTile_UVB_Fac_FromDualNoise", required, _build
    )
