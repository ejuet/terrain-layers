"""JSON loading and schema generation for terrain configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from terrain_layers.config.config_types import TerrainConfig


_TERRAIN_CONFIG_ADAPTER = TypeAdapter(TerrainConfig)


def load_terrain_config(path: str | Path) -> TerrainConfig:
    """Load and validate a terrain configuration JSON file."""
    config_path = Path(path)
    try:
        return _TERRAIN_CONFIG_ADAPTER.validate_json(config_path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Invalid terrain config '{config_path}': {error}") from error


def terrain_config_json_schema() -> dict[str, Any]:
    """Return the JSON Schema describing the supported terrain config format."""
    return _TERRAIN_CONFIG_ADAPTER.json_schema()
