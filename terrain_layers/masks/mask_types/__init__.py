from typing import Annotated, Union
from pydantic import Field
from .height import HeightMask
from .slope import SlopeMask
from .paint import PaintMask
from .path import RoadNetworkMask
from .scatter_footprint import ScatterFootprintMask

Mask = Annotated[
    Union[HeightMask, SlopeMask, PaintMask, RoadNetworkMask, ScatterFootprintMask],
    Field(discriminator="type"),
]
