from typing import Union
from .height import HeightMask
from .slope import SlopeMask
from .paint import PaintMask
from .path import PathMask

Mask = Union[HeightMask, SlopeMask, PaintMask, PathMask]
