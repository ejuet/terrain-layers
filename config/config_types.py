from dataclasses import dataclass, field
from typing import Literal, Optional
from masks.mask_types import Mask
from masks.noise import MaskNoiseConfig


@dataclass(frozen=True, slots=True)
class Layer:
    name: str
    priority: int = 0
    strength: float = 1.0
    mask: Mask | None = None
    mask_noise: Optional[MaskNoiseConfig] = None


@dataclass(frozen=True, slots=True)
class TerrainConfig:
    geometry_modifier_name: str = "Terrain_Layer_Masks"
    layers: list[Layer] = field(default_factory=list)
