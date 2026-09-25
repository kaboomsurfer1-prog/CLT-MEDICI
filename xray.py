"""Radiografii desenate procedural pentru buletinele Legacy EMS.

Fiecare zonă (mână, picior, cap, gât, genunchi) este construită din oase
desenate ca forme netede. Densitățile se adună ca pe un film real: părțile
moi sunt gri închis, corticala osului este mai luminoasă decât interiorul,
iar oasele suprapuse ies mai albe.

Starea pacientului decide leziunea:

* ``buna``     -> fără leziuni
* ``normala``  -> tumefiere ușoară a părților moi (contuzie)
* ``rea``      -> fisură (traiect de fractură fără deplasare)
* ``grava``    -> fractură cu deplasare, eschile osoase și hematom

``render_film`` întoarce imaginea RGB a filmului, cu textele de pe marginea
filmului (pacient, dată, parametri de expunere), markerul de lateralitate,
rigla în centimetri și cercul care marchează leziunea.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

FILM_W = 520
FILM_H = 620
SCALE = 2

# Densitățile din desen sunt „relative” (0-255); pe film intră la jumătate,
# ca suprapunerile să nu se satureze înainte de curba de expunere.
UNIT = 0.5

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

Point = tuple[float, float]


@lru_cache(maxsize=32)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


# ----------------------------------------------------------------------
# GEOMETRIE
# ----------------------------------------------------------------------

def _chaikin(points: Sequence[Point], iterations: int = 3, closed: bool = True) -> list[Point]:
    """Rotunjește un contur prin tăierea repetată a colțurilor."""
    pts = list(points)
    for _ in range(iterations):
        count = len(pts)
        smoothed: list[Point] = []
        for index in range(count if closed else count - 1):
            (x0, y0), (x1, y1) = pts[index], pts[(index + 1) % count]
            smoothed.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            smoothed.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if not closed:
            smoothed = [pts[0], *smoothed, pts[-1]]
        pts = smoothed
    return pts


def _rotate(points: Sequence[Point], center: Point, angle: float) -> list[Point]:
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = center
    return [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca) for x, y in points]


def _ellipse(cx: float, cy: float, rx: float, ry: float, angle: float = 0.0, steps: int = 56) -> list[Point]:
    points = [(cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps)) for i in range(steps)]
    return _rotate(points, (cx, cy), angle) if angle else points


def _box(cx: float, cy: float, w: float, h: float, corner: float, angle: float = 0.0) -> list[Point]:
    """Dreptunghi cu colțuri rotunjite (raza ``corner``), rotit cu ``angle`` grade."""
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    c = min(corner, w / 2 - 0.5, h / 2 - 0.5)
    octagon = [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]
    return _rotate(_chaikin(octagon, 2), (cx, cy), angle)


def _long_bone(p0: Point, p1: Point, profile: Sequence[tuple[float, float]], cap0: float = 0.4, cap1: float = 0.4, steps: int = 30) -> list[Point]:
    """Contur de os lung cu vârfurile exact în ``p0`` și ``p1``.

    ``profile`` = [(t, lățime)], cu t între 0 și 1 de-a lungul osului.
    Capetele sunt rotunjite; ``cap0``/``cap1`` controlează cât de bombate sunt.
    """

    def width(t: float) -> float:
        if t <= profile[0][0]:
            return profile[0][1]
        for (ta, wa), (tb, wb) in zip(profile, profile[1:]):
            if ta <= t <= tb:
                f = (t - ta) / ((tb - ta) or 1.0)
                f = (1 - math.cos(f * math.pi)) / 2
                return wa + (wb - wa) * f
        return profile[-1][1]

    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -uy, ux

    start_half, end_half = width(0.0) / 2, width(1.0) / 2
    depth0, depth1 = start_half * 2 * cap0, end_half * 2 * cap1
    if length > depth0 + depth1 + 2:
        x0, y0 = x0 + ux * depth0, y0 + uy * depth0
        x1, y1 = x1 - ux * depth1, y1 - uy * depth1
    dx, dy = x1 - x0, y1 - y0

    left, right = [], []
    for index in range(steps + 1):
        t = index / steps
        half = width(t) / 2
        cx, cy = x0 + dx * t, y0 + dy * t
        left.append((cx + nx * half, cy + ny * half))
        right.append((cx - nx * half, cy - ny * half))

    def cap(center: Point, half: float, depth: float, sign: float) -> list[Point]:
        points = []
        for index in range(1, 12):
            theta = math.pi * index / 12
            points.append((
                center[0] + (nx * half * math.cos(theta) + ux * depth * math.sin(theta)) * sign,
                center[1] + (ny * half * math.cos(theta) + uy * depth * math.sin(theta)) * sign,
            ))
        return points

    return left + cap((x1, y1), end_half, depth1, 1.0) + right[::-1] + cap((x0, y0), start_half, depth0, -1.0)


def _lerp(p0: Point, p1: Point, t: float) -> Point:
    return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)


# ----------------------------------------------------------------------
# FILMUL
# ----------------------------------------------------------------------

@dataclass
class Lesion:
    center: Point
    radius: float
    label: str


@dataclass
class Scene:
    marker: Point
    px_per_cm: float
    lesions: list[Lesion] = field(default_factory=list)


class _Film:
    """Pânza pe care se desenează: un strat de părți moi și unul de os."""

    def __init__(self, seed: int) -> None:
        self.w = FILM_W * SCALE
        self.h = FILM_H * SCALE
        self.rng = random.Random(seed)
        self.tissue = Image.new("L", (self.w, self.h), 0)
        self.bone = Image.new("L", (self.w, self.h), 0)
        self.texture = self._make_texture()

    # --- utilitare -----------------------------------------------------
    def blank(self) -> Image.Image:
        return Image.new("L", (self.w, self.h), 0)

    @staticmethod
    def scaled(points: Sequence[Point]) -> list[Point]:
        return [(x * SCALE, y * SCALE) for x, y in points]

    def mask(self, *polygons: Sequence[Point], holes: Sequence[Sequence[Point]] = ()) -> Image.Image:
        image = self.blank()
        draw = ImageDraw.Draw(image)
        for polygon in polygons:
            draw.polygon(self.scaled(polygon), fill=255)
        for hole in holes:
            draw.polygon(self.scaled(hole), fill=0)
        return image

    def stroke_mask(self, points: Sequence[Point], width: float) -> Image.Image:
        image = self.blank()
        draw = ImageDraw.Draw(image)
        scaled = self.scaled(points)
        radius = width * SCALE / 2
        draw.line(scaled, fill=255, width=max(1, int(width * SCALE)), joint="curve")
        for x, y in (scaled[0], scaled[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
        return image

    def blob(self, cx: float, cy: float, rx: float, ry: float, angle: float = 0.0, jitter: float = 0.1) -> list[Point]:
        """Elipsă ușor neregulată, pentru oase scurte (carpiene, fragmente)."""
        points = []
        for index in range(10):
            t = 2 * math.pi * index / 10
            r = 1 + self.rng.uniform(-jitter, jitter)
            points.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
        return _rotate(_chaikin(points, 3), (cx, cy), angle)

    def jagged(self, p0: Point, p1: Point, segments: int = 9, amplitude: float = 3.0) -> list[Point]:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        points = [p0]
        for index in range(1, segments):
            x, y = _lerp(p0, p1, index / segments)
            jitter = self.rng.uniform(-amplitude, amplitude)
            points.append((x + nx * jitter, y + ny * jitter))
        points.append(p1)
        return points

    def _make_texture(self) -> Image.Image:
        """Textura trabeculară: pete fine care fac osul să pară spongios."""
        coarse = Image.effect_noise((self.w // 7, self.h // 7), 70).resize((self.w, self.h), Image.BICUBIC)
        fine = Image.effect_noise((self.w // 2, self.h // 2), 60).resize((self.w, self.h), Image.BILINEAR)
        mixed = ImageChops.add(coarse, fine, scale=2.0)
        return mixed.point(lambda v: 192 + v * 63 // 255)

    # --- densități -------------------------------------------------------
    def density(self, mask: Image.Image, inner: int = 104, cortex: int = 186, depth: float = 6.0, texture: bool = True) -> Image.Image:
        """Transformă o mască de os în densitate: corticala luminoasă, interiorul mai închis."""
        box = mask.getbbox()
        if not box:
            return self.blank()
        pad = int(depth * SCALE * 3) + 4
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(self.w, box[2] + pad), min(self.h, box[3] + pad))
        crop = mask.crop(box)
        blurred = crop.filter(ImageFilter.GaussianBlur(depth * SCALE))
        lut = []
        for value in range(256):
            weight = min(1.0, max(0.0, (238 - value) / 40))
            lut.append(int((inner + (cortex - inner) * weight) * UNIT))
        dens = blurred.point(lut)
        if texture:
            dens = ImageChops.multiply(dens, self.texture.crop(box))
        dens = ImageChops.multiply(dens, crop)
        out = self.blank()
        out.paste(dens, box)
        return out

    def add_bone(self, layer: Image.Image) -> None:
        self.bone = ImageChops.add(self.bone, layer)

    def bone_shape(self, *polygons: Sequence[Point], holes: Sequence[Sequence[Point]] = (), **kwargs) -> Image.Image:
        return self.density(self.mask(*polygons, holes=holes), **kwargs)

    def add_tissue(self, mask: Image.Image, value: int = 52, edge: float = 6.0, thickness: float = 40.0) -> None:
        soft = mask.filter(ImageFilter.GaussianBlur(edge * SCALE))
        thick = mask.filter(ImageFilter.GaussianBlur(thickness * SCALE)).point(lambda v: 165 + v * 90 // 255)
        layer = ImageChops.multiply(soft, thick).point(lambda v: int(v * value * UNIT / 255))
        self.tissue = ImageChops.add(self.tissue, layer)

    def remove_tissue(self, mask: Image.Image, value: int, blur: float = 5.0) -> None:
        soft = mask.filter(ImageFilter.GaussianBlur(blur * SCALE)).point(lambda v: int(v * value * UNIT / 255))
        self.tissue = ImageChops.subtract(self.tissue, soft)

    def remove_bone(self, mask: Image.Image, value: int, blur: float = 4.0) -> None:
        soft = mask.filter(ImageFilter.GaussianBlur(blur * SCALE)).point(lambda v: int(v * value * UNIT / 255))
        self.bone = ImageChops.subtract(self.bone, soft)

    def swelling(self, center: Point, rx: float, ry: float, value: int) -> None:
        mask = self.mask(_ellipse(center[0], center[1], rx, ry))
        soft = mask.filter(ImageFilter.GaussianBlur(min(rx, ry) * 0.55 * SCALE)).point(lambda v: int(v * value * UNIT / 255))
        self.tissue = ImageChops.add(self.tissue, soft)

    # --- leziuni ---------------------------------------------------------
    def crack(self, layer: Image.Image, points: Sequence[Point], width: float = 2.0, strength: int = 255) -> Image.Image:
        line = self.blank()
        ImageDraw.Draw(line).line(self.scaled(points), fill=strength, width=max(1, int(width * SCALE)), joint="curve")
        line = line.filter(ImageFilter.GaussianBlur(0.55 * SCALE))
        return ImageChops.subtract(layer, line)

    def split(self, layer: Image.Image, cut: Sequence[Point], toward: Point) -> tuple[Image.Image, Image.Image]:
        """Taie stratul de-a lungul liniei ``cut``; al doilea rezultat e partea dinspre ``toward``."""
        (ax, ay), (zx, zy) = cut[0], cut[-1]
        length = math.hypot(zx - ax, zy - ay) or 1.0
        ux, uy = (zx - ax) / length, (zy - ay) / length
        nx, ny = -uy, ux
        if (toward[0] - ax) * nx + (toward[1] - ay) * ny < 0:
            nx, ny = -nx, -ny
        far = 4000.0
        start = (ax - ux * far, ay - uy * far)
        end = (zx + ux * far, zy + uy * far)
        polygon = [start, *cut, end, (end[0] + nx * far, end[1] + ny * far), (start[0] + nx * far, start[1] + ny * far)]
        return self.region(layer, polygon)

    def region(self, layer: Image.Image, polygon: Sequence[Point]) -> tuple[Image.Image, Image.Image]:
        """Separă interiorul poligonului (partea care se mută) de restul stratului."""
        inside = self.mask(polygon)
        moved = ImageChops.multiply(layer, inside)
        kept = ImageChops.multiply(layer, ImageOps.invert(inside))
        return kept, moved

    @staticmethod
    def move(layer: Image.Image, pivot: Point, angle: float = 0.0, dx: float = 0.0, dy: float = 0.0) -> Image.Image:
        return layer.rotate(
            angle,
            resample=Image.BICUBIC,
            center=(pivot[0] * SCALE, pivot[1] * SCALE),
            translate=(dx * SCALE, dy * SCALE),
        )

    def fragments(self, center: Point, count: int, spread: float, size: float) -> Image.Image:
        """Eschile osoase mici, împrăștiate în jurul focarului de fractură."""
        mask = self.blank()
        draw = ImageDraw.Draw(mask)
        for _ in range(count):
            cx = center[0] + self.rng.uniform(-spread, spread)
            cy = center[1] + self.rng.uniform(-spread, spread)
            radius = self.rng.uniform(size * 0.45, size)
            corners = self.rng.randint(4, 7)
            start = self.rng.uniform(0, math.pi)
            points = []
            for index in range(corners):
                angle = start + 2 * math.pi * index / corners
                r = radius * self.rng.uniform(0.55, 1.15)
                points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            draw.polygon(self.scaled(points), fill=255)
        return self.density(mask, inner=150, cortex=196, depth=1.5)

    def fracture(
        self,
        layer: Image.Image,
        cut: Sequence[Point],
        toward: Point,
        pivot: Point,
        angle: float,
        dx: float,
        dy: float,
    ) -> Image.Image:
        """Fractură cu deplasare: partea dinspre ``toward`` se rotește și se mută."""
        kept, moved = self.split(layer, cut, toward)
        kept = self.crack(kept, cut, width=2.4)
        moved = self.crack(moved, cut, width=2.4)
        return ImageChops.add(kept, self.move(moved, pivot, angle, dx, dy))

    # --- compunere -------------------------------------------------------
    def render(self) -> Image.Image:
        size = (self.w, self.h)
        density = ImageChops.add(self.tissue, self.bone)
        density = ImageChops.add(density, Image.new("L", size, 3))
        density = density.filter(ImageFilter.GaussianBlur(0.9 * SCALE))

        # Expunerea filmului: 1 - e^(-densitate). Suprapunerile se luminează
        # treptat, fără să ardă în alb.
        k = 86.0
        norm = 1 - math.exp(-255 / k)
        image = density.point([int(255 * (1 - math.exp(-v / k)) / norm) for v in range(256)])

        # Difuzie: oasele luminoase „strălucesc” puțin în jur, ca pe negatoscop.
        glow = image.filter(ImageFilter.GaussianBlur(18 * SCALE)).point(lambda v: v * 12 // 100)
        image = ImageChops.add(image, glow)

        vignette = Image.radial_gradient("L").resize(size, Image.BILINEAR)
        vignette = vignette.point(lambda v: 255 - max(0, v - 110) * 100 // 145)
        image = ImageChops.multiply(image, vignette)

        grain = Image.effect_noise(size, 9)
        image = ImageChops.add(image, grain, 1.0, -128)
        image = image.resize((FILM_W, FILM_H), Image.LANCZOS)
        return ImageOps.colorize(image, black=(4, 6, 10), white=(236, 243, 251), mid=(100, 114, 132))


# ----------------------------------------------------------------------
# ZONE ANATOMICE
# ----------------------------------------------------------------------

# Conturul tibiei proximale în unități de „jumătate de lățime”: platoul
# lateral, cele două spine intercondiliene, platoul medial și metafiza.
_TIBIA_OUTLINE = [
    (-1.0, 0.125), (-0.93, 0.018), (-0.70, 0.036), (-0.36, 0.054), (-0.143, -0.075), (-0.089, 0.036),
    (0.018, -0.09), (0.089, 0.036), (0.375, 0.054), (0.73, 0.036), (0.93, 0.036), (1.0, 0.143),
    (0.95, 0.42), (0.76, 0.78), (0.57, 1.1), (0.47, 1.46), (0.446, 1.82),
    (-0.446, 1.82), (-0.47, 1.46), (-0.55, 1.1), (-0.74, 0.78), (-0.94, 0.42),
]


def _proximal_tibia(cx: float, top: float, half: float) -> list[Point]:
    """Platoul tibial cu cele două spine intercondiliene, văzut din față."""
    return _chaikin([(cx + u * half, top + v * half) for u, v in _TIBIA_OUTLINE], 3)


def _hand(film: _Film, state: str) -> Scene:
    """Mână dreaptă, incidență postero-anterioară: policele în stânga imaginii."""
    fingers = {
        # metacarpian, apoi falangele (bază -> vârf): (p0, p1, lățime corp, lățime capete)
        "I": [((200, 414), (150, 330), 17, 25), ((146, 324), (120, 262), 14, 21), ((117, 256), (104, 216), 12, 18)],
        "II": [((236, 404), (214, 262), 15, 24), ((212, 256), (199, 172), 13, 20), ((198, 166), (192, 118), 11, 17), ((191, 112), (187, 80), 9, 14)],
        "III": [((264, 402), (262, 248), 15, 25), ((262, 242), (260, 156), 13, 21), ((260, 150), (258, 96), 11, 17), ((258, 90), (257, 58), 9, 14)],
        "IV": [((292, 406), (308, 266), 13, 22), ((309, 260), (320, 178), 12, 19), ((321, 172), (327, 122), 10, 16), ((328, 116), (331, 86), 8, 13)],
        "V": [((318, 414), (346, 290), 13, 21), ((348, 284), (364, 218), 11, 17), ((365, 212), (373, 176), 9, 14), ((374, 170), (379, 146), 8, 12)],
    }

    def segment(p0: Point, p1: Point, shaft: float, ends: float, tuft: bool) -> list[Point]:
        profile = [(0.0, ends), (0.22, shaft * 1.1), (0.5, shaft), (0.78, shaft * 1.1), (1.0, ends * (0.92 if tuft else 1.0))]
        return _long_bone(p0, p1, profile, cap0=0.22, cap1=0.5 if tuft else 0.3)

    # Părți moi: palmă, degete, antebraț.
    tissue = film.mask(
        _chaikin([(178, 520), (172, 452), (160, 404), (130, 350), (114, 300), (130, 282), (178, 330), (206, 298), (226, 262), (302, 262), (356, 284), (370, 332), (354, 420), (350, 520)], 3),
        [(166, 640), (174, 500), (352, 500), (362, 640)],
    )
    for chain in fingers.values():
        points = [chain[0][1]] + [bone[1] for bone in chain[1:]]
        tissue = ImageChops.lighter(tissue, film.stroke_mask(points, chain[1][3] + 22))
    film.add_tissue(tissue, value=62, edge=4, thickness=30)

    # Antebraț: radius (cu stiloida radială) și ulna.
    radius = _chaikin([(194, 660), (190, 600), (185, 548), (180, 516), (186, 492), (204, 484), (226, 488), (248, 494), (262, 500), (264, 518), (252, 550), (240, 600), (240, 660)], 2)
    film.add_bone(film.bone_shape(radius, depth=5))
    ulna = _long_bone((316, 660), (304, 494), [(0, 30), (0.6, 28), (0.88, 34), (1, 40)], cap0=0.1, cap1=0.4)
    film.add_bone(film.bone_shape(ulna, film.blob(322, 497, 5, 9, -15), depth=4.5))

    # Oasele carpiene, strânse în două rânduri.
    carpals = [
        (213, 462, 27, 15, -40), (253, 468, 20, 18, 0), (289, 462, 18, 15, 25), (302, 450, 10, 10, 0),
        (203, 430, 18, 17, -30), (228, 420, 14, 15, -10), (256, 426, 17, 25, 0), (287, 428, 18, 23, 15),
    ]
    for cx, cy, rx, ry, angle in carpals:
        film.add_bone(film.bone_shape(film.blob(cx, cy, rx, ry, angle, 0.08), inner=108, cortex=176, depth=3))
    for cx, cy in ((144, 334), (156, 339)):
        film.add_bone(film.bone_shape(_ellipse(cx, cy, 5, 5), inner=120, cortex=160, depth=1.5))

    # Metacarpiene și falange. Degetul mic (V) e pe un strat separat: acolo e leziunea.
    for name, chain in fingers.items():
        if name == "V":
            continue
        for index, (p0, p1, shaft, ends) in enumerate(chain):
            tuft = index == len(chain) - 1 and index > 0
            film.add_bone(film.bone_shape(segment(p0, p1, shaft, ends, tuft), depth=4.5 if index == 0 else 3.5))

    target = film.blank()
    for index, (p0, p1, shaft, ends) in enumerate(fingers["V"]):
        tuft = index == len(fingers["V"]) - 1
        target = ImageChops.add(target, film.bone_shape(segment(p0, p1, shaft, ends, tuft), depth=4.5 if index == 0 else 3.5))

    scene = Scene(marker=(452, 96), px_per_cm=24)
    base, head = fingers["V"][0][0], fingers["V"][0][1]
    site = _lerp(base, head, 0.72)
    length = math.hypot(head[0] - base[0], head[1] - base[1])
    ux, uy = (head[0] - base[0]) / length, (head[1] - base[1]) / length
    nx, ny = uy, -ux  # perpendicular pe metacarpian
    if state == "normala":
        film.swelling(site, 34, 44, 22)
    elif state == "rea":
        cut = film.jagged((site[0] - nx * 9 - ux * 3, site[1] - ny * 9 - uy * 3), (site[0] + nx * 5 + ux * 2, site[1] + ny * 5 + uy * 2), 7, 1.6)
        target = film.crack(target, cut, width=1.8, strength=235)
        film.swelling(site, 38, 48, 32)
        scene.lesions.append(Lesion(site, 26, "FISURĂ"))
    elif state == "grava":
        cut = film.jagged((site[0] - nx * 16 - ux * 5, site[1] - ny * 16 - uy * 5), (site[0] + nx * 16 + ux * 5, site[1] + ny * 16 + uy * 5), 8, 2.6)
        target = film.fracture(target, cut, toward=head, pivot=site, angle=9, dx=-3, dy=8)
        target = ImageChops.add(target, film.fragments((site[0] + 5, site[1] + 3), 4, 9, 4.5))
        film.swelling(site, 46, 58, 44)
        scene.lesions.append(Lesion((site[0] - 2, site[1] - 2), 36, "FRACTURĂ"))
    film.add_bone(target)
    return scene


def _leg(film: _Film, state: str) -> Scene:
    """Gambă dreaptă (tibie și fibulă), incidență antero-posterioară: fibula în stânga imaginii."""
    outline = _chaikin([(120, -20), (430, -20), (446, 150), (414, 330), (366, 520), (372, 640), (160, 640), (170, 520), (118, 330), (104, 150)], 3)
    film.add_tissue(film.mask(outline), value=60, edge=5, thickness=60)

    # Femurul distal, tăiat de marginea de sus, și talusul, jos.
    femur = _chaikin([(222, -40), (322, -40), (332, 0), (352, 14), (358, 38), (334, 52), (300, 50), (284, 40), (272, 34), (260, 40), (244, 50), (208, 52), (186, 38), (190, 12), (212, 0)], 2)
    film.add_bone(film.bone_shape(femur, depth=6))
    film.add_bone(film.bone_shape(_chaikin([(212, 640), (208, 606), (228, 586), (268, 578), (310, 586), (330, 610), (328, 640)], 3), depth=5))

    tibia = [
        _proximal_tibia(276, 72, 76),
        _long_bone((275, 160), (270, 572), [(0, 68), (0.1, 58), (0.75, 52), (0.9, 66), (1, 92)], cap0=0.0, cap1=0.12),
        _chaikin([(292, 500), (312, 532), (322, 566), (318, 592), (306, 594), (298, 570)], 2),
    ]
    fibula = _long_bone((194, 104), (216, 604), [(0, 40), (0.07, 34), (0.15, 21), (0.85, 20), (0.95, 30), (1, 34)], cap0=0.5, cap1=0.45)

    tibia_layer = film.bone_shape(*tibia, depth=6)
    fibula_layer = film.bone_shape(fibula, depth=3.5)

    scene = Scene(marker=(60, 232), px_per_cm=14)
    site = (272, 330)
    if state == "normala":
        film.swelling(site, 70, 64, 18)
    elif state == "rea":
        cut = film.jagged((244, 318), (284, 342), 8, 2.2)
        tibia_layer = film.crack(tibia_layer, cut, width=1.9, strength=235)
        film.swelling(site, 76, 70, 28)
        scene.lesions.append(Lesion((266, 330), 34, "FISURĂ"))
    elif state == "grava":
        target = ImageChops.add(tibia_layer, fibula_layer)
        cut = film.jagged((158, 392), (338, 298), 14, 5.0)
        target = film.fracture(target, cut, toward=(270, 560), pivot=(268, 330), angle=7, dx=18, dy=-16)
        target = ImageChops.add(target, film.fragments((278, 326), 5, 14, 6))
        film.add_bone(target)
        film.swelling((262, 338), 96, 84, 36)
        scene.lesions.append(Lesion((250, 334), 62, "FRACTURĂ"))
        return scene
    film.add_bone(tibia_layer)
    film.add_bone(fibula_layer)
    return scene


def _knee(film: _Film, state: str) -> Scene:
    """Genunchi drept, incidență antero-posterioară: capul fibulei în stânga imaginii."""
    outline = _chaikin([(96, -20), (446, -20), (440, 160), (430, 300), (424, 420), (426, 640), (116, 640), (112, 420), (106, 300), (98, 160)], 3)
    film.add_tissue(film.mask(outline), value=60, edge=5, thickness=70)

    femur = _chaikin([
        (222, -80), (316, -80), (318, 60), (326, 120), (346, 170), (366, 210), (378, 246), (378, 280), (364, 300),
        (334, 306), (306, 298), (290, 280), (268, 270), (246, 280), (232, 298), (204, 304), (174, 300), (158, 282),
        (156, 248), (166, 212), (188, 170), (210, 120), (218, 60),
    ], 3)
    film.add_bone(film.bone_shape(femur, depth=6))
    patella_layer = film.bone_shape(film.blob(270, 222, 46, 56, 0, 0.04), inner=40, cortex=70, depth=5)

    tibia = [_proximal_tibia(268, 326, 112), _long_bone((268, 500), (270, 700), [(0, 102), (0.4, 94), (1, 92)], cap0=0.0, cap1=0.0)]
    tibia_layer = film.bone_shape(*tibia, depth=6)

    fibula = _long_bone((172, 364), (186, 700), [(0, 50), (0.08, 44), (0.2, 26), (1, 24)], cap0=0.55, cap1=0.1)
    film.add_bone(film.bone_shape(fibula, inner=92, cortex=160, depth=3.5))

    scene = Scene(marker=(58, 120), px_per_cm=22)
    if state == "normala":
        film.swelling((268, 286), 150, 96, 18)
    elif state == "rea":
        cut = film.jagged((208, 330), (164, 402), 9, 2.4)
        tibia_layer = film.crack(tibia_layer, cut, width=1.9, strength=235)
        film.swelling((250, 300), 150, 100, 26)
        scene.lesions.append(Lesion((190, 362), 44, "FISURĂ"))
    elif state == "grava":
        cut = film.jagged((238, 330), (152, 416), 10, 3.0)
        tibia_layer = film.fracture(tibia_layer, cut, toward=(170, 330), pivot=(200, 360), angle=-5, dx=-6, dy=14)
        tibia_layer = film.crack(tibia_layer, film.jagged((196, 340), (176, 388), 5, 2.0), width=1.6)
        tibia_layer = ImageChops.add(tibia_layer, film.fragments((214, 346), 4, 12, 6))
        patella_cut = film.jagged((214, 224), (328, 212), 10, 2.6)
        patella_layer = film.fracture(patella_layer, patella_cut, toward=(270, 280), pivot=(270, 220), angle=-4, dx=0, dy=14)
        film.swelling((262, 300), 176, 120, 36)
        scene.lesions.append(Lesion((194, 364), 58, "FRACTURĂ"))
        scene.lesions.append(Lesion((270, 228), 58, "FRACTURĂ ROTULĂ"))
    film.add_bone(tibia_layer)
    film.add_bone(patella_layer)
    return scene


def _skull(film: _Film, state: str) -> Scene:
    """Craniu, incidență postero-anterioară: partea dreaptă a pacientului în stânga imaginii."""
    head = _ellipse(260, 226, 224, 226)
    face = _chaikin([(122, 350), (398, 350), (404, 460), (366, 548), (306, 590), (214, 590), (154, 548), (116, 460)], 3)
    neck = [(196, 560), (324, 560), (338, 640), (182, 640)]
    film.add_tissue(film.mask(head, face, neck), value=50, edge=5, thickness=70)

    # Bolta craniană (ușor mai îngustă jos), pe strat separat: aici apare fractura.
    outline = []
    for index in range(72):
        t = 2 * math.pi * index / 72
        narrow = 1 - 0.07 * max(0.0, math.sin(t))
        outline.append((260 + 204 * math.cos(t) * narrow, 214 + 200 * math.sin(t)))
    vault = film.bone_shape(outline, inner=64, cortex=196, depth=6)
    # Arcul de jos al bolții se pierde în spatele bazei craniului și al feței.
    base = film.mask(_ellipse(260, 440, 158, 96)).filter(ImageFilter.GaussianBlur(26 * SCALE))
    vault = ImageChops.multiply(vault, ImageOps.invert(base))
    for p0, p1 in (((260, 16), (260, 132)), ((148, 90), (206, 46)), ((372, 90), (314, 46))):
        vault = film.crack(vault, film.jagged(p0, p1, 16, 2.2), width=1.1, strength=30)
    # Șanțurile vasculare (artera meningee mijlocie), ramificate pe laterale.
    for side in (-1, 1):
        trunk = film.jagged((260 + side * 170, 300), (260 + side * 138, 170), 8, 3.0)
        vault = film.crack(vault, trunk, width=1.6, strength=22)
        vault = film.crack(vault, film.jagged(trunk[4], (260 + side * 92, 150), 6, 2.5), width=1.2, strength=18)

    bones = film.blank()

    def add(layer: Image.Image) -> None:
        nonlocal bones
        bones = ImageChops.add(bones, layer)

    # Orbitele: margine fină, puțin înclinată spre lateral, și liniile oblice (innominate).
    for cx, side in ((194, -1), (326, 1)):
        outer = _chaikin([(cx - 48, 272), (cx - 18, 252), (cx + 22, 254), (cx + 48, 276), (cx + 46 + side * 4, 318), (cx + 16, 342), (cx - 20, 342), (cx - 46 - side * 4, 318)], 3)
        inner = _chaikin([(cx - 38, 278), (cx - 14, 263), (cx + 18, 264), (cx + 38, 281), (cx + 36 + side * 4, 314), (cx + 12, 332), (cx - 16, 332), (cx - 36 - side * 4, 314)], 3)
        add(film.bone_shape(outer, holes=[inner], inner=34, cortex=62, depth=2))
        oblique = [(cx + side * 30, 262), (cx + side * 36, 296), (cx + side * 42, 332)]
        add(film.density(film.stroke_mask(oblique, 4), inner=36, cortex=52, depth=1.5))
    # Stânca temporalului traversează treimea inferioară a orbitelor.
    for points in (((132, 338), (170, 328), (212, 324)), ((388, 338), (350, 328), (308, 324))):
        add(film.density(film.stroke_mask(_chaikin(points, 2, False), 7), inner=34, cortex=52, depth=2))
    # Oasele zigomatice și apofizele mastoide (zone luminoase difuze).
    for cx in (150, 370):
        add(film.bone_shape(film.blob(cx, 362, 26, 34, 0, 0.12), inner=22, cortex=30, depth=8))
    for cx in (114, 406):
        add(film.bone_shape(film.blob(cx, 404, 11, 17), inner=24, cortex=38, depth=4))
    # Maxilarul (procesul alveolar), palatul dur, septul nazal și cornetele.
    add(film.bone_shape(_box(260, 444, 148, 34, 14), inner=38, cortex=54, depth=5))
    add(film.density(film.stroke_mask([(208, 430), (312, 430)], 7), inner=60, cortex=84, depth=2))
    add(film.density(film.stroke_mask([(260, 332), (260, 426)], 4), inner=48, cortex=62, depth=1))
    for cx in (242, 278):
        add(film.bone_shape(_ellipse(cx, 398, 7, 17), inner=26, cortex=36, depth=3))
    # Dintele axisului și atlasul, suprapuse peste mandibulă.
    add(film.bone_shape(_box(260, 522, 48, 104, 14), inner=26, cortex=40, depth=5))

    # Mandibula: ramurile pe laterale, unghiurile, corpul și bărbia.
    jaw = film.stroke_mask(_chaikin([(120, 478), (170, 528), (260, 556), (350, 528), (400, 478)], 2, closed=False), 26)
    for side in (-1, 1):
        ramus = _chaikin([(260 + side * 146, 366), (260 + side * 152, 420), (260 + side * 142, 470), (260 + side * 136, 482)], 2, closed=False)
        jaw = ImageChops.lighter(jaw, film.stroke_mask(ramus, 17))
    add(film.density(jaw, inner=62, cortex=160, depth=3))
    add(film.bone_shape(film.blob(260, 544, 28, 14), inner=44, cortex=70, depth=4))

    # Dinții se suprapun într-o bandă densă, cu striații verticale fine.
    teeth = film.blank()
    for index in range(16):
        x = 204 + index * 7.5
        tilt = (index - 7.5) * 1.4
        teeth = ImageChops.add(teeth, film.bone_shape(_box(x, 452, 11, 28, 5, tilt), inner=62, cortex=92, depth=1.2, texture=False))
        teeth = ImageChops.add(teeth, film.bone_shape(_box(x, 480, 10.5, 28, 5, -tilt), inner=62, cortex=92, depth=1.2, texture=False))
    add(teeth.filter(ImageFilter.GaussianBlur(1.5 * SCALE)))

    # Aer: sinusurile frontale și maxilare, celulele etmoidale, fosele nazale, orbitele.
    ethmoid = [_ellipse(250 + dx, 280 + dy, 5, 6) for dx in (-6, 6, 18) for dy in (-10, 6, 22)]
    air = film.mask(
        _chaikin([(232, 246), (228, 220), (242, 204), (258, 214), (272, 200), (290, 214), (292, 244)], 3),
        _chaikin([(248, 332), (234, 382), (230, 420), (260, 428), (290, 420), (286, 382), (272, 332)], 3),
        film.blob(204, 382, 36, 34, 8),
        film.blob(316, 382, 36, 34, -8),
        _box(192, 302, 74, 60, 26, -6),
        _box(328, 302, 74, 60, 26, 6),
        *ethmoid,
    )

    scene = Scene(marker=(40, 470), px_per_cm=28)
    site = (142, 150)
    if state == "normala":
        film.swelling((84, 140), 52, 48, 24)
    elif state == "rea":
        vault = film.crack(vault, film.jagged((94, 104), (196, 202), 12, 4.0), width=2.0, strength=225)
        vault = film.crack(vault, film.jagged((150, 156), (130, 200), 5, 2.4), width=1.5, strength=190)
        film.swelling((86, 140), 58, 54, 30)
        scene.lesions.append(Lesion((146, 154), 64, "FRACTURĂ"))
    elif state == "grava":
        fragment = []
        for index in range(14):
            angle = 2 * math.pi * index / 14
            r = film.rng.uniform(0.82, 1.16)
            fragment.append((site[0] + 44 * r * math.cos(angle), site[1] + 38 * r * math.sin(angle)))
        kept, moved = film.region(vault, fragment)
        kept = film.crack(kept, fragment + [fragment[0]], width=2.2)
        moved = film.crack(moved, film.jagged((site[0] - 30, site[1] - 8), (site[0] + 28, site[1] + 10), 7, 3.0), width=1.8)
        vault = ImageChops.add(kept, film.move(moved, site, angle=9, dx=10, dy=8))
        for angle in (200, 250, 300, 20, 120):
            rad = math.radians(angle)
            start = (site[0] + 46 * math.cos(rad), site[1] + 40 * math.sin(rad))
            length = film.rng.uniform(34, 70)
            end = (start[0] + length * math.cos(rad), start[1] + length * math.sin(rad))
            vault = film.crack(vault, film.jagged(start, end, 6, 3.0), width=1.8, strength=225)
        vault = ImageChops.add(vault, film.fragments((site[0] + 8, site[1] + 6), 4, 20, 6))
        film.swelling((78, 136), 66, 62, 44)
        scene.lesions.append(Lesion((site[0] + 4, site[1] + 4), 76, "FRACTURĂ"))

    film.add_bone(vault)
    film.add_bone(bones)
    film.remove_bone(air, 40)
    return scene


def _cervical(film: _Film, state: str) -> Scene:
    """Coloană cervicală, incidență laterală: fața pacientului spre stânga imaginii."""
    outline = _chaikin([(40, -20), (520, -20), (470, 120), (446, 330), (470, 500), (540, 560), (540, 640), (-20, 640), (-20, 560), (96, 500), (118, 330), (102, 170), (58, 110)], 3)
    film.add_tissue(film.mask(outline), value=58, edge=5, thickness=70)
    film.add_tissue(film.mask(_chaikin([(-20, 548), (540, 530), (540, 640), (-20, 640)], 2)), value=36, edge=12, thickness=40)

    # Baza craniului, mandibula, osul hioid.
    film.add_bone(film.bone_shape(_chaikin([(296, -20), (540, -20), (540, 56), (452, 88), (384, 76), (330, 44)], 3), inner=92, cortex=170, depth=8))
    jaw = _chaikin([(184, -20), (176, 50), (160, 104), (110, 124), (30, 132)], 2, closed=False)
    film.add_bone(film.density(film.stroke_mask(jaw, 24), inner=100, cortex=176, depth=4))
    film.add_bone(film.density(film.stroke_mask([(128, 194), (176, 180)], 8), inner=96, cortex=150, depth=2))

    # C1 (arcul anterior și cel posterior) și C2 cu dintele axisului.
    film.add_bone(film.bone_shape(film.blob(212, 106, 11, 15), inner=110, cortex=180, depth=3))
    film.add_bone(film.bone_shape(_ellipse(292, 104, 30, 14), inner=50, cortex=80, depth=4))
    film.add_bone(film.bone_shape(_long_bone((334, 102), (400, 96), [(0, 18), (0.5, 12), (1, 20)], 0.3, 0.6), inner=100, cortex=170, depth=3))
    axis_body = _chaikin([(228, 204), (226, 150), (240, 134), (247, 98), (256, 86), (265, 98), (272, 132), (292, 146), (296, 204), (262, 210)], 2)
    film.add_bone(film.bone_shape(axis_body, depth=6))
    film.add_bone(film.bone_shape(_chaikin([(298, 154), (332, 150), (402, 170), (404, 190), (334, 194), (298, 190)], 2), inner=100, cortex=170, depth=4))

    # C3–C7 și T1. Lordoza e mai dreaptă la „normala” (contractură musculară).
    curvature = 0.35 if state == "normala" else 1.0
    lordosis = [0, -4, -4, 0, 8, 18]
    tilts = [5, 2, 0, -3, -6, -8]
    rows = [(258, 238), (256, 298), (256, 358), (258, 418), (262, 478), (268, 538)]

    scene = Scene(marker=(40, 250), px_per_cm=20)
    for index, ((base_x, cy), tilt) in enumerate(zip(rows, tilts)):
        level = index + 3
        cx = base_x + lordosis[index] * curvature - 4 * (1 - curvature)
        w = 66 + index * 1.6
        h = 44 + index * 1.0
        body = _box(cx, cy, w, h, 9, tilt)
        layer = film.bone_shape(body, depth=6)

        # Masivul articular, lama și apofiza spinoasă, spre dreapta imaginii.
        right = cx + w / 2
        pillar = _chaikin([(right + 2, cy - h / 2 - 6), (right + 44, cy - h / 2 + 4), (right + 50, cy + h / 2 + 14), (right + 6, cy + h / 2 + 4)], 2)
        pedicle = _box(right + 2, cy - 2, 16, h * 0.6, 5)
        spine_len = 40 + index * 7 + (14 if level == 7 else 0)
        spinous = _long_bone((right + 40, cy + 4), (right + 40 + spine_len, cy + 22 + index * 2), [(0, 22), (0.6, 12), (1, 16)], cap0=0.2, cap1=0.6)
        posterior = film.bone_shape(pillar, pedicle, spinous, inner=70, cortex=150, depth=3)

        if level == 5 and state == "rea":
            cut = film.jagged((cx - w / 2 + 4, cy - h / 2 + 6), (cx + w / 2 - 10, cy + h / 2 - 4), 8, 2.2)
            layer = film.crack(layer, cut, width=1.9, strength=235)
            scene.lesions.append(Lesion((cx, cy), 42, "FISURĂ"))
        elif level == 5 and state == "grava":
            # Tasare anterioară în pană + deplasare înainte + fragment „în lacrimă”.
            wedge = _chaikin([(cx - w / 2 - 20, cy - h / 2 + 14), (cx + w / 2 - 16, cy - h / 2 + 2), (cx + w / 2 - 16, cy + h / 2), (cx - w / 2 - 22, cy + h / 2 - 4)], 2)
            layer = film.bone_shape(wedge, inner=130, cortex=200, depth=5)
            layer = film.crack(layer, film.jagged((cx - w / 2 - 14, cy - 2), (cx + w / 2 - 22, cy + 8), 8, 2.6), width=2.0)
            teardrop = _chaikin([(cx - w / 2 - 20, cy + h / 2 + 2), (cx - w / 2 - 6, cy + h / 2 - 4), (cx - w / 2 - 12, cy + h / 2 + 12)], 2)
            layer = ImageChops.add(layer, film.bone_shape(teardrop, inner=140, cortex=196, depth=1.5))
            posterior = film.move(posterior, (cx, cy), angle=0, dx=-12, dy=-4)
            film.add_tissue(film.mask(_chaikin([(190, 270), (222, 270), (226, 440), (192, 440)], 3)), value=44, edge=8, thickness=20)
            scene.lesions.append(Lesion((cx - 12, cy + 4), 54, "FRACTURĂ"))
        film.add_bone(layer)
        film.add_bone(posterior)

    # Căile aeriene (faringe + trahee) sunt mai negre decât părțile moi.
    airway = _chaikin([(142, 40), (172, 40), (178, 250), (192, 320), (196, 400), (190, 640), (158, 640), (162, 400), (156, 320), (146, 250)], 3)
    film.remove_tissue(film.mask(airway), 40)
    return scene


ZONES: dict[str, Callable[[_Film, str], Scene]] = {
    "mana": _hand,
    "picior": _leg,
    "cap": _skull,
    "gat": _cervical,
    "genunchi": _knee,
}


# ----------------------------------------------------------------------
# TEXTE PE FILM, MARKER, RIGLĂ, ADNOTĂRI
# ----------------------------------------------------------------------

OVERLAY = (196, 212, 226)
LESION = (240, 78, 56)


def _text(draw: ImageDraw.ImageDraw, xy: Point, text: str, size: int = 12, bold: bool = False, fill=OVERLAY, anchor: str = "la") -> None:
    draw.text(xy, text, font=_font(bold, size), fill=fill, anchor=anchor, stroke_width=2, stroke_fill=(0, 0, 0))


def _overlays(image: Image.Image, scene: Scene, corners: dict[str, Sequence[str]]) -> None:
    draw = ImageDraw.Draw(image)
    line_h = 16
    for index, line in enumerate(corners.get("top_left", ())):
        _text(draw, (12, 10 + index * line_h), line, bold=index == 0)
    for index, line in enumerate(corners.get("top_right", ())):
        _text(draw, (FILM_W - 12, 10 + index * line_h), line, bold=index == 0, anchor="ra")
    bottom_left = list(corners.get("bottom_left", ()))
    for index, line in enumerate(bottom_left):
        _text(draw, (12, FILM_H - 12 - (len(bottom_left) - index) * line_h + 4), line)
    bottom_right = list(corners.get("bottom_right", ()))
    for index, line in enumerate(bottom_right):
        _text(draw, (FILM_W - 12, FILM_H - 12 - (len(bottom_right) - index) * line_h + 4), line, anchor="ra")

    # Rigla pe marginea din dreapta: gradații la 0,5 cm, mai lungi la fiecare 1 cm și 5 cm.
    x = FILM_W - 16
    top = 170
    half_cm = scene.px_per_cm / 2
    count = int(280 // half_cm)
    bottom = top + count * half_cm
    draw.line((x, top, x, bottom), fill=OVERLAY, width=1)
    for index in range(count + 1):
        y = top + index * half_cm
        length = 10 if index % 10 == 0 else (6 if index % 2 == 0 else 3)
        draw.line((x - length, y, x, y), fill=OVERLAY, width=1)
    _text(draw, (x - 2, bottom + 6), "cm", size=10, anchor="ra")

    # Markerul de lateralitate (litera de plumb „D” = dreapta).
    mx, my = scene.marker
    draw.rounded_rectangle((mx - 14, my - 16, mx + 14, my + 16), radius=3, outline=(232, 238, 246), width=2)
    draw.text((mx, my + 1), "D", font=_font(True, 20), fill=(240, 244, 250), anchor="mm")

    for lesion in scene.lesions:
        cx, cy = lesion.center
        r = lesion.radius
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=LESION, width=3)
        # Eticheta leziunii, cu linie de legătură spre cerc.
        label_font = _font(True, 12)
        width = label_font.getlength(lesion.label)
        on_right = cx + r + 26 + width < FILM_W - 30
        lx = cx + r + 26 if on_right else cx - r - 26 - width
        ly = max(84, min(FILM_H - 110, cy - r - 6))
        edge_x = cx + r * 0.72 if on_right else cx - r * 0.72
        anchor_x = lx - 4 if on_right else lx + width + 4
        draw.line((edge_x, cy - r * 0.69, anchor_x, ly + 7), fill=LESION, width=2)
        draw.text((lx, ly), lesion.label, font=label_font, fill=LESION, stroke_width=2, stroke_fill=(0, 0, 0))


def render_film(
    zone: str,
    state: str,
    corners: Optional[dict[str, Sequence[str]]] = None,
    seed: int = 0,
) -> Image.Image:
    """Imaginea RGB (FILM_W × FILM_H) a radiografiei pentru ``zone`` și ``state``."""
    film = _Film(seed)
    scene = ZONES[zone](film, state)
    image = film.render()
    _overlays(image, scene, corners or {})
    return image
