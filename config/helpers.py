from config.config_types import Layer, TerrainConfig


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
