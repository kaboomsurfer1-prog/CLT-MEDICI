"""Generarea documentelor oficiale (imagini PNG) pentru Legacy EMS.

Sunt patru documente:

* ``render_contract``     -> Contract Individual de Muncă (angajare)
* ``render_termination``  -> Decizie de Încetare a Contractului (demisie acceptată)
* ``render_radiography``  -> Buletin de Investigație Radiologică (cu filmul radiografiei)
* ``render_lab_results``  -> Buletin de Analize Medicale

Toate folosesc aceeași "hârtie oficială": ramă, antet cu cele două logo-uri,
corp de text în română, casete de semnătură și ștampilă rotundă.
"""

from __future__ import annotations

import io
import math
import random
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import medical
import xray

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "assets" / "fonts"

# A4 la 150 DPI
WIDTH = 1240
HEIGHT = 1754

PAPER = (248, 245, 237)
PAPER_SHADE = (238, 233, 221)
INK = (26, 32, 44)
MUTED = (99, 110, 126)
BLUE = (22, 60, 110)
RED = (170, 30, 40)
GOLD = (176, 141, 62)
LINE = (188, 182, 168)

FONT_FILES = {
    "sans": "DejaVuSans.ttf",
    "sans_bold": "DejaVuSans-Bold.ttf",
    "serif": "DejaVuSerif.ttf",
    "serif_bold": "DejaVuSerif-Bold.ttf",
    "serif_italic": "DejaVuSerif-Italic.ttf",
    "script": "GreatVibes-Regular.ttf",
}

SYSTEM_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@lru_cache(maxsize=128)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / FONT_FILES.get(name, FONT_FILES["sans"])
    if path.exists():
        return ImageFont.truetype(str(path), size)
    for fallback in SYSTEM_FALLBACKS:
        if Path(fallback).exists():
            return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


# ----------------------------------------------------------------------
# HELPERE TEXT
# ----------------------------------------------------------------------

def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(font.getlength(text))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _text_width(candidate, font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _shrink_to_fit(text: str, name: str, max_width: int, start_size: int, min_size: int = 12) -> ImageFont.FreeTypeFont:
    size = start_size
    font = _font(name, size)
    while size > min_size and _text_width(text, font) > max_width:
        size -= 1
        font = _font(name, size)
    return font


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if _text_width(text, font) <= max_width:
        return text
    while text and _text_width(text + "…", font) > max_width:
        text = text[:-1]
    return text + "…"


def _spaced(text: str, spacing: str = " ") -> str:
    return spacing.join(text)


def _draw_paragraph_clamped(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font_name: str,
    fill,
    max_width: int,
    max_height: int,
    start_size: int = 20,
    min_size: int = 13,
    line_ratio: float = 1.45,
) -> int:
    """Scrie un paragraf care nu depășește niciodată ``max_height``.

    Micșorează fontul cât este nevoie, iar dacă tot nu încape taie textul.
    """
    size = start_size
    font = _font(font_name, size)
    line_height = max(1, int(size * line_ratio))
    lines = _wrap(text, font, max_width)
    while size > min_size and len(lines) * line_height > max_height:
        size -= 1
        font = _font(font_name, size)
        line_height = max(1, int(size * line_ratio))
        lines = _wrap(text, font, max_width)

    max_lines = max(1, max_height // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1] + " …", font, max_width)

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _draw_paragraph(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
    max_width: int,
    line_height: int,
    align: str = "left",
    center_x: Optional[int] = None,
) -> int:
    for line in _wrap(text, font, max_width):
        if align == "center":
            draw.text((center_x if center_x is not None else x + max_width // 2, y), line, font=font, fill=fill, anchor="ma")
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


# ----------------------------------------------------------------------
# HÂRTIE, RAMĂ, ȘTAMPILĂ
# ----------------------------------------------------------------------

def _paper(width: int, height: int, seed: int = 7) -> Image.Image:
    base = Image.new("RGB", (width, height), PAPER)

    # Vignetare discretă spre margini pentru aspect de hârtie reală.
    shade = Image.new("L", (width // 8, height // 8), 0)
    shade_draw = ImageDraw.Draw(shade)
    shade_draw.rectangle(
        (12, 12, shade.width - 12, shade.height - 12),
        fill=255,
    )
    shade = shade.filter(ImageFilter.GaussianBlur(14)).resize((width, height), Image.BILINEAR)
    base = Image.composite(base, Image.new("RGB", (width, height), PAPER_SHADE), shade)

    # Fibre de hârtie: zgomot foarte fin.
    rng = random.Random(seed)
    noise = Image.new("L", (width // 2, height // 2))
    noise.putdata([rng.randint(118, 138) for _ in range(noise.width * noise.height)])
    noise = noise.resize((width, height), Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.6))
    base = Image.blend(base, Image.merge("RGB", (noise, noise, noise)), 0.05)
    return base


def _frame(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((30, 30, WIDTH - 31, HEIGHT - 31), outline=GOLD, width=4)
    draw.rectangle((44, 44, WIDTH - 45, HEIGHT - 45), outline=BLUE, width=1)
    draw.rectangle((50, 50, WIDTH - 51, HEIGHT - 51), outline=(205, 199, 184), width=1)

    # Colțuri decorative
    for cx, cy, sx, sy in ((44, 44, 1, 1), (WIDTH - 45, 44, -1, 1), (44, HEIGHT - 45, 1, -1), (WIDTH - 45, HEIGHT - 45, -1, -1)):
        draw.line((cx, cy + 26 * sy, cx + 26 * sx, cy), fill=RED, width=3)


def _arc_text(
    layer: Image.Image,
    cx: float,
    cy: float,
    radius: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
    center_deg: float,
    total_deg: float,
    bottom: bool = False,
) -> None:
    """Scrie textul curbat pe un cerc. ``center_deg``: 270 = sus, 90 = jos."""
    chars = list(text)
    if not chars:
        return
    step = total_deg / len(chars)
    if bottom:
        chars.reverse()
    start = center_deg - total_deg / 2 + step / 2
    tile_size = font.size * 3
    for index, char in enumerate(chars):
        angle = start + index * step
        rad = math.radians(angle)
        x = cx + radius * math.cos(rad)
        y = cy + radius * math.sin(rad)
        tile = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((tile_size / 2, tile_size / 2), char, font=font, fill=fill, anchor="mm")
        rotation = -(angle - 90) if bottom else -(angle + 90)
        tile = tile.rotate(rotation, resample=Image.BICUBIC, center=(tile_size / 2, tile_size / 2))
        layer.alpha_composite(tile, (int(x - tile_size / 2), int(y - tile_size / 2)))


def _seal(
    size: int,
    top_text: str,
    bottom_text: str,
    center_lines: Sequence[str],
    color=(168, 32, 44),
    tilt: float = -9.0,
) -> Image.Image:
    """Ștampilă rotundă, ușor înclinată, cu aspect de tuș."""
    scale = 2
    box = size * scale
    layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    center = box / 2
    ink = color + (235,)

    draw.ellipse((6, 6, box - 7, box - 7), outline=ink, width=5 * scale)
    draw.ellipse((22 * scale // 2 + 6, 22 * scale // 2 + 6, box - 7 - 22 * scale // 2, box - 7 - 22 * scale // 2), outline=ink, width=2 * scale)

    arc_radius = center - 26 * scale
    max_span = 196.0

    def arc_font_for(text: str) -> tuple[ImageFont.FreeTypeFont, float]:
        """Alege dimensiunea literelor astfel încât textul să încapă pe arc."""
        size = int(13.5 * scale)
        while size > 6:
            font = _font("sans_bold", size)
            span = math.degrees(font.getlength(text) * 1.10 / arc_radius)
            if span <= max_span:
                return font, max(60.0, span)
            size -= 1
        font = _font("sans_bold", 6)
        return font, max_span

    top_font, top_span = arc_font_for(top_text)
    bottom_font, bottom_span = arc_font_for(bottom_text)
    _arc_text(layer, center, center, arc_radius, top_text, top_font, ink, 270, top_span)
    _arc_text(layer, center, center, arc_radius, bottom_text, bottom_font, ink, 90, bottom_span, bottom=True)

    # Stelele laterale
    star_font = _font("sans_bold", int(16 * scale))
    for angle in (0, 180):
        rad = math.radians(angle)
        sx = center + (center - 27 * scale) * math.cos(rad)
        sy = center + (center - 27 * scale) * math.sin(rad)
        draw.text((sx, sy), "★", font=star_font, fill=ink, anchor="mm")

    inner_r = center - 44 * scale
    draw.ellipse((center - inner_r, center - inner_r, center + inner_r, center + inner_r), outline=ink, width=2 * scale)

    total = len(center_lines)
    line_h = int(17 * scale)
    start_y = center - (total - 1) * line_h / 2
    for index, line in enumerate(center_lines):
        font = _shrink_to_fit(line, "sans_bold", int(inner_r * 1.7), int(16 * scale), 8)
        draw.text((center, start_y + index * line_h), line, font=font, fill=ink, anchor="mm")

    layer = layer.resize((size, size), Image.LANCZOS)
    layer = layer.rotate(tilt, resample=Image.BICUBIC, expand=True)
    return _ink(layer)


def _ink(layer: Image.Image, seed: int = 11) -> Image.Image:
    """Aspect de tuș: alpha neuniform, ca la o ștampilă apăsată pe hârtie."""
    alpha = layer.getchannel("A")
    rng = random.Random(seed)
    grain = Image.new("L", (layer.width // 3 or 1, layer.height // 3 or 1))
    grain.putdata([rng.randint(150, 255) for _ in range(grain.width * grain.height)])
    grain = grain.resize(layer.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2))
    layer.putalpha(Image.eval(Image.blend(alpha, Image.composite(alpha, Image.new("L", layer.size, 0), grain), 0.55), lambda v: int(v * 0.92)))
    return layer


# ----------------------------------------------------------------------
# LOGO-URI
# ----------------------------------------------------------------------

def _strip_border_background(image: Image.Image) -> Image.Image:
    """Elimină fundalul alb conectat la margini (logo-uri pe fundal alb)."""
    rgb = image.convert("RGB")
    sentinel = (255, 0, 254)
    corners = ((0, 0), (rgb.width - 1, 0), (0, rgb.height - 1), (rgb.width - 1, rgb.height - 1))
    touched = False
    for corner in corners:
        pixel = rgb.getpixel(corner)
        if min(pixel) > 232 and max(pixel) - min(pixel) < 16:
            ImageDraw.floodfill(rgb, corner, sentinel, thresh=26)
            touched = True
    if not touched:
        return image

    result = image.convert("RGBA")
    alpha = result.getchannel("A")
    mask = Image.new("L", result.size, 255)
    mask_px = mask.load()
    rgb_px = rgb.load()
    for y in range(result.height):
        for x in range(result.width):
            if rgb_px[x, y] == sentinel:
                mask_px[x, y] = 0
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    result.putalpha(Image.eval(Image.composite(alpha, Image.new("L", result.size, 0), mask), lambda v: v))
    return result


def _prepare_logo(raw: Optional[bytes], box: int) -> Optional[Image.Image]:
    if not raw:
        return None
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:  # noqa: BLE001 - orice format invalid e ignorat
        return None
    if getattr(image, "is_animated", False):
        image.seek(0)
    image = image.convert("RGBA")
    if image.width * image.height <= 900 * 900:
        image = _strip_border_background(image)
    image.thumbnail((box, box), Image.LANCZOS)
    return image


def _paste_logo(base: Image.Image, logo: Optional[Image.Image], center_x: int, center_y: int, box: int, placeholder: str) -> None:
    if logo is not None:
        base.alpha_composite(logo, (int(center_x - logo.width / 2), int(center_y - logo.height / 2)))
        return
    draw = ImageDraw.Draw(base)
    radius = box // 2
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        outline=BLUE,
        width=3,
    )
    font = _shrink_to_fit(placeholder, "sans_bold", int(box * 1.2), 30, 12)
    draw.text((center_x, center_y), placeholder, font=font, fill=BLUE, anchor="mm")


# ----------------------------------------------------------------------
# BLOCURI DE CONȚINUT
# ----------------------------------------------------------------------

def _section_title(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, title: str) -> int:
    font = _font("sans_bold", 21)
    draw.rectangle((x, y, x + 6, y + 26), fill=RED)
    draw.text((x + 18, y + 1), title.upper(), font=font, fill=BLUE)
    draw.line((x, y + 36, x + width, y + 36), fill=LINE, width=1)
    return y + 52


def _fields_grid(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    fields: Sequence[tuple],
    columns: int = 2,
) -> int:
    """Câmpuri (etichetă, valoare[, culoare]) așezate pe ``columns`` coloane."""
    gutter = 30
    col_width = (width - gutter * (columns - 1)) // columns
    row_height = 62
    rows = math.ceil(len(fields) / columns)

    panel_bottom = y + rows * row_height + 10
    draw.rounded_rectangle((x - 12, y - 10, x + width + 12, panel_bottom), radius=10, fill=(252, 250, 245), outline=LINE, width=1)

    label_font = _font("sans", 15)
    value_font_name = "serif_bold"
    for index, (label, value, *color) in enumerate(fields):
        col = index % columns
        row = index // columns
        fx = x + col * (col_width + gutter)
        fy = y + row * row_height
        draw.text((fx, fy), label.upper(), font=label_font, fill=MUTED)
        value_font = _shrink_to_fit(str(value), value_font_name, col_width, 23, 12)
        draw.text((fx, fy + 22), _ellipsize(str(value), value_font, col_width), font=value_font, fill=color[0] if color else INK)
        draw.line((fx, fy + 52, fx + col_width, fy + 52), fill=(214, 208, 194), width=1)
    return panel_bottom + 26


def _clauses(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, items: Iterable[str]) -> int:
    body = _font("serif", 19)
    bold = _font("serif_bold", 19)
    for index, item in enumerate(items, start=1):
        marker = f"Art. {index}."
        draw.text((x, y), marker, font=bold, fill=BLUE)
        offset = _text_width(marker, bold) + 10
        y = _draw_paragraph(draw, x + offset, y, item, body, INK, width - offset, 27)
        y += 10
    return y


def _signature_block(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    role: str,
    subtitle: str,
    signature: str,
    printed_name: str,
    caption: str = "Semnătură",
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 210), radius=12, fill=(252, 250, 245), outline=LINE, width=1)
    draw.text((x + 20, y + 16), role.upper(), font=_font("sans_bold", 18), fill=BLUE)
    sub_font = _shrink_to_fit(subtitle, "sans", width - 40, 16, 10)
    draw.text((x + 20, y + 42), _ellipsize(subtitle, sub_font, width - 40), font=sub_font, fill=MUTED)

    script = _shrink_to_fit(signature, "script", width - 60, 62, 22)
    draw.text((x + width / 2, y + 118), signature, font=script, fill=(21, 38, 92), anchor="mm")

    draw.line((x + 30, y + 152, x + width - 30, y + 152), fill=(120, 126, 138), width=2)
    name_font = _shrink_to_fit(printed_name, "sans", width - 40, 16, 10)
    draw.text((x + width / 2, y + 164), _ellipsize(printed_name, name_font, width - 40), font=name_font, fill=MUTED, anchor="ma")
    draw.text((x + width / 2, y + 186), caption, font=_font("sans", 14), fill=(160, 160, 160), anchor="ma")


def _stamp(base: Image.Image, seal: Image.Image, content_end: int, signature_y: int) -> None:
    """Așează ștampila în spațiul liber dintre conținut și semnături."""
    gap_top = content_end + 12
    gap_bottom = signature_y - 14
    available = gap_bottom - gap_top

    if available < seal.height:
        # Spațiu strâns: ștampila se micșorează și se aplică peste zona de semnături,
        # exact ca o ștampilă reală pusă pe hârtie.
        target = min(seal.height, max(118, available))
        ratio = target / seal.height
        seal = seal.resize((max(1, int(seal.width * ratio)), max(1, int(seal.height * ratio))), Image.LANCZOS)

    offset_y = gap_top + max(0, (gap_bottom - gap_top - seal.height) // 2)
    base.alpha_composite(seal, (int(WIDTH / 2 - seal.width / 2), int(offset_y)))


def _header(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_left: Optional[Image.Image],
    logo_right: Optional[Image.Image],
    city: str,
    department: str,
    subtitle: str,
    title: str,
    document_no: str,
) -> int:
    _paste_logo(base, logo_left, 158, 168, 150, "CLT")
    _paste_logo(base, logo_right, WIDTH - 158, 168, 150, "EMS")

    center_x = WIDTH // 2
    draw.text((center_x, 92), _spaced(f"ORAȘUL {city.upper()}"), font=_font("sans_bold", 20), fill=MUTED, anchor="ma")
    dep_font = _shrink_to_fit(department.upper(), "sans_bold", 560, 30, 16)
    draw.text((center_x, 122), department.upper(), font=dep_font, fill=RED, anchor="ma")
    draw.text((center_x, 158), subtitle.upper(), font=_font("sans", 17), fill=MUTED, anchor="ma")

    draw.line((center_x - 190, 190, center_x + 190, 190), fill=GOLD, width=2)

    title_font = _shrink_to_fit(title.upper(), "serif_bold", 700, 38, 20)
    lines = _wrap(title.upper(), title_font, 700)
    y = 206
    for line in lines:
        draw.text((center_x, y), line, font=title_font, fill=INK, anchor="ma")
        y += title_font.size + 8

    draw.text((center_x, y + 4), document_no, font=_font("serif_italic", 18), fill=MUTED, anchor="ma")
    y += 40

    draw.line((70, y + 12, WIDTH - 70, y + 12), fill=BLUE, width=2)
    draw.line((70, y + 18, WIDTH - 70, y + 18), fill=(190, 184, 170), width=1)
    return y + 46


def _footer(draw: ImageDraw.ImageDraw, document_id: str, issued_at: str, note: str) -> None:
    draw.line((70, HEIGHT - 130, WIDTH - 70, HEIGHT - 130), fill=(200, 194, 180), width=1)
    draw.text((70, HEIGHT - 116), f"ID document: {document_id}", font=_font("sans", 14), fill=MUTED)
    draw.text((WIDTH - 70, HEIGHT - 116), f"Generat: {issued_at}", font=_font("sans", 14), fill=MUTED, anchor="ra")
    draw.text((WIDTH // 2, HEIGHT - 92), note, font=_font("sans", 13), fill=(150, 150, 150), anchor="ma")


def _to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer.getvalue()


# ----------------------------------------------------------------------
# DOCUMENT 1 — CONTRACT DE ANGAJARE
# ----------------------------------------------------------------------

def render_contract(
    *,
    contract_id: str,
    nume_ic: str,
    cnp: str,
    functie: str,
    discord_tag: str,
    discord_id: str,
    data_angajarii: str,
    semnatura_angajat: str,
    semnatura_angajator: str,
    grad_angajator: str,
    angajator_discord: str,
    emis_la: str,
    city: str = "Legacy of CLT",
    department: str = "Legacy EMS",
    department_subtitle: str = "Departamentul Medical",
    logo_main: Optional[bytes] = None,
    logo_ems: Optional[bytes] = None,
) -> bytes:
    base = _paper(WIDTH, HEIGHT).convert("RGBA")
    draw = ImageDraw.Draw(base)
    _frame(draw)

    y = _header(
        base,
        draw,
        _prepare_logo(logo_main, 150),
        _prepare_logo(logo_ems, 150),
        city,
        department,
        department_subtitle,
        "Contract Individual de Muncă",
        f"Nr. {contract_id} · încheiat la {emis_la}",
    )

    margin = 92
    content_width = WIDTH - margin * 2

    intro = (
        f"Încheiat astăzi, {emis_la}, între Departamentul Medical {department} al orașului {city}, "
        f"reprezentat legal prin {semnatura_angajator}, în calitate de {grad_angajator}, denumit în continuare "
        f"ANGAJATOR, și numitul/numita {nume_ic}, având CNP {cnp}, denumit în continuare ANGAJAT, "
        "a intervenit prezentul contract individual de muncă."
    )
    y = _draw_paragraph_clamped(draw, margin, y, intro, "serif", INK, content_width, 176)
    y += 22

    y = _section_title(draw, margin, y, content_width, "Datele angajatului")
    y = _fields_grid(
        draw,
        margin,
        y,
        content_width,
        [
            ("Nume și prenume", nume_ic),
            ("CNP", cnp),
            ("Departament", f"{department} · {department_subtitle}"),
            ("Gradul acordat", functie),
            ("Data și ora angajării", data_angajarii),
            ("Cont Discord", discord_tag),
        ],
    )

    y = _section_title(draw, margin, y, content_width, "Clauze contractuale")
    y = _clauses(
        draw,
        margin,
        y,
        content_width,
        [
            f"Angajatul este încadrat în {department} ({department_subtitle}) al orașului {city}, cu gradul de {functie}, "
            "începând cu data menționată mai sus.",
            "Angajatul se obligă să respecte regulamentul intern al departamentului, ordinele conducerii, "
            "protocoalele medicale și regulamentul general al serverului.",
            "Angajatul se obligă să acorde asistență medicală tuturor cetățenilor, fără discriminare, "
            "și să păstreze confidențialitatea datelor pacienților.",
            "Angajatorul se obligă să asigure instruirea, echipamentul și accesul la resursele necesare "
            "desfășurării activității.",
            "Prezentul contract încetează prin demisie aprobată de conducere sau prin decizie disciplinară, "
            "moment în care se emite o decizie de încetare a activității.",
        ],
    )

    signature_y = HEIGHT - 380
    block_width = 470

    _signature_block(
        base,
        draw,
        margin,
        signature_y,
        block_width,
        "Angajator",
        f"{grad_angajator} · {angajator_discord}",
        semnatura_angajator,
        semnatura_angajator,
    )
    _signature_block(
        base,
        draw,
        WIDTH - margin - block_width,
        signature_y,
        block_width,
        "Angajat",
        f"{functie} · {discord_tag}",
        semnatura_angajat,
        nume_ic,
    )

    _stamp(
        base,
        _seal(
            238,
            f"{department.upper()} · {city.upper()}",
            department_subtitle.upper(),
            ["LEGACY", "EMS", "OFICIAL"],
        ),
        y,
        signature_y,
    )

    _footer(
        draw,
        contract_id,
        emis_la,
        f"Document generat automat de sistemul {department} · Discord ID angajat: {discord_id}",
    )
    return _to_png(base)


# ----------------------------------------------------------------------
# DOCUMENT 2 — DECIZIE DE ÎNCETARE
# ----------------------------------------------------------------------

def render_termination(
    *,
    document_id: str,
    contract_id: str,
    nume_ic: str,
    cnp: str,
    functie: str,
    discord_tag: str,
    discord_id: str,
    data_angajarii: str,
    data_incetarii: str,
    durata: str,
    zile: str,
    motiv: str,
    semnatura_angajat: str,
    semnatura_conducere: str,
    grad_conducere: str,
    conducere_discord: str,
    city: str = "Legacy of CLT",
    department: str = "Legacy EMS",
    department_subtitle: str = "Departamentul Medical",
    logo_main: Optional[bytes] = None,
    logo_ems: Optional[bytes] = None,
) -> bytes:
    base = _paper(WIDTH, HEIGHT, seed=19).convert("RGBA")
    draw = ImageDraw.Draw(base)
    _frame(draw)

    y = _header(
        base,
        draw,
        _prepare_logo(logo_main, 150),
        _prepare_logo(logo_ems, 150),
        city,
        department,
        department_subtitle,
        "Decizie de Încetare a Contractului de Muncă",
        f"Nr. {document_id} · emisă la {data_incetarii}",
    )

    margin = 92
    content_width = WIDTH - margin * 2

    intro = (
        f"Conducerea Departamentului Medical {department} al orașului {city}, reprezentată prin "
        f"{semnatura_conducere}, în calitate de {grad_conducere}, aprobă cererea de demisie depusă de "
        f"{nume_ic} (CNP {cnp}) și dispune încetarea contractului individual de muncă nr. {contract_id}."
    )
    y = _draw_paragraph_clamped(draw, margin, y, intro, "serif", INK, content_width, 150)
    y += 16

    banner_h = 60
    draw.rounded_rectangle((margin - 12, y, WIDTH - margin + 12, y + banner_h), radius=10, fill=(250, 236, 234), outline=RED, width=2)
    banner_text = f"{nume_ic} nu mai face parte din {department} · {department_subtitle}"
    banner_font = _shrink_to_fit(banner_text, "sans_bold", content_width - 20, 22, 13)
    draw.text((WIDTH // 2, y + banner_h / 2), banner_text, font=banner_font, fill=RED, anchor="mm")
    y += banner_h + 30

    y = _section_title(draw, margin, y, content_width, "Situația activității")
    y = _fields_grid(
        draw,
        margin,
        y,
        content_width,
        [
            ("Nume și prenume", nume_ic),
            ("CNP", cnp),
            ("Gradul deținut", functie),
            ("Cont Discord", discord_tag),
            ("Data intrării în departament", data_angajarii),
            ("Data încetării activității", data_incetarii),
            ("Perioadă lucrată", durata),
            ("Total zile în departament", zile),
        ],
    )

    y = _section_title(draw, margin, y, content_width, "Motivul încetării")
    y = _draw_paragraph_clamped(
        draw,
        margin,
        y,
        motiv or "Demisie la cerere.",
        "serif_italic",
        INK,
        content_width,
        190,
        start_size=19,
    )
    y += 18

    y = _clauses(
        draw,
        margin,
        y,
        content_width,
        [
            f"Începând cu data de {data_incetarii}, persoana menționată nu mai deține nicio funcție și niciun drept "
            f"în cadrul {department}.",
            "Toate rolurile, accesele, echipamentul și dotările departamentului se retrag în mod obligatoriu.",
            "Prezenta decizie servește drept dovadă oficială a vechimii în departament și se arhivează.",
        ],
    )

    signature_y = HEIGHT - 380
    block_width = 470

    _signature_block(
        base,
        draw,
        margin,
        signature_y,
        block_width,
        "Conducerea departamentului",
        f"{grad_conducere} · {conducere_discord}",
        semnatura_conducere,
        semnatura_conducere,
    )
    _signature_block(
        base,
        draw,
        WIDTH - margin - block_width,
        signature_y,
        block_width,
        "Fost angajat",
        f"{functie} · {discord_tag}",
        semnatura_angajat,
        nume_ic,
    )

    _stamp(
        base,
        _seal(
            238,
            f"{department.upper()} · {city.upper()}",
            "ÎNCETARE CONTRACT",
            ["LEGACY", "EMS", "ARHIVĂ"],
            color=(150, 34, 34),
            tilt=7.0,
        ),
        y,
        signature_y,
    )

    _footer(
        draw,
        document_id,
        data_incetarii,
        f"Document generat automat de sistemul {department} · Discord ID: {discord_id}",
    )
    return _to_png(base)


# ----------------------------------------------------------------------
# DOCUMENTE MEDICALE — ELEMENTE COMUNE
# ----------------------------------------------------------------------

PARAFA_INK = (28, 58, 150)


def _parafa_code(medic: str) -> str:
    """Codul de parafă al medicului: stabil pentru același nume."""
    return f"E{zlib.crc32(medic.lower().encode('utf-8')) % 90000 + 10000}"


def _parafa(lines: Sequence[str], tilt: float = -5.0) -> Image.Image:
    """Parafa medicului: ștampilă dreptunghiulară cu nume, specialitate și cod."""
    scale = 2
    fonts = [
        _shrink_to_fit(lines[0], "sans_bold", 176 * scale, 15 * scale, 8 * scale),
        _font("sans", 12 * scale),
        _font("sans_bold", 12 * scale),
    ]
    widths = [font.getlength(text) for font, text in zip(fonts, lines)]
    width = int(max(widths) + 34 * scale)
    height = int(sum(font.size * 1.35 for font in fonts) + 22 * scale)

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ink = PARAFA_INK + (235,)
    draw.rectangle((2, 2, width - 3, height - 3), outline=ink, width=3 * scale)
    draw.rectangle((6 * scale, 6 * scale, width - 6 * scale - 1, height - 6 * scale - 1), outline=ink, width=scale)
    y = 11 * scale
    for font, text in zip(fonts, lines):
        draw.text((width / 2, y), text, font=font, fill=ink, anchor="ma")
        y += font.size * 1.35

    layer = layer.resize((width // scale, height // scale), Image.LANCZOS)
    layer = layer.rotate(tilt, resample=Image.BICUBIC, expand=True)
    return _ink(layer, seed=29)


def _badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color, size: int = 17) -> int:
    font = _font("sans_bold", size)
    width = font.getlength(text) + 30
    height = size + 18
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=color)
    draw.text((x + width / 2, y + height / 2), text, font=font, fill=(255, 255, 255), anchor="mm")
    return y + height


def _label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> int:
    draw.text((x, y), text.upper(), font=_font("sans_bold", 15), fill=BLUE)
    return y + 25


def _tint(color, amount: float = 0.1) -> tuple[int, int, int]:
    return tuple(int(255 - (255 - channel) * amount) for channel in color)


def _insurance_box(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, title: str, text: str, color) -> int:
    """Caseta cu certificatul pentru asigurare, afișată la stare rea sau gravă."""
    icon = 56
    text_x = x + icon + 30
    text_w = width - icon - 36
    body = _font("serif", 17)
    lines = _wrap(text, body, text_w)
    height = max(icon + 30, 18 + 30 + len(lines) * 24 + 14)

    draw.rounded_rectangle((x - 12, y, x + width + 12, y + height), radius=12, fill=_tint(color), outline=color, width=2)
    cy = y + height / 2
    draw.ellipse((x + 8, cy - icon / 2, x + 8 + icon, cy + icon / 2), fill=color)
    draw.text((x + 8 + icon / 2, cy + 1), "⚕", font=_font("sans_bold", 34), fill=(255, 255, 255), anchor="mm")

    ty = y + 18
    draw.text((text_x, ty), title.upper(), font=_font("sans_bold", 18), fill=color)
    ty += 30
    for line in lines:
        draw.text((text_x, ty), line, font=body, fill=INK)
        ty += 24
    return y + height


def _medical_signatures(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    margin: int,
    medic: str,
    specialty: str,
    department: str,
    department_subtitle: str,
    city: str,
    seal_lines: Sequence[str],
) -> None:
    """Rândul de jos: ștampila unității în stânga, semnătura și parafa medicului în dreapta."""
    block_width = 470
    right_x = WIDTH - margin - block_width
    _signature_block(
        base,
        draw,
        right_x,
        y,
        block_width,
        "Medic",
        f"{department} · {specialty}",
        medic,
        f"Dr. {medic}",
        caption="Semnătura și parafa medicului",
    )
    parafa = _parafa([f"DR. {medic.upper()}", f"MEDIC · {specialty.upper()}", f"COD PARAFĂ {_parafa_code(medic)}"])
    base.alpha_composite(parafa, (int(right_x + block_width - parafa.width - 8), int(y + 6)))

    seal = _seal(214, f"{department.upper()} · {city.upper()}", department_subtitle.upper(), seal_lines, tilt=-7.0)
    base.alpha_composite(seal, (int(margin + block_width / 2 - seal.width / 2), int(y + 105 - seal.height / 2)))


def _signature_row_y(draw: ImageDraw.ImageDraw, content_end: int) -> int:
    """Rândul de semnături stă jos, ca la contract; coboară doar dacă textul e lung."""
    y = min(max(content_end + 58, HEIGHT - 380), HEIGHT - 352)
    draw.text(
        (WIDTH // 2, y - 36),
        "Prezentul document este valabil numai cu semnătura și parafa medicului și ștampila unității.",
        font=_font("serif_italic", 16),
        fill=MUTED,
        anchor="ma",
    )
    return y


# ----------------------------------------------------------------------
# DOCUMENT 3 — BULETIN RADIOLOGIC
# ----------------------------------------------------------------------

def render_radiography(
    *,
    document_id: str,
    pacient: str,
    cnp: str,
    stare: str,
    zona: str,
    medic: str,
    emis_la: str,
    emis_de: str,
    city: str = "Legacy of CLT",
    department: str = "Legacy EMS",
    department_subtitle: str = "Departamentul Medical",
    logo_main: Optional[bytes] = None,
    logo_ems: Optional[bytes] = None,
) -> bytes:
    stare_info = medical.STARI[stare]
    zona_info = medical.ZONE[zona]
    rezultat = medical.RADIOLOGIE[zona][stare]

    base = _paper(WIDTH, HEIGHT, seed=23).convert("RGBA")
    draw = ImageDraw.Draw(base)
    _frame(draw)

    y = _header(
        base,
        draw,
        _prepare_logo(logo_main, 150),
        _prepare_logo(logo_ems, 150),
        city,
        department,
        department_subtitle,
        "Buletin de Investigație Radiologică",
        f"Nr. {document_id} · emis la {emis_la}",
    )

    margin = 92
    content_width = WIDTH - margin * 2

    y = _section_title(draw, margin, y, content_width, "Datele pacientului")
    y = _fields_grid(
        draw,
        margin,
        y,
        content_width,
        [
            ("Nume și prenume", pacient),
            ("CNP", cnp),
            ("Starea pacientului", stare_info.label, stare_info.color),
            ("Zona investigată", f"{zona_info.label} · {zona_info.short}"),
            ("Data și ora examinării", emis_la),
            ("Medic examinator", f"Dr. {medic}"),
        ],
        columns=3,
    )

    # Filmul radiografiei, cu textele de pe margine ca pe un negatoscop digital.
    overlay_font = _font("sans", 12)
    film = xray.render_film(
        zona,
        stare,
        {
            "top_left": [f"{department.upper()} · RADIOLOGIE", _ellipsize(pacient.upper(), overlay_font, 230), f"CNP {cnp}"],
            "top_right": [emis_la.replace("/", "."), f"{zona_info.label.upper()} · {zona_info.short}", _ellipsize(f"Dr. {medic}", overlay_font, 200)],
            "bottom_left": [f"{zona_info.kv} kV · {medical.format_number(zona_info.mas, 1)} mAs", "DFF 100 cm"],
            "bottom_right": [document_id, "Img 1/1"],
        },
        seed=zlib.crc32(document_id.encode("utf-8")),
    )
    film_x, film_y = margin, y
    draw.rounded_rectangle((film_x - 8, film_y - 8, film_x + film.width + 8, film_y + film.height + 8), radius=10, fill=(20, 24, 32))
    base.paste(film, (film_x, film_y))
    draw.text(
        (film_x + film.width / 2, film_y + film.height + 16),
        f"Imagine radiologică digitală · {zona_info.projection}",
        font=_font("sans", 14),
        fill=MUTED,
        anchor="ma",
    )

    # Coloana din dreapta: investigația, starea și rezultatul.
    col_x = film_x + film.width + 34
    col_w = WIDTH - margin - col_x
    col_bottom = film_y + film.height
    ty = film_y - 4
    title_font = _shrink_to_fit(zona_info.examination, "serif_bold", col_w, 26, 18)
    for line in _wrap(zona_info.examination, title_font, col_w):
        draw.text((col_x, ty), line, font=title_font, fill=INK)
        ty += title_font.size + 8
    projection = zona_info.projection[0].upper() + zona_info.projection[1:]
    draw.text((col_x, ty), projection, font=_font("sans", 16), fill=MUTED)
    ty += 34
    ty = _badge(draw, col_x, ty, f"STARE: {stare_info.label.upper()}", stare_info.color) + 22
    draw.line((col_x, ty - 10, col_x + col_w, ty - 10), fill=LINE, width=1)

    ty = _label(draw, col_x, ty + 4, "Descriere radiologică")
    ty = _draw_paragraph_clamped(draw, col_x, ty, rezultat.descriere, "serif", INK, col_w, 190, start_size=18, min_size=14)
    ty = _label(draw, col_x, ty + 14, "Concluzie")
    ty = _draw_paragraph_clamped(draw, col_x, ty, rezultat.concluzie, "serif_bold", stare_info.color, col_w, 110, start_size=18, min_size=14)
    tech = [
        "Aparat: radiologie digitală directă (DR)",
        f"Expunere: {zona_info.kv} kV · {medical.format_number(zona_info.mas, 1)} mAs · DFF 100 cm",
        f"Arhivare PACS: {document_id}",
    ]
    tech_top = col_bottom - 25 - len(tech) * 22
    ty = _label(draw, col_x, ty + 14, "Recomandări")
    _draw_paragraph_clamped(draw, col_x, ty, rezultat.recomandari, "serif", INK, col_w, max(40, tech_top - 24 - ty), start_size=18, min_size=14)

    draw.line((col_x, tech_top - 12, col_x + col_w, tech_top - 12), fill=LINE, width=1)
    _label(draw, col_x, tech_top, "Date tehnice")
    for index, line in enumerate(tech):
        draw.text((col_x, tech_top + 25 + index * 22), line, font=_font("sans", 14), fill=MUTED)

    y = film_y + film.height + 42
    if medical.needs_insurance(stare):
        y = _insurance_box(
            draw,
            margin,
            y,
            content_width,
            medical.INSURANCE_TITLE,
            medical.insurance_text(stare, department),
            stare_info.color,
        )

    _medical_signatures(
        base,
        draw,
        _signature_row_y(draw, y),
        margin,
        medic,
        "Radiologie",
        department,
        department_subtitle,
        city,
        ["LEGACY", "EMS", "RADIOLOGIE"],
    )
    _footer(
        draw,
        document_id,
        emis_la,
        f"Document medical generat automat de sistemul {department} · Emis de {emis_de}",
    )
    return _to_png(base)


# ----------------------------------------------------------------------
# DOCUMENT 4 — BULETIN DE ANALIZE MEDICALE
# ----------------------------------------------------------------------

def _range_bar(draw: ImageDraw.ImageDraw, x: int, cy: float, width: int, result: medical.ValoareAnaliza) -> None:
    """Bara de încadrare: zona verde este intervalul de referință, punctul este valoarea."""
    test = result.test
    span = (test.high - test.low) or 1.0
    if result.value < test.low:
        position = 0.25 - 0.23 * min(1.0, (test.low - result.value) / (span * 0.8))
    elif result.value > test.high:
        position = 0.75 + 0.23 * min(1.0, (result.value - test.high) / (span * 1.2))
    else:
        position = 0.25 + 0.5 * (result.value - test.low) / span

    h = 8
    draw.rounded_rectangle((x, cy - h / 2, x + width, cy + h / 2), radius=4, fill=(222, 216, 204))
    draw.rounded_rectangle((x + width * 0.25, cy - h / 2, x + width * 0.75, cy + h / 2), radius=4, fill=(176, 216, 188))
    color = (30, 132, 80) if result.flag == "normal" else RED
    px = x + width * position
    draw.ellipse((px - 7, cy - 7, px + 7, cy + 7), fill=color, outline=(255, 255, 255), width=2)


def _lab_table(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, results: Sequence[medical.ValoareAnaliza]) -> int:
    columns = [("Analiză", 330), ("Rezultat", 150), ("UM", 128), ("Interval de referință", 206), ("Încadrare", width - 814)]
    header_h, group_h, row_h = 34, 25, 28

    draw.rounded_rectangle((x - 12, y, x + width + 12, y + header_h), radius=8, fill=BLUE)
    cx = x
    for title, col_width in columns:
        draw.text((cx, y + header_h / 2), title.upper(), font=_font("sans_bold", 13), fill=(255, 255, 255), anchor="lm")
        cx += col_width
    y += header_h + 4

    group = None
    for index, result in enumerate(results):
        if result.test.group != group:
            group = result.test.group
            label_font = _font("sans_bold", 13)
            mid = y + group_h / 2 + 2
            draw.text((x, mid), group.upper(), font=label_font, fill=RED, anchor="lm")
            line_x = x + label_font.getlength(group.upper()) + 14
            draw.line((line_x, mid, x + width, mid), fill=LINE, width=1)
            y += group_h

        draw.rectangle((x - 12, y, x + width + 12, y + row_h), fill=(252, 250, 245) if index % 2 == 0 else (243, 239, 229))
        mid = y + row_h / 2
        cx = x
        draw.text((cx, mid), result.test.name, font=_font("serif", 17), fill=INK, anchor="lm")
        cx += columns[0][1]
        abnormal = result.flag != "normal"
        draw.text((cx, mid), f"{result.text} {result.arrow}".strip(), font=_font("sans_bold", 17), fill=RED if abnormal else INK, anchor="lm")
        cx += columns[1][1]
        draw.text((cx, mid), result.test.unit, font=_font("sans", 15), fill=MUTED, anchor="lm")
        cx += columns[2][1]
        draw.text((cx, mid), result.test.reference, font=_font("sans", 15), fill=MUTED, anchor="lm")
        cx += columns[3][1]
        _range_bar(draw, cx + 4, mid, columns[4][1] - 12, result)
        y += row_h

    draw.line((x - 12, y, x + width + 12, y), fill=LINE, width=1)
    return y + 20


def render_lab_results(
    *,
    document_id: str,
    pacient: str,
    cnp: str,
    stare: str,
    medic: str,
    results: Sequence[medical.ValoareAnaliza],
    emis_la: str,
    emis_de: str,
    city: str = "Legacy of CLT",
    department: str = "Legacy EMS",
    department_subtitle: str = "Departamentul Medical",
    logo_main: Optional[bytes] = None,
    logo_ems: Optional[bytes] = None,
) -> bytes:
    stare_info = medical.STARI[stare]
    interpretare, concluzie = medical.INTERPRETARE[stare]

    base = _paper(WIDTH, HEIGHT, seed=31).convert("RGBA")
    draw = ImageDraw.Draw(base)
    _frame(draw)

    y = _header(
        base,
        draw,
        _prepare_logo(logo_main, 150),
        _prepare_logo(logo_ems, 150),
        city,
        department,
        department_subtitle,
        "Buletin de Analize Medicale",
        f"Nr. {document_id} · emis la {emis_la}",
    )

    margin = 92
    content_width = WIDTH - margin * 2

    y = _section_title(draw, margin, y, content_width, "Datele pacientului")
    y = _fields_grid(
        draw,
        margin,
        y,
        content_width,
        [
            ("Nume și prenume", pacient),
            ("CNP", cnp),
            ("Starea pacientului", stare_info.label, stare_info.color),
            ("Tip probă", "Sânge venos"),
            ("Data și ora recoltării", emis_la),
            ("Medic", f"Dr. {medic}"),
        ],
        columns=3,
    )

    y = _section_title(draw, margin, y, content_width, "Rezultatele analizelor")
    y = _lab_table(draw, margin, y, content_width, results)

    abnormal = sum(1 for result in results if result.flag != "normal")
    summary = (
        f"{abnormal} din {len(results)} parametri sunt în afara intervalului de referință."
        if abnormal
        else f"Toți cei {len(results)} parametri sunt în intervalul de referință."
    )
    y = _label(draw, margin, y, "Interpretare medicală")
    y = _draw_paragraph_clamped(draw, margin, y, f"{summary} {interpretare}", "serif", INK, content_width, 104, start_size=18, min_size=14)
    y = _draw_paragraph_clamped(draw, margin, y + 6, f"Concluzie: {concluzie}", "serif_bold", stare_info.color, content_width, 56, start_size=18, min_size=14)

    if medical.needs_insurance(stare):
        y = _insurance_box(
            draw,
            margin,
            y + 14,
            content_width,
            medical.INSURANCE_TITLE,
            medical.insurance_text(stare, department),
            stare_info.color,
        )

    _medical_signatures(
        base,
        draw,
        _signature_row_y(draw, y),
        margin,
        medic,
        "Laborator",
        department,
        department_subtitle,
        city,
        ["LEGACY", "EMS", "LABORATOR"],
    )
    _footer(
        draw,
        document_id,
        emis_la,
        f"Document medical generat automat de sistemul {department} · Emis de {emis_de}",
    )
    return _to_png(base)
