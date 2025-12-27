from config.config_types import (
    TerrainConfig,
    Layer,
)
from masks.mask_types.height import HeightMask
from masks.mask_types.slope import SlopeMask
from masks.mask_types.paint import PaintMask
from masks.noise import DualNoiseConfig, MaskNoiseConfig

from masks.create_layer_masks import create_terrain_layers

from shader.create_shader import create_terrain_shader


def run():
    # Two dual noise configs: default and an alternate for "Rock"
    dual_default = DualNoiseConfig(
        scale=6.0, large_scale=1.5, large_mix=0.35, detail=1.0
    )
    dual_alt = DualNoiseConfig(scale=10.0, large_scale=2.2, large_mix=0.55, detail=0.8)

    config = TerrainConfig(
        geometry_modifier_name="Terrain_Layer_Masks",
        layers=[
            Layer(name="Underwater", priority=0, strength=1.0),
            Layer(
                name="Beach",
                priority=10,
                strength=1.0,
                mask=HeightMask(
                    min_height=1.5,
                    max_height=7.5,
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
            ),
            Layer(
                name="Sand Painted",
                priority=20,
                strength=1.0,
                mask=PaintMask(
                    image_name="IMG_Terrain_SandPaint",
                    uv_map_name="UV_TerrainPaint",
                    width=2048,
                    height=2048,
                    alpha=True,
                    ramp_low=0.0,
                    ramp_high=1.0,
                    interpolation="Linear",
                    extension="CLIP",
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
            ),
            Layer(
                name="Rock",
                priority=25,
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
            ),
            Layer(
                name="Snow",
                priority=30,
                strength=1.0,
                mask=HeightMask(
                    min_height=9.0,
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
            ),
        ],
    )

    create_terrain_layers(config)
    create_terrain_shader(config)
