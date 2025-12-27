from typing import Union
from .height import HeightMask
from .slope import SlopeMask
from .paint import PaintMask

Mask = Union[HeightMask, SlopeMask, PaintMask]
