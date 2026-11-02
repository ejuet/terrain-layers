from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, Optional, TypeAlias
import math
from pydantic import Field
from terrain_layers.masks.noise import DualNoiseConfig

if TYPE_CHECKING:
    from terrain_layers.shader.get_texture_image import MaterialPBRImages


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
class PBRSourceMaterial:
    """Read PBR maps from a named Blender material's node tree."""

    material_name: str
    uv_scale: float = 1.0
    uv_warp: Optional[UVWarpConfig] = None
    uv_anti_tiling: Optional[UVAntiTilingConfig] = None
    type: Literal["source_material"] = "source_material"

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

    base_color: str | None = None
    roughness: str | None = None
    normal: str | None = None
    displacement: str | None = None
    uv_scale: float = 1.0
    uv_warp: Optional[UVWarpConfig] = None
    uv_anti_tiling: Optional[UVAntiTilingConfig] = None
    name: str = "PBR Texture Set"
    type: Literal["texture_set"] = "texture_set"

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
