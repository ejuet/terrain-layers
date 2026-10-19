from typing import Union
from .height import HeightMask
from .slope import SlopeMask
from .paint import PaintMask
from .path import RoadNetworkMask
from .scatter_footprint import ScatterFootprintMask

Mask = Union[HeightMask, SlopeMask, PaintMask, RoadNetworkMask, ScatterFootprintMask]
