"""Blender-independent terrain mask noise configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DualNoiseConfig:
    """Parameters for one reusable dual-noise sampler."""

    scale: float = 6.0
    large_scale: float = 1.5
    large_mix: float = 0.35
    detail: float = 1.0


@dataclass(frozen=True, slots=True)
class MaskNoiseConfig:
    """Parameters for applying a dual-noise sampler to one mask."""

    dual: DualNoiseConfig = DualNoiseConfig()
    amount: float = 2.8
    sharpness: float = 1.8
    bias: float = 0.0
    zone_width: float = 0.5
    zone_softness: float = 1.0
