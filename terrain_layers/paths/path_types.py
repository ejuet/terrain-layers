from dataclasses import dataclass
from pydantic import Field


@dataclass(frozen=True, slots=True)
class DeformationSettings:
    enabled: bool = Field(default=False, description="Whether terrain geometry is deformed beneath this path.")
    width: float | None = Field(default=None, description="Width of the deformed path area; inherits the path-mask width when omitted.")
    falloff: float | None = Field(default=None, description="Distance beyond the path width over which deformation fades out; inherits the path-mask falloff when omitted.")
    sample_count: int | None = Field(default=None, description="Number of points used along each path segment; inherits the path-mask value when omitted.")
    ray_length: float | None = Field(default=None, description="Maximum distance used to find the terrain surface below each path point; inherits the path-mask value when omitted.")
    strength: float = Field(default=1.0, description="Multiplier for the calculated vertical terrain displacement.")
    vertical_offset: float = Field(default=0.0, description="Vertical offset added to the road's terrain deformation.")
