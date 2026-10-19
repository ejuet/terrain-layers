from terrain_layers.config.config_types import Layer, TerrainConfig


def sort_layers_by_priority(layers: list[Layer]) -> list[Layer]:
    """
    Returns layers sorted by priority DESC (higher priority first).
    Stable for equal priorities: earlier items in the config win ties.
    """
    indexed = list(enumerate(layers))

    def key(item: tuple[int, Layer]) -> tuple[int, int]:
        idx, layer = item
        # sort by prio DESC, then idx ASC (stable tiebreak)
        return (-int(layer.priority), idx)

    indexed.sort(key=key)
    return [layer for _, layer in indexed]


def validate_terrain_config(config: TerrainConfig) -> None:
    """Validate identifiers and cross-references needed by the terrain graph."""
    layer_names = [layer.name for layer in config.layers]
    duplicate_layers = sorted({name for name in layer_names if layer_names.count(name) > 1})
    if duplicate_layers:
        raise ValueError(f"Layer names must be unique: {', '.join(duplicate_layers)}.")

    biome_ids = [biome.id for biome in config.scatter_biomes]
    duplicate_biomes = sorted({biome_id for biome_id in biome_ids if biome_ids.count(biome_id) > 1})
    if duplicate_biomes:
        raise ValueError(
            f"Scatter biome IDs must be unique: {', '.join(duplicate_biomes)}."
        )

    known_layers = set(layer_names)
    for biome in config.scatter_biomes:
        if biome.eligibility_layer_name not in known_layers:
            raise ValueError(
                f"Scatter biome '{biome.id}' references unknown eligibility layer "
                f"'{biome.eligibility_layer_name}'."
            )
