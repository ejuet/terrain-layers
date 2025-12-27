from typing import Literal
from utility.geo_nodes import remove_node_group
import bpy
from masks.mask_types.type_helpers import MaskSocket, Node
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaintMask:
    type: Literal["paint"] = "paint"

    image_name: str = "IMG_TerrainPaintMask"
    uv_map_name: str = "UV_TerrainPaintMask"

    width: int = 1024
    height: int = 1024
    alpha: bool = True

    ramp_low: float = 0.0
    ramp_high: float = 1.0

    interpolation: Literal["Linear", "Closest", "Cubic", "Smart"] = "Linear"
    extension: Literal["REPEAT", "EXTEND", "CLIP", "MIRROR"] = "CLIP"


def _ensure_uv_map(obj: bpy.types.Object, uv_name: str):
    if obj.type != "MESH" or obj.data is None:
        raise TypeError("Paint mask requires an active Mesh object.")
    me: bpy.types.Mesh = obj.data  # type: ignore[assignment]
    uv = me.uv_layers.get(uv_name)
    if uv is None:
        uv = me.uv_layers.new(name=uv_name)
    return uv


def _ensure_paint_image(image_name: str, *, width: int, height: int, use_alpha: bool):
    img = bpy.data.images.get(image_name)
    if img is None:
        img = bpy.data.images.new(
            name=image_name,
            width=int(width),
            height=int(height),
            alpha=bool(use_alpha),
            float_buffer=False,
        )
        # Default black = no influence until painted
        try:
            img.generated_color = (0.0, 0.0, 0.0, 1.0)
        except Exception:
            pass
        img.use_fake_user = True
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    return img


def _group_has_io(ng: bpy.types.NodeTree, ins: list[str], outs: list[str]) -> bool:
    try:
        in_names = {s.name for s in getattr(ng, "inputs", [])}
        out_names = {s.name for s in getattr(ng, "outputs", [])}
        return all(n in in_names for n in ins) and all(n in out_names for n in outs)
    except Exception:
        return False


def _math(nt: bpy.types.NodeTree, op: str, label: str = "") -> bpy.types.Node:
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.label = label
    return n


def create_paint_mask_group(group_name: str = "TerrainPaintMask"):
    """
    Geometry Node Group:
      Inputs:
        UV (Vector)
        Image (Image)
        Ramp Low (Float)
        Ramp High (Float)
      Output:
        Mask (Float)
    """
    remove_node_group(group_name)
    ng = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(name="UV", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketImage")
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

    # Sample image (GN-native). If this node doesn't exist in your build, paint masks
    # can't be sampled in GN without custom nodes.
    tex = nodes.new("GeometryNodeImageTexture")
    tex.label = "Paint: Image Sample"
    tex.location = (-700, 0)

    if "Vector" in tex.inputs:
        links.new(gin.outputs["UV"], tex.inputs["Vector"])
    else:
        links.new(gin.outputs["UV"], tex.inputs[0])

    if "Image" in tex.inputs:
        links.new(gin.outputs["Image"], tex.inputs["Image"])

    color = tex.outputs.get("Color") or tex.outputs[0]

    # Separate RGB (this node is allowed in GN in your setup)
    sep = nodes.new("ShaderNodeSeparateXYZ")
    sep.label = "Separate RGB"
    sep.location = (-450, 0)
    links.new(color, sep.inputs["Vector"])

    # Luminance = R*0.2126 + G*0.7152 + B*0.0722
    mr = _math(ng, "MULTIPLY", "R*0.2126")
    mr.location = (-250, 120)
    links.new(sep.outputs["X"], mr.inputs[0])
    mr.inputs[1].default_value = 0.2126

    mg = _math(ng, "MULTIPLY", "G*0.7152")
    mg.location = (-250, 0)
    links.new(sep.outputs["Y"], mg.inputs[0])
    mg.inputs[1].default_value = 0.7152

    mb = _math(ng, "MULTIPLY", "B*0.0722")
    mb.location = (-250, -120)
    links.new(sep.outputs["Z"], mb.inputs[0])
    mb.inputs[1].default_value = 0.0722

    add_rg = _math(ng, "ADD", "R+G")
    add_rg.location = (-60, 60)
    links.new(mr.outputs[0], add_rg.inputs[0])
    links.new(mg.outputs[0], add_rg.inputs[1])

    lum = _math(ng, "ADD", "(R+G)+B")
    lum.location = (120, 0)
    links.new(add_rg.outputs[0], lum.inputs[0])
    links.new(mb.outputs[0], lum.inputs[1])

    # Remap:
    # t = (lum - low) / max(high-low, eps)
    # t = clamp(t, 0, 1) using MAXIMUM + MINIMUM (no CLAMP op needed)
    num = _math(ng, "SUBTRACT", "lum-low")
    num.location = (320, 60)
    links.new(lum.outputs[0], num.inputs[0])
    links.new(gin.outputs["Ramp Low"], num.inputs[1])

    denom = _math(ng, "SUBTRACT", "high-low")
    denom.location = (320, -80)
    links.new(gin.outputs["Ramp High"], denom.inputs[0])
    links.new(gin.outputs["Ramp Low"], denom.inputs[1])

    denom_safe = _math(ng, "MAXIMUM", "max(denom, eps)")
    denom_safe.location = (520, -80)
    links.new(denom.outputs[0], denom_safe.inputs[0])
    denom_safe.inputs[1].default_value = 1e-6

    div = _math(ng, "DIVIDE", "t")
    div.location = (520, 60)
    links.new(num.outputs[0], div.inputs[0])
    links.new(denom_safe.outputs[0], div.inputs[1])

    max0 = _math(ng, "MAXIMUM", "max(t,0)")
    max0.location = (720, 60)
    links.new(div.outputs[0], max0.inputs[0])
    max0.inputs[1].default_value = 0.0

    min1 = _math(ng, "MINIMUM", "min(t,1)")
    min1.location = (920, 60)
    links.new(max0.outputs[0], min1.inputs[0])
    min1.inputs[1].default_value = 1.0

    links.new(min1.outputs[0], gout.inputs["Mask"])

    return ng


def add_paint_mask_node(
    nt,
    mask_def: PaintMask,
    *,
    obj: bpy.types.Object,
    group_name: str = "TerrainPaintMask",
) -> tuple[MaskSocket, list[Node]]:
    _ensure_uv_map(obj, mask_def.uv_map_name)
    img = _ensure_paint_image(
        mask_def.image_name,
        width=mask_def.width,
        height=mask_def.height,
        use_alpha=mask_def.alpha,
    )

    mask_group = bpy.data.node_groups.get(group_name)
    if mask_group is None or not _group_has_io(
        mask_group,
        ins=["UV", "Image", "Ramp Low", "Ramp High"],
        outs=["Mask"],
    ):
        mask_group = create_paint_mask_group(group_name)

    nodes, links = nt.nodes, nt.links

    uv_attr = nodes.new("GeometryNodeInputNamedAttribute")
    uv_attr.data_type = "FLOAT_VECTOR"
    uv_attr.inputs["Name"].default_value = mask_def.uv_map_name
    uv_attr.label = f"UV: {mask_def.uv_map_name}"

    group_node = nodes.new("GeometryNodeGroup")
    group_node.node_tree = mask_group
    group_node.label = f"Mask: Paint ({mask_def.image_name})"

    links.new(
        uv_attr.outputs.get("Attribute") or uv_attr.outputs[0], group_node.inputs["UV"]
    )

    # image + params
    try:
        group_node.inputs["Image"].default_value = img  # type: ignore[attr-defined]
    except Exception:
        pass
    group_node.inputs["Ramp Low"].default_value = float(mask_def.ramp_low)
    group_node.inputs["Ramp High"].default_value = float(mask_def.ramp_high)

    # sampling settings (best effort)
    try:
        for n in mask_group.nodes:
            if n.bl_idname == "GeometryNodeImageTexture":
                try:
                    if hasattr(n, "interpolation"):
                        n.interpolation = str(mask_def.interpolation)
                except Exception:
                    pass
                try:
                    if hasattr(n, "extension"):
                        n.extension = str(mask_def.extension)
                except Exception:
                    pass
                break
    except Exception:
        pass

    return group_node.outputs["Mask"], [uv_attr, group_node]
