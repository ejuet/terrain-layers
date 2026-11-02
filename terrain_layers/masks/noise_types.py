"""Blender-independent terrain mask noise configuration."""

from dataclasses import dataclass
from pydantic import Field


@dataclass(frozen=True, slots=True)
class DualNoiseConfig:
    """Parameters for one reusable dual-noise sampler."""

    scale: float = Field(default=6.0, description="Scale of the primary noise pattern.")
    large_scale: float = Field(default=1.5, description="Scale of the secondary, broader noise pattern.")
    large_mix: float = Field(default=0.35, description="Blend weight of the broader noise pattern.")
    detail: float = Field(default=1.0, description="Detail level of both noise patterns.")


@dataclass(frozen=True, slots=True)
class MaskNoiseConfig:
    """Parameters for applying a dual-noise sampler to one mask."""

    dual: DualNoiseConfig = Field(default_factory=DualNoiseConfig, description="Dual-noise sampler used to perturb the mask.")
    amount: float = Field(default=2.8, description="Strength of the noise perturbation applied to the mask.")
    sharpness: float = Field(default=1.8, description="Contrast applied to the noise before it affects the mask.")
    bias: float = Field(default=0.0, description="Offset applied to the noise contribution.")
    zone_width: float = Field(default=0.5, description="Width of the mask-value band centered at 0.5 that receives noise.")
    zone_softness: float = Field(default=1.0, description="Softness of the transition at the edges of the noise-affected band.")
