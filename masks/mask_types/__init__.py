from typing import Union
from .height import HeightMask
from .slope import SlopeMask

Mask = Union[HeightMask, SlopeMask]
