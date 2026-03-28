from dataclasses import dataclass, field
from typing import Optional
from masks.mask_types import Mask
from masks.noise import MaskNoiseConfig
from shader.material_types import GroundMaterial


@dataclass(frozen=True, slots=True)
class ScatterBiome:
    collection_name: str
    density: float = 0.03
    seed: int = 0
    scale_min: float = 0.9
    scale_max: float = 1.3


@dataclass(frozen=True, slots=True)
class Layer:
    name: str
    priority: int = 0
    strength: float = 1.0
    mask: Mask | None = None
    mask_noise: Optional[MaskNoiseConfig] = None
    ground_material: Optional[GroundMaterial] = None
    scatter_biome: Optional[ScatterBiome] = None


@dataclass(frozen=True, slots=True)
class TerrainConfig:
    object_name: Optional[str] = None
    geometry_modifier_name: str = "Terrain_Layer_Masks"
    scatter_modifier_name: str = "Terrain_Scatter_Biomes"
    shader_name: str = "Terrain_Layered_Shader"
    layers: list[Layer] = field(default_factory=list)
