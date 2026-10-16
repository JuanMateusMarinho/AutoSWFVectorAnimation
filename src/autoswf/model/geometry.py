"""2D geometry in Flash conventions: pixels, y pointing down."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Matrix:
    """Affine transform, Flash order: x' = a*x + c*y + tx, y' = b*x + d*y + ty (translation in px)."""
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    @classmethod
    def identity(cls) -> "Matrix":
        return cls()

    @classmethod
    def translate(cls, tx: float, ty: float) -> "Matrix":
        return cls(tx=tx, ty=ty)

    @classmethod
    def scale(cls, sx: float, sy: float) -> "Matrix":
        return cls(a=sx, d=sy)

    @classmethod
    def rotate(cls, radians: float) -> "Matrix":
        cos, sin = math.cos(radians), math.sin(radians)
        return cls(a=cos, b=sin, c=-sin, d=cos)

    def __matmul__(self, o: "Matrix") -> "Matrix":
        return Matrix(
            a=self.a * o.a + self.c * o.b,
            b=self.b * o.a + self.d * o.b,
            c=self.a * o.c + self.c * o.d,
            d=self.b * o.c + self.d * o.d,
            tx=self.a * o.tx + self.c * o.ty + self.tx,
            ty=self.b * o.tx + self.d * o.ty + self.ty,
        )

    def apply(self, p: Point) -> Point:
        return Point(self.a * p.x + self.c * p.y + self.tx, self.b * p.x + self.d * p.y + self.ty)


@dataclass(frozen=True)
class ColorTransform:
    """Per-channel multiply then add, RGBA order (add terms are -255..255)."""
    mult: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    add: tuple[int, int, int, int] = (0, 0, 0, 0)
