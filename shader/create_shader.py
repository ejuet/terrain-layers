import bpy
import math

from config.config_types import TerrainConfig, Layer
from shader.material_types import GroundMaterial, UVWarpConfig, UVAntiTilingConfig
from shader.get_texture_image import get_material_pbr_images
from utility.geo_nodes import active_mesh_object
from shader.anti_repetition.uv_warp import ensure_pbr_warped_uv_group
from shader.anti_repetition.anti_tile import ensure_pbr_antitile_uvb_fac_group
from masks.mask_types.paint import PaintMask
from shader.anti_repetition.uv_noise import get_or_create_shared_dual_noise_node


# ---------------------------------------------------------------------------
# Small utilities (local replacements for the helpers used in your old script)
# ---------------------------------------------------------------------------


def _safe_key(s: str) -> str:
    s = (s or "").strip()
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in s) or "Layer"


def _add_socket(
    ng: bpy.types.NodeTree,
    *,
    in_out: str,
    name: str,
    socket_type: str,
    default=None,
    min_val=None,
    max_val=None,
):
    if in_out.upper() == "INPUT":
        sock = ng.interface.new_socket(
            name=name, in_out="INPUT", socket_type=socket_type
        )
    else:
        sock = ng.interface.new_socket(
            name=name, in_out="OUTPUT", socket_type=socket_type
        )

    # Best-effort defaults/ranges (Blender’s API differs a bit across versions)
    if default is not None:
        try:
            sock.default_value = default
        except Exception:
            pass
    if min_val is not None:
        try:
            sock.min_value = min_val
        except Exception:
            pass
    if max_val is not None:
        try:
            sock.max_value = max_val
        except Exception:
            pass
    return sock


def _frame_nodes(nt_or_ng: bpy.types.NodeTree, title: str, nodes_list):
    if not nodes_list:
        return None
    frame = nt_or_ng.nodes.new("NodeFrame")
    frame.label = title
    # Place frame roughly around nodes; parent them
    for n in nodes_list:
        try:
            n.parent = frame
        except Exception:
            pass
    return frame


def _rebuild_group_if_missing_inputs(
    group_name: str, required_inputs: set[str], build_fn
):
    ng = bpy.data.node_groups.get(group_name)
    if ng is None or ng.bl_idname != "ShaderNodeTree":
        return build_fn()

    # Build a quick set of current input names
    existing = set()
    try:
        for item in ng.interface.items_tree:
            if getattr(item, "in_out", "") == "INPUT":
                existing.add(item.name)
    except Exception:
        # Fallback (older Blender)
        existing = {s.name for s in getattr(ng, "inputs", [])}

    if not required_inputs.issubset(existing):
        # Rebuild (delete old, make new)
        try:
            bpy.data.node_groups.remove(ng)
        except Exception:
            pass
        return build_fn()

    return ng


# ---------------------------------------------------------
# Mix Terrain Layer Group (same structure as your old script)
# ---------------------------------------------------------


def _make_mix_terrain_layer_group(group_name="NG_MixTerrainLayer"):
    ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gin.location = (-680, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (520, 0)

    _add_socket(
        ng,
        in_out="INPUT",
        name="Mask",
        socket_type="NodeSocketFloat",
        default=0.0,
        min_val=0.0,
        max_val=1.0,
    )

    _add_socket(ng, in_out="INPUT", name="A Base Color", socket_type="NodeSocketColor")
    _add_socket(ng, in_out="INPUT", name="B Base Color", socket_type="NodeSocketColor")
    _add_socket(ng, in_out="INPUT", name="A Roughness", socket_type="NodeSocketFloat")
    _add_socket(ng, in_out="INPUT", name="B Roughness", socket_type="NodeSocketFloat")
    _add_socket(ng, in_out="INPUT", name="A Normal", socket_type="NodeSocketVector")
    _add_socket(ng, in_out="INPUT", name="B Normal", socket_type="NodeSocketVector")
    _add_socket(ng, in_out="INPUT", name="A Height", socket_type="NodeSocketFloat")
    _add_socket(ng, in_out="INPUT", name="B Height", socket_type="NodeSocketFloat")

    _add_socket(ng, in_out="OUTPUT", name="Base Color", socket_type="NodeSocketColor")
    _add_socket(ng, in_out="OUTPUT", name="Roughness", socket_type="NodeSocketFloat")
    _add_socket(ng, in_out="OUTPUT", name="Normal", socket_type="NodeSocketVector")
    _add_socket(ng, in_out="OUTPUT", name="Height", socket_type="NodeSocketFloat")

    mix_bc = nodes.new("ShaderNodeMixRGB")
    mix_bc.location = (-180, 220)
    mix_bc.blend_type = "MIX"
    links.new(gin.outputs["Mask"], mix_bc.inputs["Fac"])
    links.new(gin.outputs["A Base Color"], mix_bc.inputs["Color1"])
    links.new(gin.outputs["B Base Color"], mix_bc.inputs["Color2"])
    links.new(mix_bc.outputs["Color"], gout.inputs["Base Color"])

    mix_r = nodes.new("ShaderNodeMix")
    mix_r.location = (-180, 60)
    mix_r.data_type = "FLOAT"
    links.new(gin.outputs["Mask"], mix_r.inputs["Factor"])
    links.new(gin.outputs["A Roughness"], mix_r.inputs["A"])
    links.new(gin.outputs["B Roughness"], mix_r.inputs["B"])
    links.new(mix_r.outputs["Result"], gout.inputs["Roughness"])

    mix_n = nodes.new("ShaderNodeMix")
    mix_n.location = (-180, -100)
    mix_n.data_type = "VECTOR"
    links.new(gin.outputs["Mask"], mix_n.inputs["Factor"])
    links.new(gin.outputs["A Normal"], mix_n.inputs["A"])
    links.new(gin.outputs["B Normal"], mix_n.inputs["B"])
    links.new(mix_n.outputs["Result"], gout.inputs["Normal"])

    mix_h = nodes.new("ShaderNodeMix")
    mix_h.location = (-180, -260)
    mix_h.data_type = "FLOAT"
    links.new(gin.outputs["Mask"], mix_h.inputs["Factor"])
    links.new(gin.outputs["A Height"], mix_h.inputs["A"])
    links.new(gin.outputs["B Height"], mix_h.inputs["B"])
    links.new(mix_h.outputs["Result"], gout.inputs["Height"])

    return ng


def _ensure_mix_terrain_layer_group():
    required = {
        "Mask",
        "A Base Color",
        "B Base Color",
        "A Roughness",
        "B Roughness",
        "A Normal",
        "B Normal",
        "A Height",
        "B Height",
    }
    return _rebuild_group_if_missing_inputs(
        "NG_MixTerrainLayer",
        required,
        lambda: _make_mix_terrain_layer_group("NG_MixTerrainLayer"),
    )


# -----------------------------------------
# PBR Layer Group (one group per layer key)
# -----------------------------------------


def _make_pbr_layer_group(
    layer_key: str,
    ground_mat: GroundMaterial,
    group_prefix="NG_PBRLayer_",
):
    images = get_material_pbr_images(ground_mat.material_name)

    build_warp = ground_mat.uv_warp is not None
    build_antitile = ground_mat.uv_anti_tiling is not None

    safe = _safe_key(layer_key)
    group_name = f"{group_prefix}{safe}_warp{build_warp}_antitile{build_antitile}_v01"

    def _build():
        ng = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
        nodes, links = ng.nodes, ng.links
        nodes.clear()

        gin = nodes.new("NodeGroupInput")
        gin.location = (-900, 0)
        gout = nodes.new("NodeGroupOutput")
        gout.location = (650, 0)

        # Inputs (same semantics as your old group)
        _add_socket(
            ng,
            in_out="INPUT",
            name="Vector",
            socket_type="NodeSocketVector",
            default=(0.0, 0.0, 0.0),
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="UV Scale",
            socket_type="NodeSocketFloat",
            default=1.0,
            min_val=0.0,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="Normal Strength",
            socket_type="NodeSocketFloat",
            default=1.0,
            min_val=0.0,
        )

        _add_socket(
            ng,
            in_out="INPUT",
            name="Warp Noise Centered",
            socket_type="NodeSocketFloat",
            default=0.0,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="UV Warp Amount",
            socket_type="NodeSocketFloat",
            default=0.0,
            min_val=0.0,
            max_val=1.0,
        )

        _add_socket(
            ng,
            in_out="INPUT",
            name="AntiTile Noise Centered",
            socket_type="NodeSocketFloat",
            default=0.0,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="AntiTile Enable",
            socket_type="NodeSocketFloat",
            default=0.0,
            min_val=0.0,
            max_val=1.0,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="AntiTile Blend",
            socket_type="NodeSocketFloat",
            default=1.0,
            min_val=0.0,
            max_val=1.0,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="AntiTile Angle",
            socket_type="NodeSocketFloat",
            default=math.radians(60.0),
            min_val=-math.pi,
            max_val=math.pi,
        )
        _add_socket(
            ng,
            in_out="INPUT",
            name="AntiTile Offset",
            socket_type="NodeSocketVector",
            default=(0.37, 0.11, 0.0),
        )

        # Outputs
        _add_socket(
            ng, in_out="OUTPUT", name="Base Color", socket_type="NodeSocketColor"
        )
        _add_socket(
            ng, in_out="OUTPUT", name="Roughness", socket_type="NodeSocketFloat"
        )
        _add_socket(ng, in_out="OUTPUT", name="Normal", socket_type="NodeSocketVector")
        _add_socket(ng, in_out="OUTPUT", name="Height", socket_type="NodeSocketFloat")

        # --- helpers ---
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
            m.label = "Layer UV Scale"
            c = nodes.new("ShaderNodeCombineXYZ")
            links.new(vec_socket, m.inputs["Vector"])
            links.new(scale_socket, c.inputs["X"])
            links.new(scale_socket, c.inputs["Y"])
            links.new(scale_socket, c.inputs["Z"])
            links.new(c.outputs["Vector"], m.inputs["Scale"])
            return m.outputs["Vector"], [m, c]

        frames = []

        # --- Vector path (warp or not) ---
        if build_warp:
            g_warp = nodes.new("ShaderNodeGroup")
            g_warp.node_tree = ensure_pbr_warped_uv_group()
            g_warp.label = "Warped UV"
            g_warp.location = (-560, 280)

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
            ns[0].location = (-580, 280)
            ns[1].location = (-760, 160)
            frames.append(("uv (no warp)", ns))

        # --- Base Color (antitile or not) ---
        tex_a = tex_img("Base Color", images.base_color, "sRGB", vec)
        tex_a.location = (-260, 420)

        if build_antitile:
            g_at = nodes.new("ShaderNodeGroup")
            g_at.node_tree = ensure_pbr_antitile_uvb_fac_group()
            g_at.label = "AntiTile UVB+Fac"
            g_at.location = (-260, 220)

            links.new(vec, g_at.inputs["Warped Vector"])
            links.new(
                gin.outputs["AntiTile Noise Centered"],
                g_at.inputs["AntiTile Noise Centered"],
            )
            links.new(gin.outputs["AntiTile Enable"], g_at.inputs["AntiTile Enable"])
            links.new(gin.outputs["AntiTile Blend"], g_at.inputs["AntiTile Blend"])
            links.new(gin.outputs["AntiTile Angle"], g_at.inputs["AntiTile Angle"])
            links.new(gin.outputs["AntiTile Offset"], g_at.inputs["AntiTile Offset"])

            tex_b = tex_img(
                "Base Color B", images.base_color, "sRGB", g_at.outputs["UV B"]
            )
            tex_b.location = (-20, 260)

            mix_bc = nodes.new("ShaderNodeMixRGB")
            mix_bc.blend_type = "MIX"
            mix_bc.location = (240, 380)
            links.new(g_at.outputs["Fac"], mix_bc.inputs["Fac"])
            links.new(tex_a.outputs["Color"], mix_bc.inputs["Color1"])
            links.new(tex_b.outputs["Color"], mix_bc.inputs["Color2"])

            base_color_out = mix_bc.outputs["Color"]
            frames.append(("anti-tiling", [g_at, tex_b, mix_bc]))
        else:
            base_color_out = tex_a.outputs["Color"]

        # --- Remaining maps (always single sample) ---
        tex_r = tex_img("Roughness", images.roughness, "Non-Color", vec)
        tex_n = tex_img("Normal", images.normal, "Non-Color", vec)
        tex_h = tex_img("Height", images.displacement, "Non-Color", vec)

        tex_r.location = (-260, 40)
        tex_n.location = (-260, -120)
        tex_h.location = (-260, -280)

        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (240, -90)
        links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
        links.new(gin.outputs["Normal Strength"], nmap.inputs["Strength"])

        # Outputs
        links.new(base_color_out, gout.inputs["Base Color"])
        links.new(tex_r.outputs["Color"], gout.inputs["Roughness"])
        links.new(nmap.outputs["Normal"], gout.inputs["Normal"])
        links.new(tex_h.outputs["Color"], gout.inputs["Height"])

        # Frames
        for title, ns in frames:
            _frame_nodes(ng, title, ns)
        _frame_nodes(ng, "Textures", [n for n in (tex_a, tex_r, tex_n, tex_h) if n])

        return ng

    required_inputs = {
        "Vector",
        "UV Scale",
        "Normal Strength",
        "Warp Noise Centered",
        "UV Warp Amount",
        "AntiTile Noise Centered",
        "AntiTile Enable",
        "AntiTile Blend",
        "AntiTile Angle",
        "AntiTile Offset",
    }
    return _rebuild_group_if_missing_inputs(group_name, required_inputs, _build)


# -----------------------------
# Terrain Shader Builder
# -----------------------------


def create_terrain_shader(config: TerrainConfig):
    print("Creating shader...")

    if not config.layers or len(config.layers) < 1:
        raise ValueError("TerrainConfig.layers must contain at least 1 layer.")

    obj = active_mesh_object()
    if not obj or obj.type != "MESH":
        raise ValueError("Active object must be a mesh.")

    # Create / reuse material
    mat = bpy.data.materials.get(config.shader_name) or bpy.data.materials.new(
        config.shader_name
    )
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    # Output + BSDF
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (1200, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (950, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # UV map for PBR tiling
    uv_tiling = nodes.new("ShaderNodeUVMap")
    uv_tiling.location = (-1650, -220)
    uv_tiling.uv_map = "UV_TERRAIN_TILING"
    uv_tiling.label = "UV Map: UV_TERRAIN_TILING (PBR)"

    # Mapping (global), per-layer scaling happens in the layer group (UV Scale)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-1350, -220)
    mapping.label = "Base Mapping"
    links.new(uv_tiling.outputs["UV"], mapping.inputs["Vector"])

    # (Optional) create paint UV nodes for layers that were painted (for parity / easy debugging)
    paint_uv_nodes_by_name: dict[str, bpy.types.Node] = {}
    paint_uv_y = -520
    for layer in config.layers:
        m = getattr(layer, "mask", None)
        if isinstance(m, PaintMask):
            uv_name = m.uv_map_name
            if uv_name not in paint_uv_nodes_by_name:
                u = nodes.new("ShaderNodeUVMap")
                u.location = (-1650, paint_uv_y)
                u.uv_map = uv_name
                u.label = f"UV Map: {uv_name} (PAINT)"
                paint_uv_nodes_by_name[uv_name] = u
                paint_uv_y -= 180

    # Build per-layer PBR group nodes
    layer_nodes: list[bpy.types.Node] = []
    layer_frames: list[bpy.types.Node | None] = []

    for i, layer in enumerate(config.layers):
        g = nodes.new("ShaderNodeGroup")
        g.node_tree = _make_pbr_layer_group(layer.name, layer.ground_material)
        g.label = f"Layer: {layer.name}"
        g.location = (-900, 520 - i * 260)

        # Vector input from mapping
        links.new(mapping.outputs["Vector"], g.inputs["Vector"])

        # Per-layer UV scale
        g.inputs["UV Scale"].default_value = float(
            getattr(layer.ground_material, "uv_scale", 1.0)
        )

        # Normal strength (keep as 1.0 unless you add it to your config)
        g.inputs["Normal Strength"].default_value = 1.0

        # Warp / antitile defaults and shared dual-noise hookups
        uvw = layer.ground_material.uv_warp
        if uvw is not None:
            g.inputs["UV Warp Amount"].default_value = float(uvw.amount)

            # Dual noise (cached per node-tree+params by your helper)
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
        layer_frames.append(_frame_nodes(nt, f"Layer {layer.name}", [g]))

    # Mix stack (same approach as your old script, but masks come from attributes per layer name)
    ng_mix = _ensure_mix_terrain_layer_group()

    cur = {
        "Base Color": layer_nodes[0].outputs["Base Color"],
        "Roughness": layer_nodes[0].outputs["Roughness"],
        "Normal": layer_nodes[0].outputs["Normal"],
        "Height": layer_nodes[0].outputs["Height"],
    }

    mix_x = -350
    start_y = 340
    step_y = -260

    for i in range(1, len(layer_nodes)):
        layer = config.layers[i]

        # Attribute mask (0..1) stored under the layer name
        attr = nodes.new("ShaderNodeAttribute")
        attr.location = (mix_x - 520, start_y + (i - 1) * step_y - 80)
        attr.attribute_name = layer.name
        attr.label = f"Mask Attr: {layer.name}"

        clamp = nodes.new("ShaderNodeClamp")
        clamp.location = (mix_x - 330, start_y + (i - 1) * step_y - 80)
        clamp.inputs["Min"].default_value = 0.0
        clamp.inputs["Max"].default_value = 1.0
        links.new(attr.outputs.get("Fac") or attr.outputs[2], clamp.inputs["Value"])

        # (Optional) If the mask was painted, keep the paint UV node near it for debugging parity.
        m = getattr(layer, "mask", None)
        if isinstance(m, PaintMask):
            uv_node = paint_uv_nodes_by_name.get(m.uv_map_name)
            if uv_node:
                # visually cluster (no link needed since mask is already baked into attribute)
                pass

        mix = nodes.new("ShaderNodeGroup")
        mix.node_tree = ng_mix
        mix.label = f"Mix (-> {layer.name})"
        mix.location = (mix_x, start_y + (i - 1) * step_y)

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

        # Frame masks with that layer
        fr = layer_frames[i]
        if fr:
            try:
                attr.parent = fr
                clamp.parent = fr
                mix.parent = fr
            except Exception:
                pass

    # Normalize final normal and plug everything into BSDF
    norm = nodes.new("ShaderNodeVectorMath")
    norm.operation = "NORMALIZE"
    norm.label = "Normalize Normal"
    norm.location = (720, -140)
    links.new(cur["Normal"], norm.inputs[0])

    links.new(cur["Base Color"], bsdf.inputs["Base Color"])
    links.new(cur["Roughness"], bsdf.inputs["Roughness"])
    links.new(norm.outputs["Vector"], bsdf.inputs["Normal"])

    # Displacement (height)
    disp = nodes.new("ShaderNodeDisplacement")
    disp.label = "Displacement"
    disp.location = (950, -360)
    disp.inputs["Scale"].default_value = 0.10
    disp.inputs["Midlevel"].default_value = 0.50
    links.new(cur["Height"], disp.inputs["Height"])
    links.new(disp.outputs["Displacement"], out.inputs["Displacement"])

    # Assign to active object
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    return mat


# -----------------------------
# Run (your example)
# -----------------------------
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
            Layer(
                name="Beach",
                ground_material=GroundMaterial("Sand"),
            ),
            Layer(
                name="Sand Painted",
                ground_material=GroundMaterial("Sand"),
            ),
            Layer(
                name="Grass",
                ground_material=GroundMaterial("Grass"),
            ),
            Layer(
                name="Rock",
                ground_material=GroundMaterial("Rock"),
            ),
            Layer(
                name="Snow",
                ground_material=GroundMaterial("Snow"),
            ),
        ],
    )

    create_terrain_shader(config)
