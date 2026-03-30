from terrain_layers.config.config_types import (
    TerrainConfig,
    Layer,
    PreviewLayerColor,
    ScatterBiome,
)
from terrain_layers.masks.mask_types.height import HeightMask
from terrain_layers.masks.mask_types.slope import SlopeMask
from terrain_layers.masks.mask_types.paint import PaintMask
from terrain_layers.masks.mask_types.path import (
    RoadNetworkMask,
    RoadNetworkPath,
    RoadPathSettings,
    RoadPathSettingsOverride,
)
from terrain_layers.paths.path_deformation import (
    DeformationSettings,
    create_path_deformation,
)
from terrain_layers.masks.noise import DualNoiseConfig, MaskNoiseConfig

from terrain_layers.masks.create_layer_masks import create_terrain_layers
from terrain_layers.biomes.create_scatter_biomes import create_scatter_biomes

from terrain_layers.shader.create_shader import create_terrain_shader
from terrain_layers.shader.material_types import (
    GroundMaterial,
    UVWarpConfig,
    UVAntiTilingConfig,
)

from terrain_layers.preview_shader.create_preview_terrain_shader import (
    create_preview_terrain_shader,
)


def run():
    # Two dual noise configs: default and an alternate for "Rock"
    dual_default = DualNoiseConfig(
        scale=6.0, large_scale=1.5, large_mix=0.35, detail=1.0
    )
    dual_alt = DualNoiseConfig(scale=10.0, large_scale=2.2, large_mix=0.55, detail=0.8)

    config = TerrainConfig(
        object_name="UV_TERRAIN_TILING",
        geometry_modifier_name="Terrain_Layer_Masks",
        scatter_modifier_name="Terrain_Scatter_Biomes",
        preview_shader_name="Terrain_Layer_Preview_Shader",
        layers=[
            Layer(
                name="Underwater",
                priority=0,
                strength=1.0,
                preview_color=PreviewLayerColor.BLUE,
                ground_material=GroundMaterial(
                    "Muddy ground with underwater moss",
                    uv_scale=2.0,
                    uv_warp=UVWarpConfig(),
                    uv_anti_tiling=UVAntiTilingConfig(),
                ),
            ),
            Layer(
                name="Beach",
                priority=10,
                strength=1.0,
                mask=HeightMask(
                    min_height=1.0,
                    max_height=6.5,
                    ramp_low=0.35,
                    ramp_high=0.55,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,
                    amount=2.0,
                    sharpness=1.6,
                    bias=0.0,
                    zone_width=0.35,
                    zone_softness=1.0,
                ),
                ground_material=GroundMaterial("Sand"),
                scatter_biome=ScatterBiome(
                    collection_name="Beach_Objects",
                    density=0.02,
                    seed=15,
                    scale_min=0.9,
                    scale_max=1.35,
                ),
            ),
            Layer(
                name="Grass",
                priority=20,
                strength=1.0,
                mask=HeightMask(
                    min_height=3.5,
                    max_height=8.0,
                    ramp_low=0.45,
                    ramp_high=0.65,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,  # reuses the same stored dual noise as Beach
                    amount=1.8,
                    sharpness=1.8,
                    bias=0.0,
                    zone_width=0.5,
                    zone_softness=1.0,
                ),
                ground_material=GroundMaterial("Grass"),
                scatter_biome=ScatterBiome(
                    collection_name="Forest_Trees",
                    density=0.02,
                    seed=13,
                    scale_min=0.9,
                    scale_max=1.35,
                ),
            ),
            Layer(
                name="Snow",
                priority=25,
                strength=1.0,
                mask=HeightMask(
                    min_height=11.0,
                    max_height=15.0,
                    ramp_low=0.45,
                    ramp_high=0.65,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_default,  # reuses default dual noise
                    amount=1.2,
                    sharpness=2.2,
                    bias=0.0,
                    zone_width=0.3,
                    zone_softness=1.2,
                ),
                ground_material=GroundMaterial("Snow"),
            ),
            Layer(
                name="Rock",
                priority=27,
                strength=1.0,
                mask=SlopeMask(
                    min_angle=25.0,
                    max_angle=60.0,
                    ramp_low=0.4,
                    ramp_high=0.6,
                ),
                mask_noise=MaskNoiseConfig(
                    dual=dual_alt,  # different dual noise => second stored attribute
                    amount=2.2,
                    sharpness=2.0,
                    bias=0.0,
                    zone_width=0.4,
                    zone_softness=1.0,
                ),
                ground_material=GroundMaterial("Rock"),
            ),
            Layer(
                name="Volcanos",
                priority=30,
                strength=1.0,
                mask=PaintMask(
                    image_name="IMG_Terrain_VolcanosMask",
                ),
                ground_material=GroundMaterial("04 Vulcanic Rock Surface D"),
            ),
            Layer(
                name="Roads",
                priority=40,
                strength=1.0,
                mask=RoadNetworkMask(
                    path_settings=RoadPathSettings(
                        width=1.25,
                        falloff=0.0,
                        ramp_low=0.0,
                        ramp_high=0.2,
                        deformation_settings=DeformationSettings(
                            enabled=True,
                            width=2.5,
                            falloff=3.0,
                            strength=0.85,
                        ),
                    ),
                    paths=[
                        RoadNetworkPath(path_collection_name="Path_Network"),
                        RoadNetworkPath(
                            path_object_name="MainRoad",
                            path_settings=RoadPathSettingsOverride(
                                width=2.0,
                            ),
                        ),
                    ],
                ),
                ground_material=GroundMaterial("Sand"),
            ),
        ],
    )

    create_path_deformation(config)
    create_terrain_layers(config)
    create_scatter_biomes(config)
    create_terrain_shader(config)
    create_preview_terrain_shader(config)
