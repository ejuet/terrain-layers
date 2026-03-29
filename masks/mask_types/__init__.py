from typing import Union
from .height import HeightMask
from .slope import SlopeMask
from .paint import PaintMask
from .path import RoadNetworkMask

Mask = Union[HeightMask, SlopeMask, PaintMask, RoadNetworkMask]
