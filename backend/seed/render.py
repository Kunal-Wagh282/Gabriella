"""Renders consistent flat-lay product illustrations with Pillow.

Each garment shape is a set of normalised polygons (0..1 on a 4:5 canvas). The renderer
fills them with the product colour and pattern, adds soft lighting, a drop shadow and
stitch details, then downsamples for anti-aliasing. Output is deterministic per product.
"""

import colorsys
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 640, 800
SS = 2  # supersampling factor
BG_TOP = (241, 237, 231)
BG_BOTTOM = (229, 223, 214)
SHIRTING_WHITE = (240, 238, 233)

Pt = tuple[float, float]


@dataclass
class Fill:
    """A polygon drawn in a fixed colour (soles, inner collars) rather than the fabric."""

    points: list[Pt]
    colour: tuple[int, int, int] | str  # RGB, or "shade"/"light" relative to the fabric
    alpha: int = 255


@dataclass
class Shape:
    body: list[list[Pt]]
    strokes: list[tuple[list[Pt], float]] = field(default_factory=list)  # thick parts of body
    under: list[Fill] = field(default_factory=list)
    over: list[Fill] = field(default_factory=list)
    lines: list[tuple[list[Pt], float]] = field(default_factory=list)  # (points, width)
    dashed: list[list[Pt]] = field(default_factory=list)  # contrast top-stitching
    buttons: list[tuple[float, float, float]] = field(default_factory=list)
    stripes: str = "vertical"


def mirror(points: list[Pt]) -> list[Pt]:
    return [(1 - x, y) for x, y in reversed(points)]


def sym(left_half: list[Pt]) -> list[Pt]:
    """Builds a symmetric polygon from its left half (top-centre → bottom-centre, clockwise)."""
    return left_half + mirror(left_half)


# ---------------------------------------------------------------------------- shapes


def _tshirt() -> Shape:
    body = [
        (0.37, 0.13),
        (0.44, 0.165),
        (0.50, 0.175),
        (0.56, 0.165),
        (0.63, 0.13),
        (0.80, 0.19),
        (0.93, 0.36),
        (0.81, 0.42),
        (0.745, 0.34),
        (0.75, 0.87),
        (0.25, 0.87),
        (0.255, 0.34),
        (0.19, 0.42),
        (0.07, 0.36),
        (0.20, 0.19),
    ]
    return Shape(
        body=[body],
        under=[
            Fill(
                [
                    (0.37, 0.13),
                    (0.50, 0.14),
                    (0.63, 0.13),
                    (0.56, 0.165),
                    (0.50, 0.175),
                    (0.44, 0.165),
                ],
                "shade",
            )
        ],
        lines=[
            ([(0.375, 0.145), (0.44, 0.18), (0.50, 0.19), (0.56, 0.18), (0.625, 0.145)], 0.004),
            ([(0.095, 0.335), (0.205, 0.395)], 0.003),
            ([(0.905, 0.335), (0.795, 0.395)], 0.003),
            ([(0.255, 0.845), (0.745, 0.845)], 0.003),
        ],
        stripes="horizontal",
    )


def _polo() -> Shape:
    s = _tshirt()
    s.over += [
        Fill([(0.37, 0.13), (0.50, 0.175), (0.45, 0.215), (0.345, 0.165)], "light"),
        Fill(mirror([(0.37, 0.13), (0.50, 0.175), (0.45, 0.215), (0.345, 0.165)]), "light"),
    ]
    s.lines += [([(0.485, 0.18), (0.485, 0.32), (0.515, 0.32), (0.515, 0.18)], 0.003)]
    s.buttons += [(0.50, 0.23, 0.007), (0.50, 0.285, 0.007)]
    s.stripes = "horizontal"
    return s


def _shirt(pocket: bool = True) -> Shape:
    body = [
        (0.40, 0.12),
        (0.50, 0.16),
        (0.60, 0.12),
        (0.78, 0.17),
        (0.86, 0.30),
        (0.93, 0.74),
        (0.84, 0.76),
        (0.77, 0.40),
        (0.76, 0.86),
        (0.62, 0.89),
        (0.50, 0.875),
        (0.38, 0.89),
        (0.24, 0.86),
        (0.23, 0.40),
        (0.16, 0.76),
        (0.07, 0.74),
        (0.14, 0.30),
        (0.22, 0.17),
    ]
    collar_l = [(0.40, 0.112), (0.50, 0.165), (0.455, 0.222), (0.365, 0.155)]
    lines = [
        ([(0.488, 0.165), (0.488, 0.875)], 0.003),
        ([(0.512, 0.165), (0.512, 0.875)], 0.003),
        ([(0.085, 0.69), (0.165, 0.71)], 0.003),
        ([(0.915, 0.69), (0.835, 0.71)], 0.003),
        (collar_l + [collar_l[0]], 0.003),
        (mirror(collar_l) + [mirror(collar_l)[0]], 0.003),
    ]
    if pocket:
        lines.append(
            (
                [
                    (0.58, 0.30),
                    (0.68, 0.30),
                    (0.68, 0.40),
                    (0.63, 0.415),
                    (0.58, 0.40),
                    (0.58, 0.30),
                ],
                0.003,
            )
        )
    return Shape(
        body=[body, collar_l, mirror(collar_l)],
        under=[Fill([(0.40, 0.115), (0.50, 0.10), (0.60, 0.115), (0.50, 0.165)], "shade")],
        lines=lines,
        buttons=[(0.50, y, 0.007) for y in (0.25, 0.37, 0.49, 0.61, 0.73)],
    )


def _blouse() -> Shape:
    body = [
        (0.38, 0.13),
        (0.50, 0.26),
        (0.62, 0.13),
        (0.79, 0.19),
        (0.91, 0.43),
        (0.80, 0.47),
        (0.735, 0.34),
        (0.79, 0.84),
        (0.50, 0.865),
        (0.21, 0.84),
        (0.265, 0.34),
        (0.20, 0.47),
        (0.09, 0.43),
        (0.21, 0.19),
    ]
    return Shape(
        body=[body],
        under=[Fill([(0.38, 0.13), (0.50, 0.15), (0.62, 0.13), (0.50, 0.26)], "shade")],
        lines=[
            ([(0.39, 0.145), (0.50, 0.265), (0.61, 0.145)], 0.003),
            ([(0.105, 0.415), (0.205, 0.455)], 0.003),
            ([(0.895, 0.415), (0.795, 0.455)], 0.003),
            ([(0.44, 0.40), (0.42, 0.80)], 0.002),
            ([(0.58, 0.42), (0.60, 0.80)], 0.002),
        ],
    )


def _sweater(hood: bool = False) -> Shape:
    body = [
        (0.37, 0.13),
        (0.44, 0.17),
        (0.50, 0.18),
        (0.56, 0.17),
        (0.63, 0.13),
        (0.80, 0.18),
        (0.88, 0.32),
        (0.92, 0.78),
        (0.82, 0.79),
        (0.77, 0.38),
        (0.76, 0.85),
        (0.24, 0.85),
        (0.23, 0.38),
        (0.18, 0.79),
        (0.08, 0.78),
        (0.12, 0.32),
        (0.20, 0.18),
    ]
    ribs = [([(x, 0.80), (x, 0.845)], 0.002) for x in [0.26 + i * 0.024 for i in range(21)]]
    ribs += [([(0.09 + i * 0.016, 0.735), (0.087 + i * 0.016, 0.775)], 0.002) for i in range(6)]
    ribs += [([(0.91 - i * 0.016, 0.735), (0.913 - i * 0.016, 0.775)], 0.002) for i in range(6)]
    shape = Shape(
        body=[body],
        under=[
            Fill(
                [
                    (0.37, 0.13),
                    (0.50, 0.14),
                    (0.63, 0.13),
                    (0.56, 0.17),
                    (0.50, 0.18),
                    (0.44, 0.17),
                ],
                "shade",
            )
        ],
        lines=[
            ([(0.24, 0.80), (0.76, 0.80)], 0.003),
            ([(0.375, 0.15), (0.44, 0.188), (0.50, 0.198), (0.56, 0.188), (0.625, 0.15)], 0.004),
            *ribs,
        ],
        stripes="horizontal",
    )
    if hood:
        hood_poly = [
            (0.35, 0.15),
            (0.37, 0.06),
            (0.50, 0.03),
            (0.63, 0.06),
            (0.65, 0.15),
            (0.56, 0.21),
            (0.50, 0.22),
            (0.44, 0.21),
        ]
        shape.body.append(hood_poly)
        shape.under = []
        shape.over = [
            Fill(
                [
                    (0.40, 0.14),
                    (0.44, 0.08),
                    (0.50, 0.065),
                    (0.56, 0.08),
                    (0.60, 0.14),
                    (0.55, 0.195),
                    (0.45, 0.195),
                ],
                "shade",
            )
        ]
        shape.lines = [
            ([(0.24, 0.80), (0.76, 0.80)], 0.003),
            ([(0.34, 0.60), (0.66, 0.60), (0.70, 0.79), (0.30, 0.79), (0.34, 0.60)], 0.003),
            ([(0.465, 0.20), (0.46, 0.36)], 0.005),
            ([(0.535, 0.20), (0.54, 0.36)], 0.005),
            *ribs,
        ]
    return shape


def _blazer() -> Shape:
    body = [
        (0.40, 0.11),
        (0.50, 0.14),
        (0.60, 0.11),
        (0.80, 0.16),
        (0.87, 0.30),
        (0.92, 0.80),
        (0.82, 0.81),
        (0.775, 0.40),
        (0.775, 0.90),
        (0.53, 0.91),
        (0.50, 0.87),
        (0.47, 0.91),
        (0.225, 0.90),
        (0.225, 0.40),
        (0.18, 0.81),
        (0.08, 0.80),
        (0.13, 0.30),
        (0.20, 0.16),
    ]
    lapel_l = [(0.42, 0.115), (0.355, 0.30), (0.41, 0.315), (0.50, 0.52)]
    return Shape(
        body=[body],
        over=[
            Fill([(0.425, 0.115), (0.50, 0.14), (0.575, 0.115), (0.50, 0.50)], SHIRTING_WHITE),
            Fill(
                [(0.42, 0.115), (0.355, 0.30), (0.41, 0.315), (0.50, 0.52), (0.47, 0.30)],
                "light",
                70,
            ),
            Fill(
                mirror([(0.42, 0.115), (0.355, 0.30), (0.41, 0.315), (0.50, 0.52), (0.47, 0.30)]),
                "light",
                70,
            ),
        ],
        lines=[
            (lapel_l, 0.004),
            (mirror(lapel_l), 0.004),
            ([(0.50, 0.50), (0.50, 0.87)], 0.003),
            ([(0.28, 0.70), (0.42, 0.70)], 0.004),
            ([(0.58, 0.70), (0.72, 0.70)], 0.004),
            ([(0.60, 0.37), (0.70, 0.36)], 0.004),
            ([(0.10, 0.74), (0.18, 0.75)], 0.002),
            ([(0.90, 0.74), (0.82, 0.75)], 0.002),
        ],
        buttons=[(0.50, 0.585, 0.011), (0.50, 0.69, 0.011)],
    )


def _jacket() -> Shape:
    body = [
        (0.40, 0.13),
        (0.50, 0.15),
        (0.60, 0.13),
        (0.80, 0.17),
        (0.88, 0.31),
        (0.92, 0.76),
        (0.82, 0.77),
        (0.78, 0.40),
        (0.78, 0.80),
        (0.22, 0.80),
        (0.22, 0.40),
        (0.18, 0.77),
        (0.08, 0.76),
        (0.12, 0.31),
        (0.20, 0.17),
    ]
    collar_l = [(0.40, 0.12), (0.50, 0.155), (0.44, 0.24), (0.33, 0.17)]
    return Shape(
        body=[body, collar_l, mirror(collar_l)],
        under=[Fill([(0.40, 0.125), (0.50, 0.11), (0.60, 0.125), (0.50, 0.155)], "shade")],
        lines=[
            (collar_l + [collar_l[0]], 0.003),
            (mirror(collar_l) + [mirror(collar_l)[0]], 0.003),
            ([(0.50, 0.155), (0.50, 0.80)], 0.004),
            ([(0.28, 0.33), (0.42, 0.33), (0.42, 0.45), (0.28, 0.45), (0.28, 0.33)], 0.003),
            ([(0.58, 0.33), (0.72, 0.33), (0.72, 0.45), (0.58, 0.45), (0.58, 0.33)], 0.003),
            ([(0.28, 0.37), (0.42, 0.37)], 0.003),
            ([(0.58, 0.37), (0.72, 0.37)], 0.003),
            ([(0.22, 0.74), (0.78, 0.74)], 0.003),
        ],
        dashed=[[(0.24, 0.735), (0.76, 0.735)]],
        buttons=[(0.50, y, 0.009) for y in (0.26, 0.40, 0.54, 0.68)]
        + [(0.35, 0.355, 0.007), (0.65, 0.355, 0.007)],
    )


def _kurta() -> Shape:
    body = [
        (0.41, 0.10),
        (0.50, 0.12),
        (0.59, 0.10),
        (0.78, 0.15),
        (0.86, 0.28),
        (0.91, 0.66),
        (0.82, 0.67),
        (0.76, 0.36),
        (0.76, 0.70),
        (0.80, 0.96),
        (0.20, 0.96),
        (0.24, 0.70),
        (0.24, 0.36),
        (0.18, 0.67),
        (0.09, 0.66),
        (0.14, 0.28),
        (0.22, 0.15),
    ]
    return Shape(
        body=[body],
        under=[Fill([(0.41, 0.10), (0.50, 0.09), (0.59, 0.10), (0.50, 0.12)], "shade")],
        lines=[
            ([(0.41, 0.115), (0.50, 0.135), (0.59, 0.115)], 0.004),
            ([(0.488, 0.135), (0.488, 0.36), (0.512, 0.36), (0.512, 0.135)], 0.003),
            ([(0.24, 0.72), (0.215, 0.96)], 0.003),
            ([(0.76, 0.72), (0.785, 0.96)], 0.003),
            ([(0.10, 0.62), (0.18, 0.63)], 0.003),
            ([(0.90, 0.62), (0.82, 0.63)], 0.003),
            ([(0.21, 0.93), (0.79, 0.93)], 0.003),
        ],
        buttons=[(0.50, y, 0.006) for y in (0.17, 0.23, 0.29)],
    )


def _vest() -> Shape:
    body = [
        (0.40, 0.12),
        (0.50, 0.14),
        (0.60, 0.12),
        (0.70, 0.15),
        (0.74, 0.22),
        (0.72, 0.36),
        (0.74, 0.82),
        (0.52, 0.86),
        (0.50, 0.81),
        (0.48, 0.86),
        (0.26, 0.82),
        (0.28, 0.36),
        (0.26, 0.22),
        (0.30, 0.15),
    ]
    return Shape(
        body=[body],
        under=[Fill([(0.40, 0.12), (0.50, 0.10), (0.60, 0.12), (0.50, 0.14)], "shade")],
        lines=[
            ([(0.40, 0.135), (0.50, 0.155), (0.60, 0.135)], 0.004),
            ([(0.50, 0.155), (0.50, 0.81)], 0.003),
            ([(0.31, 0.62), (0.42, 0.62)], 0.004),
            ([(0.58, 0.62), (0.69, 0.62)], 0.004),
            ([(0.58, 0.33), (0.67, 0.325)], 0.004),
        ],
        buttons=[(0.50, y, 0.008) for y in (0.21, 0.31, 0.41, 0.51, 0.61, 0.71)],
    )


def _trousers(kind: str = "chino") -> Shape:
    hem = (0.745, 0.555) if kind != "joggers" else (0.70, 0.575)
    body = [
        (0.30, 0.08),
        (0.70, 0.08),
        (0.71, 0.14),
        (hem[0], 0.93),
        (hem[1], 0.94),
        (0.50, 0.36),
        (1 - hem[1], 0.94),
        (1 - hem[0], 0.93),
        (0.29, 0.14),
    ]
    lines = [
        ([(0.295, 0.125), (0.705, 0.125)], 0.003),
        ([(0.52, 0.13), (0.52, 0.28), (0.50, 0.32)], 0.003),
    ]
    dashed: list[list[Pt]] = []
    if kind == "joggers":
        lines += [([(0.30, y), (0.70, y)], 0.002) for y in (0.095, 0.11)]
        lines += [
            ([(1 - hem[0] + 0.005, 0.89), (1 - hem[1] - 0.005, 0.895)], 0.003),
            ([(hem[0] - 0.005, 0.89), (hem[1] + 0.005, 0.895)], 0.003),
        ]
        lines += [([(0.46, 0.125), (0.45, 0.20)], 0.004), ([(0.54, 0.125), (0.55, 0.20)], 0.004)]
    else:
        lines += [
            ([(0.30, 0.14), (0.36, 0.25)], 0.003),
            ([(0.70, 0.14), (0.64, 0.25)], 0.003),
            ([(0.40, 0.15), (0.35, 0.92)], 0.002),
            ([(0.60, 0.15), (0.65, 0.92)], 0.002),
        ]
        lines += [([(x, 0.08), (x, 0.125)], 0.004) for x in (0.34, 0.44, 0.56, 0.66)]
    if kind == "jeans":
        dashed = [
            [(0.30, 0.135), (0.70, 0.135)],
            [(0.535, 0.13), (0.535, 0.29), (0.505, 0.33)],
            [(0.305, 0.15), (0.37, 0.255)],
            [(0.695, 0.15), (0.63, 0.255)],
            [(0.62, 0.15), (0.67, 0.15), (0.675, 0.20)],
        ]
    shape = Shape(body=[body], lines=lines, dashed=dashed)
    if kind == "jeans":
        shape.buttons = [(0.50, 0.10, 0.009), (0.37, 0.255, 0.004), (0.63, 0.255, 0.004)]
    return shape


def _shorts() -> Shape:
    body = [
        (0.29, 0.10),
        (0.71, 0.10),
        (0.72, 0.16),
        (0.77, 0.60),
        (0.53, 0.62),
        (0.50, 0.38),
        (0.47, 0.62),
        (0.23, 0.60),
        (0.28, 0.16),
    ]
    return Shape(
        body=[body],
        lines=[
            ([(0.285, 0.145), (0.715, 0.145)], 0.003),
            ([(0.52, 0.15), (0.52, 0.30), (0.50, 0.34)], 0.003),
            ([(0.29, 0.16), (0.35, 0.27)], 0.003),
            ([(0.71, 0.16), (0.65, 0.27)], 0.003),
            ([(0.235, 0.575), (0.465, 0.595)], 0.003),
            ([(0.765, 0.575), (0.535, 0.595)], 0.003),
        ],
    )


def _skirt() -> Shape:
    body = [
        (0.33, 0.10),
        (0.67, 0.10),
        (0.68, 0.16),
        (0.80, 0.80),
        (0.50, 0.82),
        (0.20, 0.80),
        (0.32, 0.16),
    ]
    return Shape(
        body=[body],
        lines=[
            ([(0.325, 0.155), (0.675, 0.155)], 0.003),
            ([(0.42, 0.16), (0.36, 0.80)], 0.002),
            ([(0.50, 0.16), (0.50, 0.815)], 0.002),
            ([(0.58, 0.16), (0.64, 0.80)], 0.002),
        ],
    )


def _dress() -> Shape:
    body = [
        (0.375, 0.08),
        (0.395, 0.08),
        (0.42, 0.20),
        (0.50, 0.245),
        (0.58, 0.20),
        (0.605, 0.08),
        (0.625, 0.08),
        (0.645, 0.24),
        (0.62, 0.42),
        (0.82, 0.93),
        (0.50, 0.95),
        (0.18, 0.93),
        (0.38, 0.42),
        (0.355, 0.24),
    ]
    return Shape(
        body=[body],
        lines=[
            ([(0.38, 0.42), (0.62, 0.42)], 0.004),
            ([(0.45, 0.43), (0.36, 0.92)], 0.002),
            ([(0.55, 0.43), (0.64, 0.92)], 0.002),
            ([(0.50, 0.43), (0.50, 0.94)], 0.002),
        ],
    )


def _shoe_base(upper: list[Pt], sole: list[Pt], sole_colour: tuple[int, int, int] | str) -> Shape:
    return Shape(body=[upper], over=[Fill(sole, sole_colour)])


def _sneaker() -> Shape:
    s = _shoe_base(
        [
            (0.14, 0.43),
            (0.22, 0.39),
            (0.34, 0.37),
            (0.42, 0.40),
            (0.52, 0.46),
            (0.66, 0.50),
            (0.80, 0.53),
            (0.87, 0.57),
            (0.88, 0.625),
            (0.14, 0.625),
        ],
        [(0.12, 0.62), (0.89, 0.62), (0.885, 0.665), (0.80, 0.685), (0.16, 0.685), (0.12, 0.665)],
        (246, 244, 239),
    )
    s.lines = [
        ([(0.40, 0.40), (0.67, 0.515)], 0.004),
        ([(0.67, 0.515), (0.74, 0.535), (0.80, 0.585), (0.78, 0.62)], 0.003),
        ([(0.22, 0.43), (0.36, 0.45), (0.50, 0.56), (0.60, 0.60)], 0.004),
        *[
            ([(0.43 + i * 0.045, 0.415 + i * 0.019), (0.465 + i * 0.045, 0.40 + i * 0.019)], 0.005)
            for i in range(5)
        ],
        ([(0.14, 0.43), (0.19, 0.46), (0.19, 0.60)], 0.003),
    ]
    return s


def _loafer(laced: bool = False) -> Shape:
    s = _shoe_base(
        [
            (0.14, 0.485),
            (0.20, 0.455),
            (0.36, 0.465),
            (0.50, 0.47),
            (0.66, 0.485),
            (0.80, 0.52),
            (0.88, 0.57),
            (0.88, 0.61),
            (0.14, 0.61),
        ],
        [(0.13, 0.605), (0.89, 0.605), (0.88, 0.64), (0.14, 0.64)],
        (58, 40, 30),
    )
    s.over.append(Fill([(0.14, 0.64), (0.26, 0.64), (0.25, 0.67), (0.15, 0.67)], (48, 33, 25)))
    if laced:
        s.lines = [
            ([(0.42, 0.47), (0.52, 0.475), (0.60, 0.50)], 0.004),
            *[([(0.44 + i * 0.04, 0.472), (0.46 + i * 0.04, 0.50)], 0.004) for i in range(4)],
            ([(0.72, 0.505), (0.74, 0.57), (0.70, 0.605)], 0.003),
            ([(0.30, 0.47), (0.33, 0.60)], 0.003),
        ]
    else:
        s.lines = [
            ([(0.48, 0.475), (0.56, 0.53), (0.67, 0.505)], 0.005),
            ([(0.47, 0.475), (0.62, 0.53), (0.76, 0.52), (0.80, 0.56)], 0.003),
            ([(0.30, 0.465), (0.32, 0.60)], 0.003),
        ]
    return s


def _boot() -> Shape:
    s = _shoe_base(
        [
            (0.18, 0.22),
            (0.40, 0.22),
            (0.42, 0.46),
            (0.60, 0.50),
            (0.78, 0.53),
            (0.87, 0.58),
            (0.87, 0.625),
            (0.16, 0.625),
            (0.17, 0.40),
        ],
        [(0.15, 0.62), (0.885, 0.62), (0.88, 0.66), (0.16, 0.66)],
        (52, 38, 30),
    )
    s.over += [
        Fill([(0.30, 0.225), (0.37, 0.225), (0.385, 0.42), (0.335, 0.47), (0.285, 0.42)], "shade"),
        Fill([(0.16, 0.66), (0.29, 0.66), (0.285, 0.685), (0.165, 0.685)], (44, 32, 26)),
    ]
    s.lines = [([(0.42, 0.46), (0.40, 0.62)], 0.003), ([(0.17, 0.235), (0.40, 0.235)], 0.003)]
    return s


def _heel() -> Shape:
    upper = [
        (0.20, 0.42),
        (0.245, 0.43),
        (0.34, 0.50),
        (0.48, 0.56),
        (0.60, 0.565),
        (0.74, 0.585),
        (0.85, 0.615),
        (0.895, 0.645),
        (0.885, 0.665),
        (0.62, 0.665),
        (0.40, 0.625),
        (0.24, 0.58),
        (0.19, 0.56),
    ]
    return Shape(
        body=[upper],
        under=[Fill([(0.195, 0.55), (0.265, 0.58), (0.25, 0.76), (0.22, 0.76)], "shade")],
        over=[
            Fill([(0.245, 0.43), (0.34, 0.50), (0.48, 0.56), (0.36, 0.55), (0.25, 0.50)], "shade")
        ],
        lines=[([(0.19, 0.56), (0.40, 0.625), (0.62, 0.665), (0.885, 0.665)], 0.004)],
    )


def _sandal() -> Shape:
    return Shape(
        body=[
            [(0.36, 0.585), (0.42, 0.455), (0.50, 0.43), (0.62, 0.43), (0.71, 0.46), (0.78, 0.585)]
        ],
        under=[Fill([(0.12, 0.575), (0.88, 0.575), (0.89, 0.625), (0.12, 0.625)], (196, 160, 116))],
        over=[Fill([(0.115, 0.62), (0.895, 0.62), (0.89, 0.65), (0.12, 0.65)], (58, 44, 36))],
        lines=[([(0.40, 0.50), (0.74, 0.50)], 0.003)],
        dashed=[[(0.43, 0.465), (0.70, 0.465)]],
    )


def _jutti() -> Shape:
    s = _shoe_base(
        [
            (0.16, 0.50),
            (0.24, 0.47),
            (0.40, 0.48),
            (0.58, 0.50),
            (0.76, 0.53),
            (0.86, 0.55),
            (0.92, 0.52),
            (0.90, 0.58),
            (0.86, 0.615),
            (0.16, 0.615),
        ],
        [(0.15, 0.61), (0.87, 0.61), (0.85, 0.635), (0.16, 0.635)],
        (92, 64, 44),
    )
    s.over.append(Fill([(0.24, 0.47), (0.40, 0.48), (0.30, 0.50)], "shade"))
    s.dashed = [
        [(0.42, 0.50), (0.56, 0.52), (0.70, 0.55), (0.80, 0.58)],
        [(0.45, 0.535), (0.60, 0.56), (0.75, 0.59)],
    ]
    s.buttons = [(0.48 + i * 0.06, 0.575 + i * 0.008, 0.006) for i in range(5)]
    return s


def _belt() -> Shape:
    return Shape(
        body=[
            [
                (0.06, 0.48),
                (0.10, 0.455),
                (0.74, 0.455),
                (0.74, 0.545),
                (0.10, 0.545),
                (0.06, 0.52),
            ],
            [(0.80, 0.465), (0.94, 0.465), (0.94, 0.535), (0.80, 0.535)],
        ],
        over=[
            Fill([(0.72, 0.425), (0.82, 0.425), (0.82, 0.575), (0.72, 0.575)], (176, 156, 112)),
            Fill([(0.735, 0.44), (0.805, 0.44), (0.805, 0.56), (0.735, 0.56)], BG_TOP),
        ],
        lines=[
            ([(0.10, 0.465), (0.72, 0.465)], 0.002),
            ([(0.10, 0.535), (0.72, 0.535)], 0.002),
            ([(0.77, 0.44), (0.80, 0.50)], 0.006),
        ],
        buttons=[(0.86 + i * 0.03, 0.50, 0.007) for i in range(3)],
    )


def _bag() -> Shape:
    return Shape(
        body=[[(0.22, 0.40), (0.78, 0.40), (0.82, 0.86), (0.18, 0.86)]],
        strokes=[
            ([(0.34, 0.41), (0.36, 0.26), (0.42, 0.20), (0.50, 0.19)], 0.03),
            ([(0.66, 0.41), (0.64, 0.26), (0.58, 0.20), (0.50, 0.19)], 0.03),
        ],
        lines=[
            ([(0.22, 0.44), (0.78, 0.44)], 0.003),
            ([(0.36, 0.40), (0.36, 0.50)], 0.004),
            ([(0.64, 0.40), (0.64, 0.50)], 0.004),
        ],
        buttons=[(0.50, 0.47, 0.012)],
    )


def _cap() -> Shape:
    return Shape(
        body=[
            [
                (0.20, 0.60),
                (0.22, 0.46),
                (0.30, 0.36),
                (0.46, 0.31),
                (0.62, 0.34),
                (0.72, 0.44),
                (0.75, 0.58),
            ],
            [(0.58, 0.56), (0.92, 0.585), (0.91, 0.635), (0.62, 0.63)],
        ],
        lines=[
            ([(0.46, 0.31), (0.48, 0.60)], 0.003),
            ([(0.46, 0.31), (0.34, 0.60)], 0.003),
            ([(0.20, 0.60), (0.62, 0.61)], 0.004),
        ],
        buttons=[(0.46, 0.31, 0.012)],
    )


def _scarf() -> Shape:
    return Shape(
        body=[
            [(0.36, 0.10), (0.64, 0.10), (0.67, 0.86), (0.33, 0.86)],
            [(0.40, 0.10), (0.60, 0.10), (0.62, 0.20), (0.38, 0.20)],
        ],
        lines=[
            ([(0.45, 0.20), (0.43, 0.85)], 0.002),
            ([(0.55, 0.20), (0.57, 0.85)], 0.002),
            ([(0.38, 0.20), (0.62, 0.20)], 0.003),
        ]
        + [([(0.335 + i * 0.0225, 0.86), (0.335 + i * 0.0225, 0.90)], 0.004) for i in range(16)],
    )


SHAPES: dict[str, Callable[[], Shape]] = {
    "tshirt": _tshirt,
    "polo": _polo,
    "shirt": _shirt,
    "shirt_formal": lambda: _shirt(pocket=False),
    "blouse": _blouse,
    "sweater": _sweater,
    "hoodie": lambda: _sweater(hood=True),
    "blazer": _blazer,
    "jacket": _jacket,
    "kurta": _kurta,
    "vest": _vest,
    "trousers": _trousers,
    "jeans": lambda: _trousers("jeans"),
    "joggers": lambda: _trousers("joggers"),
    "shorts": _shorts,
    "skirt": _skirt,
    "dress": _dress,
    "sneaker": _sneaker,
    "loafer": _loafer,
    "oxford": lambda: _loafer(laced=True),
    "boot": _boot,
    "heel": _heel,
    "sandal": _sandal,
    "jutti": _jutti,
    "belt": _belt,
    "bag": _bag,
    "cap": _cap,
    "scarf": _scarf,
}

# ------------------------------------------------------------------------- drawing


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _adjust(rgb: tuple[int, int, int], lightness: float) -> tuple[int, int, int]:
    h, l_, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    l_ = min(1.0, max(0.0, l_ + lightness))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l_, s))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _round_corners(points: list[Pt], radius: float = 0.012, segments: int = 4) -> list[Pt]:
    """Rounds each corner by a fixed radius so long edges stay straight and hems stay crisp."""
    out: list[Pt] = []
    n = len(points)
    for i in range(n):
        ax, ay = points[i - 1]
        px, py = points[i]
        bx, by = points[(i + 1) % n]
        da = math.hypot(ax - px, ay - py) or 1e-9
        db = math.hypot(bx - px, by - py) or 1e-9
        r = min(radius, da / 2, db / 2)
        p1 = (px + (ax - px) * r / da, py + (ay - py) * r / da)
        p2 = (px + (bx - px) * r / db, py + (by - py) * r / db)
        for k in range(segments + 1):
            t = k / segments
            out.append(
                (
                    (1 - t) ** 2 * p1[0] + 2 * (1 - t) * t * px + t**2 * p2[0],
                    (1 - t) ** 2 * p1[1] + 2 * (1 - t) * t * py + t**2 * p2[1],
                )
            )
    return out


def _px(points: list[Pt], offset: Pt = (0, 0)) -> list[tuple[float, float]]:
    return [((x + offset[0]) * W * SS, (y + offset[1]) * H * SS) for x, y in points]


def _fabric(
    size: tuple[int, int],
    base: tuple[int, int, int],
    pattern: str,
    secondary: list[tuple[int, int, int]],
    stripes: str,
    material: str,
    rng: random.Random,
) -> Image.Image:
    fabric = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(fabric, "RGBA")
    w, h = size
    accent = secondary[0] if secondary else _adjust(base, 0.3 if _luminance(base) < 0.5 else -0.3)
    unit = int(0.032 * W * SS)

    if pattern == "striped":
        width = max(2, int(unit * 0.32))
        for i in range(0, max(w, h), unit):
            if stripes == "horizontal":
                draw.rectangle([0, i, w, i + width], fill=(*accent, 235))
            else:
                draw.rectangle([i, 0, i + width, h], fill=(*accent, 235))
    elif pattern == "checked":
        step = int(unit * 2.2)
        second = secondary[1] if len(secondary) > 1 else _adjust(base, -0.15)
        for i in range(0, max(w, h), step):
            draw.rectangle([i, 0, i + step // 3, h], fill=(*accent, 90))
            draw.rectangle([0, i, w, i + step // 3], fill=(*accent, 90))
            draw.line(
                [(i + step // 2, 0), (i + step // 2, h)], fill=(*second, 160), width=max(2, SS)
            )
            draw.line(
                [(0, i + step // 2), (w, i + step // 2)], fill=(*second, 160), width=max(2, SS)
            )
    elif pattern == "printed":
        r = int(unit * 0.28)
        for _ in range(int(w * h / (unit * unit) * 0.9)):
            cx, cy = rng.uniform(0, w), rng.uniform(0, h)
            colour = rng.choice(secondary) if secondary else accent
            for k in range(5):  # five-petal motif
                ang = k * 1.2566 + rng.random() * 0.3
                px, py = cx + r * 0.9 * math.cos(ang), cy + r * 0.9 * math.sin(ang)
                draw.ellipse(
                    [px - r * 0.55, py - r * 0.55, px + r * 0.55, py + r * 0.55],
                    fill=(*colour, 215),
                )
            draw.ellipse(
                [cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3],
                fill=(*_adjust(colour, -0.2), 230),
            )
    if "denim" in material.lower():
        for i in range(-h, w, max(3, SS * 3)):
            draw.line([(i, 0), (i + h, h)], fill=(255, 255, 255, 14), width=SS)

    # Fibre texture: stronger for knits, textured weaves and suede.
    strength = (
        0.10
        if pattern == "textured"
        or any(
            k in material.lower() for k in ("knit", "wool", "suede", "linen", "fleece", "jacquard")
        )
        else 0.045
    )
    noise = (
        Image.effect_noise((w // SS, h // SS), 64)
        .resize(size, Image.Resampling.BILINEAR)
        .convert("RGB")
    )
    fabric = ImageChops.blend(fabric, ImageChops.overlay(fabric, noise), strength * 4)
    return fabric


@lru_cache(maxsize=4)
def _lighting(size: tuple[int, int]) -> Image.Image:
    """Diagonal light from the top-left: 0..255 mask used to darken the far corner."""
    grad = Image.linear_gradient("L").rotate(-35, expand=False).resize(size)
    return grad.point(lambda v: int(v * 0.32))


def _detail_colour(base: tuple[int, int, int]) -> tuple[int, int, int]:
    return _adjust(base, -0.22) if _luminance(base) > 0.22 else _adjust(base, 0.18)


def _draw_layer(
    canvas: Image.Image,
    shape: Shape,
    base: tuple[int, int, int],
    fabric: Image.Image,
    offset: Pt = (0, 0),
    darken: float = 0.0,
) -> None:
    size = canvas.size
    if darken:
        base = _adjust(base, -darken)
        fabric = ImageChops.multiply(
            fabric, Image.new("RGB", size, _adjust((255, 255, 255), -darken * 1.5))
        )

    def resolve(colour: tuple[int, int, int] | str) -> tuple[int, int, int]:
        if colour == "shade":
            return _adjust(base, -0.12)
        if colour == "light":
            return _adjust(base, 0.06)
        return _adjust(colour, -darken) if darken else colour  # type: ignore[arg-type]

    mask = Image.new("L", size, 0)
    mdraw = ImageDraw.Draw(mask)
    for poly in shape.body:
        mdraw.polygon(_px(_round_corners(poly), offset), fill=255)
    for pts, width in shape.strokes:
        mdraw.line(_px(pts, offset), fill=255, width=int(width * W * SS), joint="curve")

    # Under-fills (inner necklines, heels) sit beneath the garment.
    under = ImageDraw.Draw(canvas, "RGBA")
    for f in shape.under:
        under.polygon(
            _px(_round_corners(f.points, 0.006), offset), fill=(*resolve(f.colour), f.alpha)
        )

    # Soft contact shadow.
    small = mask.resize((size[0] // 4, size[1] // 4), Image.Resampling.BILINEAR)
    shadow = (
        small.filter(ImageFilter.GaussianBlur(14 * SS / 4))
        .resize(size, Image.Resampling.BILINEAR)
        .point(lambda v: int(v * 0.30))
    )
    shadow = ImageChops.offset(shadow, int(0.012 * W * SS), int(0.018 * H * SS))
    canvas.paste((70, 58, 46), (0, 0), shadow)

    lit = fabric.copy()
    lit.paste((0, 0, 0), (0, 0), _lighting(size))
    canvas.paste(lit, (0, 0), mask)

    draw = ImageDraw.Draw(canvas, "RGBA")
    for f in shape.over:
        draw.polygon(
            _px(_round_corners(f.points, 0.006), offset), fill=(*resolve(f.colour), f.alpha)
        )
    detail = _detail_colour(base)
    for pts, width in shape.lines:
        draw.line(
            _px(pts, offset), fill=(*detail, 200), width=max(1, int(width * W * SS)), joint="curve"
        )
    stitch = (201, 160, 78) if base[2] > base[0] else _adjust(base, 0.25)
    for pts in shape.dashed:
        _dashed(draw, _px(pts, offset), (*stitch, 230), int(0.003 * W * SS))
    for x, y, r in shape.buttons:
        cx, cy = (x + offset[0]) * W * SS, (y + offset[1]) * H * SS
        rad = r * W * SS
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(*_adjust(detail, -0.05), 255))
        draw.ellipse(
            [cx - rad * 0.45, cy - rad * 0.45, cx + rad * 0.45, cy + rad * 0.45],
            fill=(*_adjust(detail, 0.1), 255),
        )


def _dashed(
    draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], fill: tuple[int, ...], width: int
) -> None:
    dash = width * 4
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        steps = max(1, int(length // dash))
        for i in range(0, steps, 2):
            t0, t1 = i / steps, min(1, (i + 1) / steps)
            draw.line(
                [
                    (x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                    (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1),
                ],
                fill=fill,
                width=width,
            )


@lru_cache(maxsize=2)
def _background_cached(size: tuple[int, int]) -> Image.Image:
    grad = Image.linear_gradient("L").resize(size)
    top = Image.new("RGB", size, BG_TOP)
    bottom = Image.new("RGB", size, BG_BOTTOM)
    return Image.composite(bottom, top, grad)


def render_flatlay(
    shape_key: str,
    colour_hex: str,
    *,
    pattern: str = "solid",
    material: str = "",
    secondary_hex: list[str] | None = None,
    seed: int = 0,
) -> Image.Image:
    rng = random.Random(seed)
    size = (W * SS, H * SS)
    base = hex_to_rgb(colour_hex)
    secondary = [hex_to_rgb(h) for h in (secondary_hex or [])]
    shape = SHAPES[shape_key]()
    fabric = _fabric(size, base, pattern, secondary, shape.stripes, material, rng)
    canvas = _background_cached(size).copy()
    _draw_layer(canvas, shape, base, fabric)
    return canvas.resize((W, H), Image.Resampling.LANCZOS)


def render_swatch(
    colour_hex: str,
    *,
    pattern: str = "solid",
    material: str = "",
    secondary_hex: list[str] | None = None,
    seed: int = 0,
) -> Image.Image:
    """A close-up fabric square used as the second gallery image."""
    rng = random.Random(seed + 1)
    size = (W * SS, W * SS)
    base = hex_to_rgb(colour_hex)
    secondary = [hex_to_rgb(h) for h in (secondary_hex or [])]
    fabric = _fabric(size, base, pattern, secondary, "vertical", material, rng)
    fabric.paste((0, 0, 0), (0, 0), _lighting(size).point(lambda v: v // 2))
    return fabric.resize((W, W), Image.Resampling.LANCZOS)


def save_webp(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "WEBP", quality=84, method=5)
