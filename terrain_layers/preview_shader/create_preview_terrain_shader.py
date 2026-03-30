import bpy
from array import array

from terrain_layers.config.config_types import Layer, PreviewLayerColor, TerrainConfig
from terrain_layers.shader.get_texture_image import get_material_image_for_property
from terrain_layers.utility.geo_nodes import get_terrain_object

_PREVIEW_COLOR_VALUES: dict[PreviewLayerColor, tuple[float, float, float, float]] = {
    PreviewLayerColor.RED: (0.92, 0.20, 0.16, 1.0),
    PreviewLayerColor.GREEN: (0.18, 0.72, 0.22, 1.0),
    PreviewLayerColor.BLUE: (0.18, 0.40, 0.92, 1.0),
    PreviewLayerColor.YELLOW: (0.97, 0.84, 0.16, 1.0),
    PreviewLayerColor.CYAN: (0.10, 0.80, 0.88, 1.0),
    PreviewLayerColor.MAGENTA: (0.88, 0.20, 0.72, 1.0),
    PreviewLayerColor.ORANGE: (0.95, 0.49, 0.12, 1.0),
    PreviewLayerColor.LIME: (0.63, 0.86, 0.16, 1.0),
    PreviewLayerColor.TEAL: (0.10, 0.60, 0.53, 1.0),
    PreviewLayerColor.PINK: (0.95, 0.45, 0.67, 1.0),
    PreviewLayerColor.VIOLET: (0.50, 0.29, 0.83, 1.0),
    PreviewLayerColor.GOLD: (0.85, 0.65, 0.13, 1.0),
    PreviewLayerColor.BROWN: (0.55, 0.35, 0.20, 1.0),
    PreviewLayerColor.WHITE: (0.92, 0.92, 0.92, 1.0),
}

_MATERIAL_PREVIEW_COLOR_CACHE: dict[str, tuple[float, float, float, float]] = {}


def _resolve_preview_color(color: PreviewLayerColor | str) -> PreviewLayerColor:
    if isinstance(color, PreviewLayerColor):
        return color

    normalized = str(color).strip().lower()
    for option in PreviewLayerColor:
        if option.value == normalized:
            return option

    raise ValueError(
        f"Unsupported preview color '{color}'. Use one of: "
        + ", ".join(option.value for option in PreviewLayerColor)
    )


def _average_image_color(
    image: bpy.types.Image, sample_size: int = 32
) -> tuple[float, float, float, float]:
    if image.size[0] <= 0 or image.size[1] <= 0:
        raise ValueError(f"Image '{image.name}' has invalid size.")

    temp_image = image.copy()
    try:
        temp_image.scale(sample_size, sample_size)
        pixel_buffer = array("f", [0.0]) * (sample_size * sample_size * 4)
        temp_image.pixels.foreach_get(pixel_buffer)

        pixel_count = sample_size * sample_size
        if pixel_count <= 0:
            raise ValueError(f"Image '{image.name}' has no readable pixels.")

        r_total = 0.0
        g_total = 0.0
        b_total = 0.0
        a_total = 0.0

        for pixel_index in range(pixel_count):
            base = pixel_index * 4
            r_total += float(pixel_buffer[base])
            g_total += float(pixel_buffer[base + 1])
            b_total += float(pixel_buffer[base + 2])
            a_total += float(pixel_buffer[base + 3])

        return (
            r_total / pixel_count,
            g_total / pixel_count,
            b_total / pixel_count,
            a_total / pixel_count,
        )
    finally:
        bpy.data.images.remove(temp_image)


def _get_layer_preview_color(layer: Layer) -> tuple[float, float, float, float]:
    if layer.preview_color is not None:
        chosen = _resolve_preview_color(layer.preview_color)
        return _PREVIEW_COLOR_VALUES[chosen]

    if layer.ground_material is None:
        raise ValueError(
            f"Layer '{layer.name}' has no preview_color and no GroundMaterial to sample."
        )

    material_name = layer.ground_material.material_name
    cached_color = _MATERIAL_PREVIEW_COLOR_CACHE.get(material_name)
    if cached_color is not None:
        return cached_color

    image = get_material_image_for_property(
        material_name,
        "base_color",
    )
    if image is None:
        raise ValueError(
            f"Layer '{layer.name}' has no preview_color and material "
            f"'{material_name}' has no base color image."
        )

    average_color = _average_image_color(image)
    _MATERIAL_PREVIEW_COLOR_CACHE[material_name] = average_color
    return average_color


def _choose_layer_colors(
    layers: list[Layer],
) -> list[tuple[float, float, float, float]]:
    return [_get_layer_preview_color(layer) for layer in layers]


def create_preview_terrain_shader(config: TerrainConfig):
    """
    Create a simple preview shader that visualizes the terrain layers in solid mode.
    Turn down Levels_Viewport on the multires modifier of the terrain when editing paths for less lagging.
    """
    if not config.layers:
        raise ValueError("TerrainConfig.layers must contain at least 1 layer.")

    obj = get_terrain_object(config.object_name)
    if not obj or obj.type != "MESH":
        raise ValueError("Active object must be a mesh.")

    mat = bpy.data.materials.get(config.preview_shader_name) or bpy.data.materials.new(
        config.preview_shader_name
    )
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    links.new(diffuse.outputs["BSDF"], out.inputs["Surface"])

    layer_colors = _choose_layer_colors(config.layers)

    first_color = nodes.new("ShaderNodeRGB")
    first_color.label = f"Preview Color: {config.layers[0].name}"
    first_color.outputs["Color"].default_value = layer_colors[0]
    current_color = first_color.outputs["Color"]

    for index in range(1, len(config.layers)):
        layer = config.layers[index]

        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = layer.name
        attr.label = f"Mask Attr: {layer.name}"

        clamp = nodes.new("ShaderNodeClamp")
        clamp.inputs["Min"].default_value = 0.0
        clamp.inputs["Max"].default_value = 1.0
        links.new(attr.outputs.get("Fac") or attr.outputs[2], clamp.inputs["Value"])

        color_node = nodes.new("ShaderNodeRGB")
        color_node.label = f"Preview Color: {layer.name}"
        color_node.outputs["Color"].default_value = layer_colors[index]

        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        links.new(clamp.outputs["Result"], mix.inputs["Fac"])
        links.new(current_color, mix.inputs["Color1"])
        links.new(color_node.outputs["Color"], mix.inputs["Color2"])

        current_color = mix.outputs["Color"]

    links.new(current_color, diffuse.inputs["Color"])

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    return mat
