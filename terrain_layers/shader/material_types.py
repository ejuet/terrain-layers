from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, Optional, TypeAlias
import math
from pydantic import Field
from terrain_layers.masks.noise_types import DualNoiseConfig

if TYPE_CHECKING:
    from terrain_layers.shader.get_texture_image import MaterialPBRImages


@dataclass(frozen=True, slots=True)
class UVWarpConfig:
    amount: float = Field(default=0.08, description="Strength of the noise-driven UV-coordinate distortion.")
    dual_noise: DualNoiseConfig = Field(default_factory=DualNoiseConfig, description="Noise settings that control the UV distortion.")


@dataclass(frozen=True, slots=True)
class UVAntiTilingConfig:
    blend: float = Field(default=1.0, description="Strength of the anti-tiling effect.")
    angle: float = Field(default=math.radians(60), description="Rotation angle, in radians, between anti-tiling texture variants.")
    offset: tuple[float, float, float] = Field(default=(0.37, 0.11, 0.0), description="XYZ coordinate offset used to decorrelate anti-tiling texture variants.")
    dual_noise: DualNoiseConfig = Field(default_factory=DualNoiseConfig, description="Noise settings that vary the anti-tiling effect.")


@dataclass(frozen=True, slots=True)
class PBRSourceMaterial:
    """Read PBR maps from a named Blender material's node tree."""

    material_name: str = Field(description="Name of the Blender material used to provide the PBR maps.")
    uv_scale: float = Field(default=1.0, description="Multiplier for the material's texture coordinates.")
    uv_warp: Optional[UVWarpConfig] = Field(default=None, description="Optional noise-based UV distortion used before sampling textures.")
    uv_anti_tiling: Optional[UVAntiTilingConfig] = Field(default=None, description="Optional stochastic UV treatment that reduces visible texture repetition.")
    type: Literal["source_material"] = Field(
        default="source_material", description="PBR material-source variant identifier."
    )

    @property
    def display_name(self) -> str:
        return self.material_name

    def resolve_images(self) -> "MaterialPBRImages":
        # Kept local so this configuration module stays independent of the
        # node-graph inspection implementation.
        from terrain_layers.shader.get_texture_image import get_material_pbr_images

        return get_material_pbr_images(self.material_name)


@dataclass(frozen=True, slots=True)
class PBRTextureSet:
    """Load PBR image maps directly from disk when the shader is built.

    Paths may be absolute or Blender-relative (``//``). They are resolved with
    :func:`bpy.path.abspath`, so they do not depend on Blender's process CWD.
    """

    base_color: str | None = Field(default=None, description="Path to the base-color image map.")
    roughness: str | None = Field(default=None, description="Path to the roughness image map.")
    normal: str | None = Field(default=None, description="Path to the tangent-space normal image map.")
    displacement: str | None = Field(default=None, description="Path to the displacement or height image map.")
    uv_scale: float = Field(default=1.0, description="Multiplier for the texture coordinates used to sample all maps.")
    uv_warp: Optional[UVWarpConfig] = Field(default=None, description="Optional noise-based UV distortion used before sampling textures.")
    uv_anti_tiling: Optional[UVAntiTilingConfig] = Field(default=None, description="Optional stochastic UV treatment that reduces visible texture repetition.")
    name: str = Field(default="PBR Texture Set", description="Human-readable name shown for this texture set.")
    type: Literal["texture_set"] = Field(
        default="texture_set", description="PBR material-source variant identifier."
    )

    @property
    def display_name(self) -> str:
        return self.name

    def resolve_images(self) -> "MaterialPBRImages":
        from terrain_layers.shader.get_texture_image import load_pbr_texture_set

        return load_pbr_texture_set(
            base_color=self.base_color,
            roughness=self.roughness,
            normal=self.normal,
            displacement=self.displacement,
        )


# Keep this a concrete union rather than a Protocol: configuration loaders need
# to know which class to instantiate from JSON.
PBRMaterialSource: TypeAlias = Annotated[
    PBRSourceMaterial | PBRTextureSet,
    Field(discriminator="type"),
]
