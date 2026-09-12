"""Generarea documentelor oficiale (imagini PNG) pentru Legacy EMS.

Sunt două documente:

* ``render_contract``     -> Contract Individual de Muncă (angajare)
* ``render_termination``  -> Decizie de Încetare a Contractului (demisie acceptată)

Ambele folosesc același "hârtie oficială": ramă, antet cu cele două logo-uri,
corp de text în română, casete de semnătură și ștampilă rotundă.
"""

from __future__ import annotations

import io
import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

    # Aspect de tuș: alpha neuniform.
    alpha = layer.getchannel("A")
    rng = random.Random(11)
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


def _fields_grid(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, fields: Sequence[tuple[str, str]]) -> int:
    columns = 2
    col_width = (width - 30) // columns
    row_height = 62
    rows = math.ceil(len(fields) / columns)

    panel_bottom = y + rows * row_height + 10
    draw.rounded_rectangle((x - 12, y - 10, x + width + 12, panel_bottom), radius=10, fill=(252, 250, 245), outline=LINE, width=1)

    label_font = _font("sans", 15)
    value_font_name = "serif_bold"
    for index, (label, value) in enumerate(fields):
        col = index % columns
        row = index // columns
        fx = x + col * (col_width + 30)
        fy = y + row * row_height
        draw.text((fx, fy), label.upper(), font=label_font, fill=MUTED)
        value_font = _shrink_to_fit(str(value), value_font_name, col_width, 23, 12)
        draw.text((fx, fy + 22), _ellipsize(str(value), value_font, col_width), font=value_font, fill=INK)
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
    draw.text((x + width / 2, y + 186), "Semnătură", font=_font("sans", 14), fill=(160, 160, 160), anchor="ma")


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
