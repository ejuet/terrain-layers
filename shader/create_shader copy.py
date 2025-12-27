from config.config_types import TerrainConfig, Layer
from shader.material_types import GroundMaterial
from shader.get_texture_image import get_material_pbr_images
import bpy
from utility.geo_nodes import active_mesh_object

"""
you can assume that for each layer, an attribute exists with the layer's name
that contains a mask value from 0.0 to 1.0
where the material should be placed.
"""

"""
@dataclass(frozen=True, slots=True)
class GroundMaterial:
    material_name: str  # Material to take textures from
    uv_scale: float = 1.0
"""

"""
you can use the following function to get the image textures:
@dataclass(frozen=True, slots=True)
class MaterialPBRImages:
    base_color: Optional[bpy.types.Image]
    roughness: Optional[bpy.types.Image]
    normal: Optional[bpy.types.Image]
    displacement: Optional[bpy.types.Image]


def get_material_pbr_images(
    material_name: str
) -> MaterialPBRImages:
...
"""


def create_terrain_shader(config: TerrainConfig):
    print("Creating shader...")


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
