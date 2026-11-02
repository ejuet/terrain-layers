from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pydantic import Field
from terrain_layers.masks.mask_types import Mask
from terrain_layers.masks.noise_types import MaskNoiseConfig
from terrain_layers.shader.material_types import PBRMaterialSource
from terrain_layers.tunnels.tunnel_types import TunnelSystem


class PreviewLayerColor(str, Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"
    CYAN = "cyan"
    MAGENTA = "magenta"
    ORANGE = "orange"
    LIME = "lime"
    TEAL = "teal"
    PINK = "pink"
    VIOLET = "violet"
    GOLD = "gold"
    BROWN = "brown"
    WHITE = "white"


@dataclass(frozen=True, slots=True)
class ScatterBiome:
    id: str = Field(description="Unique identifier used to associate this biome with footprint masks.")
    eligibility_layer_name: str = Field(description="Name of the terrain layer whose mask determines where instances may appear.")
    collection_name: str = Field(description="Name of the Blender collection containing objects to scatter.")
    density: float = Field(default=0.03, description="Average number of scatter instances per square Blender unit in eligible areas.")
    seed: int = Field(default=0, description="Random seed used to place and choose scatter instances reproducibly.")
    scale_min: float = Field(default=0.9, description="Smallest random uniform scale applied to an instance.")
    scale_max: float = Field(default=1.3, description="Largest random uniform scale applied to an instance.")
    keep_upright: bool = Field(default=False, description="Keep instances aligned with world up instead of tilting them to the terrain surface.")


@dataclass(frozen=True, slots=True)
class Layer:
    name: str = Field(description="Unique name for this terrain layer.")
    priority: int = Field(default=0, description="Order used when layers overlap; higher-priority layers take precedence.")
    strength: float = Field(default=1.0, description="Multiplier applied to the layer mask before terrain blending.")
    mask: Mask | None = Field(default=None, description="Rule used to generate this layer's terrain mask.")
    mask_noise: Optional[MaskNoiseConfig] = Field(default=None, description="Optional procedural noise used to vary the generated mask.")
    pbr_source: Optional[PBRMaterialSource] = Field(default=None, description="Material source supplying the layer's PBR texture maps.")
    preview_color: Optional[PreviewLayerColor] = Field(default=None, description="Color used for this layer in the generated preview shader.")


@dataclass(frozen=True, slots=True)
class TerrainConfig:
    object_name: Optional[str] = Field(default=None, description="Name of the Blender terrain object; uses the active object when omitted.")
    path_deformation_modifier_name: str = Field(default="Terrain_Path_Deformation", description="Name used for the road-terrain deformation setup.")
    tunnel_system_modifier_name: str = Field(default="Terrain_Tunnel_System", description="Name used for the tunnel and cave setup.")
    geometry_modifier_name: str = Field(default="Terrain_Layer_Masks", description="Name used for the terrain-layer mask setup.")
    shader_name: str = Field(default="Terrain_Layered_Shader", description="Name assigned to the generated layered terrain material.")
    preview_shader_name: str = Field(default="Terrain_Layer_Preview_Shader", description="Name assigned to the generated color-coded layer preview material.")
    tunnel_system: Optional[TunnelSystem] = Field(default=None, description="Optional tunnel and cave excavation configuration.")
    layers: list[Layer] = Field(default_factory=list, description="Terrain layers to mask and blend.")
    scatter_biomes: list[ScatterBiome] = Field(default_factory=list, description="Object-scattering biomes placed according to terrain-layer masks.")
