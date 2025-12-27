import bpy
from config.config_types import TerrainConfig, Layer
from shader.material_types import GroundMaterial
from shader.get_texture_image import get_material_pbr_images
from utility.geo_nodes import active_mesh_object


UV_MAP_NAME = "UV_TERRAIN_TILING"


def _ensure_material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    return mat


def _clear_node_tree(nt: bpy.types.NodeTree) -> None:
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    for l in list(nt.links):
        nt.links.remove(l)


def _new_image_tex(
    nt: bpy.types.NodeTree,
    image: bpy.types.Image | None,
    label: str,
    x: float,
    y: float,
) -> bpy.types.ShaderNodeTexImage | None:
    if image is None:
        return None
    n = nt.nodes.new("ShaderNodeTexImage")
    n.label = label
    n.name = f"IMG_{label}"
    n.image = image
    n.interpolation = "Smart"
    n.extension = "REPEAT"
    n.location = (x, y)
    return n


def _layer_shader_block(
    nt: bpy.types.NodeTree,
    layer: Layer,
    x: float,
    y: float,
):
    """
    Returns:
        shader_socket: output shader socket for the layer
        disp_socket:   float socket for displacement height (may be None)
    """
    imgs = get_material_pbr_images(layer.ground_material.material_name)

    # UV -> Mapping (per-layer scale)
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = UV_MAP_NAME
    uv.location = (x, y + 220)

    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    mapping.location = (x + 220, y + 220)

    uv_scale = getattr(layer.ground_material, "uv_scale", 1.0) or 1.0
    mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, uv_scale)

    nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])

    # Principled
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.label = layer.name
    bsdf.location = (x + 920, y)

    # Base Color
    base = _new_image_tex(
        nt, imgs.base_color, f"{layer.name}_BaseColor", x + 460, y + 260
    )
    if base:
        base.image.colorspace_settings.name = "sRGB"
        nt.links.new(mapping.outputs["Vector"], base.inputs["Vector"])
        nt.links.new(base.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness
    rough = _new_image_tex(
        nt, imgs.roughness, f"{layer.name}_Roughness", x + 460, y + 60
    )
    if rough:
        rough.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mapping.outputs["Vector"], rough.inputs["Vector"])
        nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    # Normal
    normal_tex = _new_image_tex(
        nt, imgs.normal, f"{layer.name}_Normal", x + 460, y - 140
    )
    if normal_tex:
        normal_tex.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mapping.outputs["Vector"], normal_tex.inputs["Vector"])

        normal_map = nt.nodes.new("ShaderNodeNormalMap")
        normal_map.location = (x + 700, y - 140)
        nt.links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        nt.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    # Displacement (height)
    disp_socket = None
    disp_tex = _new_image_tex(
        nt, imgs.displacement, f"{layer.name}_Displacement", x + 460, y - 360
    )
    if disp_tex:
        disp_tex.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mapping.outputs["Vector"], disp_tex.inputs["Vector"])
        # use the value output if present; otherwise convert from color with RGB to BW
        if "Value" in disp_tex.outputs:
            disp_socket = disp_tex.outputs["Value"]
        else:
            rgb2bw = nt.nodes.new("ShaderNodeRGBToBW")
            rgb2bw.location = (x + 700, y - 360)
            nt.links.new(disp_tex.outputs["Color"], rgb2bw.inputs["Color"])
            disp_socket = rgb2bw.outputs["Val"]

    return bsdf.outputs["BSDF"], disp_socket


def create_terrain_shader(config: TerrainConfig):
    print("Creating shader...")

    obj = active_mesh_object()
    if obj is None or obj.type != "MESH":
        raise RuntimeError("No active mesh object found.")

    mat = _ensure_material(config.shader_name)
    nt = mat.node_tree
    _clear_node_tree(nt)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (2200, 0)

    # Start with a default "empty" base in case first mask is sparse
    base_bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    base_bsdf.label = "Base_Fallback"
    base_bsdf.location = (1200, -500)

    current_shader = base_bsdf.outputs["BSDF"]

    # We'll also build a mixed displacement chain (float height),
    # then feed it through a Displacement node to the output.
    current_disp = None

    # Create one Displacement node for the material output (Cycles will use it).
    disp_node = nt.nodes.new("ShaderNodeDisplacement")
    disp_node.location = (1900, -600)
    # sensible defaults; you can tune as needed
    disp_node.inputs["Scale"].default_value = 0.1
    disp_node.inputs["Midlevel"].default_value = 0.5

    # Build layers bottom -> top (later layers overwrite where their mask is 1)
    x0, y0 = 0.0, 500.0
    y_step = -520.0

    for i, layer in enumerate(config.layers):
        ly = y0 + i * y_step

        layer_shader, layer_disp = _layer_shader_block(nt, layer, x0, ly)

        # Attribute mask by layer name (0..1)
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = layer.name
        attr.location = (x0 + 0, ly - 120)

        # Mix shader: fac = attribute
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.label = f"MIX_{layer.name}"
        mix.location = (x0 + 1500, ly)

        nt.links.new(current_shader, mix.inputs[1])
        nt.links.new(layer_shader, mix.inputs[2])

        # Prefer Fac output if present; otherwise use Color -> BW
        if "Fac" in attr.outputs:
            nt.links.new(attr.outputs["Fac"], mix.inputs["Fac"])
            mask_socket = attr.outputs["Fac"]
        else:
            rgb2bw = nt.nodes.new("ShaderNodeRGBToBW")
            rgb2bw.location = (x0 + 250, ly - 120)
            nt.links.new(attr.outputs["Color"], rgb2bw.inputs["Color"])
            nt.links.new(rgb2bw.outputs["Val"], mix.inputs["Fac"])
            mask_socket = rgb2bw.outputs["Val"]

        current_shader = mix.outputs["Shader"]

        # Mix displacement heights (float) using the same mask
        if layer_disp is not None:
            if current_disp is None:
                current_disp = layer_disp
            else:
                mixh = nt.nodes.new("ShaderNodeMix")
                mixh.data_type = "FLOAT"
                mixh.label = f"MIXH_{layer.name}"
                mixh.location = (x0 + 1500, ly - 240)

                # Mix: A=previous, B=this layer, Factor=mask
                nt.links.new(mask_socket, mixh.inputs["Factor"])
                nt.links.new(current_disp, mixh.inputs["A"])
                nt.links.new(layer_disp, mixh.inputs["B"])
                current_disp = mixh.outputs["Result"]

    # Hook up surface
    nt.links.new(current_shader, out.inputs["Surface"])

    # Hook up displacement if we built any
    if current_disp is not None:
        nt.links.new(current_disp, disp_node.inputs["Height"])
        nt.links.new(disp_node.outputs["Displacement"], out.inputs["Displacement"])

    # Assign material to active object
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    print(f"Done. Assigned material '{mat.name}' to '{obj.name}'.")


def run():
    config = TerrainConfig(
        shader_name="Terrain_Layered_Shader",
        layers=[
            Layer(
                name="Underwater",
                ground_material=GroundMaterial("Muddy ground with underwater moss"),
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
