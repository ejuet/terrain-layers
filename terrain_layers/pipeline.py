from pathlib import Path

from terrain_layers.biomes.create_scatter_biomes import validate_scatter_collections
from terrain_layers.config.config_types import TerrainConfig
from terrain_layers.config.helpers import validate_terrain_config
from terrain_layers.config.json_io import load_terrain_config
from terrain_layers.masks.create_layer_masks import create_terrain_layers
from terrain_layers.paths.path_deformation import create_path_deformation
from terrain_layers.preview_shader.create_preview_terrain_shader import (
    create_preview_terrain_shader,
)
from terrain_layers.shader.create_shader import create_terrain_shader
from terrain_layers.tunnels import create_tunnel_system


DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.json")


def build(config: TerrainConfig) -> None:
    """Validate and build all terrain-layer data from a typed configuration."""
    validate_terrain_config(config)
    validate_scatter_collections(config.scatter_biomes)
    create_path_deformation(config)
    create_tunnel_system(config)
    create_terrain_layers(config)
    create_terrain_shader(config)
    create_preview_terrain_shader(config)


def run(config_path: str | Path | None = None) -> None:
    """Build terrain from ``config_path`` or the bundled default configuration."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    build(load_terrain_config(path))
