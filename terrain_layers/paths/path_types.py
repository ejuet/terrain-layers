from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeformationSettings:
    enabled: bool = False
    width: float | None = None
    falloff: float | None = None
    sample_count: int | None = None
    ray_length: float | None = None
    strength: float = 1.0
    vertical_offset: float = 0.0
