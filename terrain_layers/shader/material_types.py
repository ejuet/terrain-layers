from dataclasses import dataclass
from typing import Optional
import math
from terrain_layers.masks.noise import DualNoiseConfig


@dataclass(frozen=True, slots=True)
class UVWarpConfig:
    amount: float = 0.08
    dual_noise: DualNoiseConfig = DualNoiseConfig()


@dataclass(frozen=True, slots=True)
class UVAntiTilingConfig:
    blend: float = 1.0
    angle: float = math.radians(60)
    offset: tuple[float, float, float] = (0.37, 0.11, 0.0)
    dual_noise: DualNoiseConfig = DualNoiseConfig()


@dataclass(frozen=True, slots=True)
class GroundMaterial:
    material_name: str  # Material to take textures from
    uv_scale: float = 1.0
    uv_warp: Optional[UVWarpConfig] = None
    uv_anti_tiling: Optional[UVAntiTilingConfig] = None
