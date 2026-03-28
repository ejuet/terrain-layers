import bpy
import math

from config.config_types import TerrainConfig, Layer
from shader.material_types import GroundMaterial, UVWarpConfig, UVAntiTilingConfig
from shader.get_texture_image import get_material_pbr_images
from utility.geo_nodes import get_terrain_object
from shader.anti_repetition.uv_warp import ensure_pbr_warped_uv_group
from shader.anti_repetition.anti_tile import ensure_pbr_antitile_uvb_fac_group
from masks.mask_types.paint import PaintMask
from shader.anti_repetition.uv_noise import get_or_create_shared_dual_noise_node
from utility.frame_nodes import frame_nodes


def _safe_key(s: str) -> str:
    s = (s or "").strip()
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in s) or "Layer"


def _make_mix_terrain_layer_group(name="NG_MixTerrainLayer"):
    ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    # sockets (no helpers / no rebuild checks)
    ng.interface.new_socket("Mask", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        "A Base Color", in_out="INPUT", socket_type="NodeSocketColor"
    )
    ng.interface.new_socket(
        "B Base Color", in_out="INPUT", socket_type="NodeSocketColor"
    )
    ng.interface.new_socket(
        "A Roughness", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "B Roughness", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket("A Normal", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("B Normal", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("A Height", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("B Height", in_out="INPUT", socket_type="NodeSocketFloat")

    ng.interface.new_socket(
        "Base Color", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    ng.interface.new_socket("Roughness", in_out="OUTPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Normal", in_out="OUTPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("Height", in_out="OUTPUT", socket_type="NodeSocketFloat")

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    mix_bc = nodes.new("ShaderNodeMixRGB")
    mix_bc.blend_type = "MIX"
    links.new(gin.outputs["Mask"], mix_bc.inputs["Fac"])
    links.new(gin.outputs["A Base Color"], mix_bc.inputs["Color1"])
    links.new(gin.outputs["B Base Color"], mix_bc.inputs["Color2"])
    links.new(mix_bc.outputs["Color"], gout.inputs["Base Color"])

    mix_r = nodes.new("ShaderNodeMix")
    mix_r.data_type = "FLOAT"
    links.new(gin.outputs["Mask"], mix_r.inputs["Factor"])
    links.new(gin.outputs["A Roughness"], mix_r.inputs["A"])
    links.new(gin.outputs["B Roughness"], mix_r.inputs["B"])
    links.new(mix_r.outputs["Result"], gout.inputs["Roughness"])

    mix_n = nodes.new("ShaderNodeMix")
    mix_n.data_type = "VECTOR"
    links.new(gin.outputs["Mask"], mix_n.inputs["Factor"])
    links.new(gin.outputs["A Normal"], mix_n.inputs["A"])
    links.new(gin.outputs["B Normal"], mix_n.inputs["B"])
    links.new(mix_n.outputs["Result"], gout.inputs["Normal"])

    mix_h = nodes.new("ShaderNodeMix")
    mix_h.data_type = "FLOAT"
    links.new(gin.outputs["Mask"], mix_h.inputs["Factor"])
    links.new(gin.outputs["A Height"], mix_h.inputs["A"])
    links.new(gin.outputs["B Height"], mix_h.inputs["B"])
    links.new(mix_h.outputs["Result"], gout.inputs["Height"])

    return ng


def _make_pbr_layer_group(
    layer_key: str, ground_mat: GroundMaterial, group_prefix="NG_PBRLayer_"
):
    images = get_material_pbr_images(ground_mat.material_name)
    build_warp = ground_mat.uv_warp is not None
    build_antitile = ground_mat.uv_anti_tiling is not None
    name = f"{group_prefix}{_safe_key(layer_key)}_warp{build_warp}_antitile{build_antitile}_v01"

    ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    # sockets (no helpers / no rebuild checks)
    ng.interface.new_socket("Vector", in_out="INPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("UV Scale", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket(
        "Normal Strength", in_out="INPUT", socket_type="NodeSocketFloat"
    )

    ng.interface.new_socket(
        "Warp Noise Centered", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "UV Warp Amount", in_out="INPUT", socket_type="NodeSocketFloat"
    )

    ng.interface.new_socket(
        "AntiTile Noise Centered", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "AntiTile Enable", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "AntiTile Blend", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "AntiTile Angle", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    ng.interface.new_socket(
        "AntiTile Offset", in_out="INPUT", socket_type="NodeSocketVector"
    )

    ng.interface.new_socket(
        "Base Color", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    ng.interface.new_socket("Roughness", in_out="OUTPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Normal", in_out="OUTPUT", socket_type="NodeSocketVector")
    ng.interface.new_socket("Height", in_out="OUTPUT", socket_type="NodeSocketFloat")

    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    def tex_img(label, img, colorspace, vec_socket):
        n = nodes.new("ShaderNodeTexImage")
        n.label = label
        n.name = label
        n.interpolation = "Linear"
        n.image = img
        if img:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        links.new(vec_socket, n.inputs["Vector"])
        return n

    def scale_vec(vec_socket, scale_socket):
        m = nodes.new("ShaderNodeMapping")
        c = nodes.new("ShaderNodeCombineXYZ")
        links.new(vec_socket, m.inputs["Vector"])
        links.new(scale_socket, c.inputs["X"])
        links.new(scale_socket, c.inputs["Y"])
        links.new(scale_socket, c.inputs["Z"])
        links.new(c.outputs["Vector"], m.inputs["Scale"])
        return m.outputs["Vector"], (m, c)

    frames = []

    if build_warp:
        g_warp = nodes.new("ShaderNodeGroup")
        g_warp.node_tree = ensure_pbr_warped_uv_group()
        g_warp.label = "Warped UV"
        links.new(gin.outputs["Vector"], g_warp.inputs["Vector"])
        links.new(gin.outputs["UV Scale"], g_warp.inputs["UV Scale"])
        links.new(
            gin.outputs["Warp Noise Centered"], g_warp.inputs["Warp Noise Centered"]
        )
        links.new(gin.outputs["UV Warp Amount"], g_warp.inputs["UV Warp Amount"])
        vec = g_warp.outputs.get("Warped Vector") or g_warp.outputs[0]
        frames.append(("uv warping", [g_warp]))
    else:
        vec, ns = scale_vec(gin.outputs["Vector"], gin.outputs["UV Scale"])
        frames.append(("uv (no warp)", list(ns)))

    tex_a = tex_img("Base Color", images.base_color, "sRGB", vec)

    if build_antitile:
        g_at = nodes.new("ShaderNodeGroup")
        g_at.node_tree = ensure_pbr_antitile_uvb_fac_group()
        g_at.label = "AntiTile UVB+Fac"
        links.new(vec, g_at.inputs["Warped Vector"])
        links.new(
            gin.outputs["AntiTile Noise Centered"],
            g_at.inputs["AntiTile Noise Centered"],
        )
        links.new(gin.outputs["AntiTile Enable"], g_at.inputs["AntiTile Enable"])
        links.new(gin.outputs["AntiTile Blend"], g_at.inputs["AntiTile Blend"])
        links.new(gin.outputs["AntiTile Angle"], g_at.inputs["AntiTile Angle"])
        links.new(gin.outputs["AntiTile Offset"], g_at.inputs["AntiTile Offset"])

        tex_b = tex_img("Base Color B", images.base_color, "sRGB", g_at.outputs["UV B"])

        mix_bc = nodes.new("ShaderNodeMixRGB")
        mix_bc.blend_type = "MIX"
        links.new(g_at.outputs["Fac"], mix_bc.inputs["Fac"])
        links.new(tex_a.outputs["Color"], mix_bc.inputs["Color1"])
        links.new(tex_b.outputs["Color"], mix_bc.inputs["Color2"])
        base_color_out = mix_bc.outputs["Color"]
        frames.append(("anti-tiling", [g_at, tex_b, mix_bc]))
    else:
        base_color_out = tex_a.outputs["Color"]

    tex_r = tex_img("Roughness", images.roughness, "Non-Color", vec)
    tex_n = tex_img("Normal", images.normal, "Non-Color", vec)
    tex_h = tex_img("Height", images.displacement, "Non-Color", vec)

    nmap = nodes.new("ShaderNodeNormalMap")
    links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
    links.new(gin.outputs["Normal Strength"], nmap.inputs["Strength"])

    links.new(base_color_out, gout.inputs["Base Color"])
    links.new(tex_r.outputs["Color"], gout.inputs["Roughness"])
    links.new(nmap.outputs["Normal"], gout.inputs["Normal"])
    links.new(tex_h.outputs["Color"], gout.inputs["Height"])

    for title, ns in frames:
        frame_nodes(ng, title, ns)
    frame_nodes(ng, "Textures", [n for n in (tex_a, tex_r, tex_n, tex_h) if n])

    return ng


def create_terrain_shader(config: TerrainConfig):
    if not config.layers:
        raise ValueError("TerrainConfig.layers must contain at least 1 layer.")

    obj = get_terrain_object(config.object_name)
    if not obj or obj.type != "MESH":
        raise ValueError("Active object must be a mesh.")

    mat = bpy.data.materials.get(config.shader_name) or bpy.data.materials.new(
        config.shader_name
    )
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    uv_tiling = nodes.new("ShaderNodeUVMap")
    uv_tiling.uv_map = "UV_TERRAIN_TILING"
    uv_tiling.label = "UV Map: UV_TERRAIN_TILING (PBR)"

    mapping = nodes.new("ShaderNodeMapping")
    mapping.label = "Base Mapping"
    links.new(uv_tiling.outputs["UV"], mapping.inputs["Vector"])

    paint_uv_nodes_by_name: dict[str, bpy.types.Node] = {}
    for layer in config.layers:
        m = getattr(layer, "mask", None)
        if isinstance(m, PaintMask):
            uv_name = m.uv_map_name
            if uv_name not in paint_uv_nodes_by_name:
                u = nodes.new("ShaderNodeUVMap")
                u.uv_map = uv_name
                u.label = f"UV Map: {uv_name} (PAINT)"
                paint_uv_nodes_by_name[uv_name] = u

    layer_nodes: list[bpy.types.Node] = []
    layer_frames: list[bpy.types.Node | None] = []

    for layer in config.layers:
        if layer.ground_material is None:
            continue

        g = nodes.new("ShaderNodeGroup")
        g.node_tree = _make_pbr_layer_group(layer.name, layer.ground_material)
        g.label = f"Layer: {layer.name}"

        links.new(mapping.outputs["Vector"], g.inputs["Vector"])
        g.inputs["UV Scale"].default_value = float(
            getattr(layer.ground_material, "uv_scale", 1.0)
        )
        g.inputs["Normal Strength"].default_value = 1.0

        uvw = layer.ground_material.uv_warp
        if uvw is not None:
            g.inputs["UV Warp Amount"].default_value = float(uvw.amount)
            dn = uvw.dual_noise
            warp_noise = get_or_create_shared_dual_noise_node(
                nt,
                mapping_node=mapping,
                scale=float(getattr(dn, "scale", 0.35)),
                large_scale=float(getattr(dn, "large_scale", 0.12)),
                large_mix=float(getattr(dn, "large_mix", 0.35)),
                detail=float(getattr(dn, "detail", 1.0)),
            )
            links.new(warp_noise, g.inputs["Warp Noise Centered"])
        else:
            g.inputs["UV Warp Amount"].default_value = 0.0

        at = layer.ground_material.uv_anti_tiling
        if at is not None:
            g.inputs["AntiTile Enable"].default_value = 1.0
            g.inputs["AntiTile Blend"].default_value = float(at.blend)
            g.inputs["AntiTile Angle"].default_value = float(at.angle)
            g.inputs["AntiTile Offset"].default_value = tuple(at.offset)

            dn = at.dual_noise
            at_noise = get_or_create_shared_dual_noise_node(
                nt,
                mapping_node=mapping,
                scale=float(getattr(dn, "scale", 0.22)),
                large_scale=float(getattr(dn, "large_scale", 0.08)),
                large_mix=float(getattr(dn, "large_mix", 0.35)),
                detail=float(getattr(dn, "detail", 1.0)),
            )
            links.new(at_noise, g.inputs["AntiTile Noise Centered"])
        else:
            g.inputs["AntiTile Enable"].default_value = 0.0
            g.inputs["AntiTile Blend"].default_value = 1.0
            g.inputs["AntiTile Angle"].default_value = math.radians(60.0)
            g.inputs["AntiTile Offset"].default_value = (0.37, 0.11, 0.0)

        layer_nodes.append(g)
        layer_frames.append(frame_nodes(nt, f"Layer {layer.name}", [g]))

    if not layer_nodes:
        raise ValueError("No layers had a GroundMaterial.")

    ng_mix = bpy.data.node_groups.get(
        "NG_MixTerrainLayer"
    ) or _make_mix_terrain_layer_group("NG_MixTerrainLayer")

    cur = {
        "Base Color": layer_nodes[0].outputs["Base Color"],
        "Roughness": layer_nodes[0].outputs["Roughness"],
        "Normal": layer_nodes[0].outputs["Normal"],
        "Height": layer_nodes[0].outputs["Height"],
    }

    for i in range(1, len(layer_nodes)):
        layer = config.layers[i]

        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = layer.name
        attr.label = f"Mask Attr: {layer.name}"

        clamp = nodes.new("ShaderNodeClamp")
        clamp.inputs["Min"].default_value = 0.0
        clamp.inputs["Max"].default_value = 1.0
        links.new(attr.outputs.get("Fac") or attr.outputs[2], clamp.inputs["Value"])

        m = getattr(layer, "mask", None)
        if isinstance(m, PaintMask):
            _ = paint_uv_nodes_by_name.get(m.uv_map_name)

        mix = nodes.new("ShaderNodeGroup")
        mix.node_tree = ng_mix
        mix.label = f"Mix (-> {layer.name})"

        links.new(clamp.outputs["Result"], mix.inputs["Mask"])

        links.new(cur["Base Color"], mix.inputs["A Base Color"])
        links.new(layer_nodes[i].outputs["Base Color"], mix.inputs["B Base Color"])

        links.new(cur["Roughness"], mix.inputs["A Roughness"])
        links.new(layer_nodes[i].outputs["Roughness"], mix.inputs["B Roughness"])

        links.new(cur["Normal"], mix.inputs["A Normal"])
        links.new(layer_nodes[i].outputs["Normal"], mix.inputs["B Normal"])

        links.new(cur["Height"], mix.inputs["A Height"])
        links.new(layer_nodes[i].outputs["Height"], mix.inputs["B Height"])

        cur["Base Color"] = mix.outputs["Base Color"]
        cur["Roughness"] = mix.outputs["Roughness"]
        cur["Normal"] = mix.outputs["Normal"]
        cur["Height"] = mix.outputs["Height"]

        fr = layer_frames[i]
        if fr:
            try:
                attr.parent = fr
                clamp.parent = fr
                mix.parent = fr
            except Exception:
                pass

    norm = nodes.new("ShaderNodeVectorMath")
    norm.operation = "NORMALIZE"
    norm.label = "Normalize Normal"
    links.new(cur["Normal"], norm.inputs[0])

    links.new(cur["Base Color"], bsdf.inputs["Base Color"])
    links.new(cur["Roughness"], bsdf.inputs["Roughness"])
    links.new(norm.outputs["Vector"], bsdf.inputs["Normal"])

    disp = nodes.new("ShaderNodeDisplacement")
    disp.label = "Displacement"
    disp.inputs["Scale"].default_value = 0.10
    disp.inputs["Midlevel"].default_value = 0.50
    links.new(cur["Height"], disp.inputs["Height"])
    links.new(disp.outputs["Displacement"], out.inputs["Displacement"])

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    return mat


def run():
    config = TerrainConfig(
        shader_name="Terrain_Layered_Shader",
        layers=[
            Layer(
                name="Underwater",
                ground_material=GroundMaterial(
                    "Muddy ground with underwater moss",
                    uv_scale=2.0,
                    uv_warp=UVWarpConfig(),
                    uv_anti_tiling=UVAntiTilingConfig(),
                ),
            ),
            Layer(name="Beach", ground_material=GroundMaterial("Sand")),
            Layer(name="Sand Painted", ground_material=GroundMaterial("Sand")),
            Layer(name="Grass", ground_material=GroundMaterial("Grass")),
            Layer(name="Rock", ground_material=GroundMaterial("Rock")),
            Layer(name="Snow", ground_material=GroundMaterial("Snow")),
        ],
    )
    create_terrain_shader(config)
