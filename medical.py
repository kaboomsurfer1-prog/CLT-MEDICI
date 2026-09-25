"""Conținutul medical al documentelor Legacy EMS: stări, zone, texte, analize.

Folosit de ``documents.py`` (imaginile) și de ``main.py`` (mesajele din Discord),
ca textele de pe document și cele din embed să fie mereu aceleași.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


# ----------------------------------------------------------------------
# STAREA PACIENTULUI
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Stare:
    key: str
    label: str
    emoji: str
    color: tuple[int, int, int]
    discord_color: int


STARI: dict[str, Stare] = {
    "buna": Stare("buna", "Bună", "🟢", (30, 132, 80), 0x1E8450),
    "normala": Stare("normala", "Normală", "🔵", (37, 99, 170), 0x2563AA),
    "rea": Stare("rea", "Rea", "🟠", (207, 110, 16), 0xCF6E10),
    "grava": Stare("grava", "Gravă", "🔴", (180, 28, 40), 0xB41C28),
}


def needs_insurance(stare: str) -> bool:
    """La stare rea sau gravă documentul menționează certificatul pentru asigurare."""
    return stare in {"rea", "grava"}


INSURANCE_TITLE = "Certificat medical pentru asigurare"


def insurance_text(stare: str, department: str) -> str:
    return (
        f"Întrucât starea pacientului este {STARI[stare].label.lower()}, spitalul {department} oferă un "
        "certificat medical pentru asigurarea pacientului, valabil în caz de accident sau dacă pacientul "
        "a fost vătămat de o altă persoană, cu obligația de despăgubire pentru îngrijirile medicale acordate."
    )


INSURANCE_SHORT = (
    "Spitalul oferă un certificat medical pentru asigurarea pacientului, în caz de accident sau dacă "
    "a fost vătămat de o altă persoană, cu obligația de despăgubire pentru îngrijirile medicale."
)


# ----------------------------------------------------------------------
# RADIOGRAFII
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Zona:
    key: str
    label: str
    examination: str
    projection: str
    short: str
    kv: int
    mas: float


ZONE: dict[str, Zona] = {
    "mana": Zona("mana", "Mână", "Radiografie mână", "incidență postero-anterioară (PA)", "PA", 55, 2.5),
    "picior": Zona("picior", "Picior", "Radiografie gambă (tibie și fibulă)", "incidență antero-posterioară (AP)", "AP", 62, 6.3),
    "cap": Zona("cap", "Cap", "Radiografie craniu", "incidență postero-anterioară (PA)", "PA", 75, 25.0),
    "gat": Zona("gat", "Gât", "Radiografie coloană cervicală", "incidență laterală (LL)", "LAT", 70, 16.0),
    "genunchi": Zona("genunchi", "Genunchi", "Radiografie genunchi", "incidență antero-posterioară (AP)", "AP", 65, 8.0),
}


@dataclass(frozen=True)
class Rezultat:
    descriere: str
    concluzie: str
    recomandari: str


_APT = "Nu necesită tratament. Pacientul este apt pentru activitate normală."

RADIOLOGIE: dict[str, dict[str, Rezultat]] = {
    "mana": {
        "buna": Rezultat(
            "Structurile osoase ale mâinii (oasele carpiene, metacarpienele și falangele) au aspect radiologic normal, "
            "cu contururi corticale regulate și structură trabeculară păstrată. Spațiile articulare sunt păstrate. "
            "Nu se evidențiază traiecte de fractură sau deplasări.",
            "Aspect radiologic normal al mâinii. Fără leziuni osoase.",
            _APT,
        ),
        "normala": Rezultat(
            "Structuri osoase integre, fără traiecte de fractură sau luxații. Se observă o ușoară tumefiere a "
            "părților moi în regiunea metacarpiană, de natură posttraumatică, fără afectare osoasă.",
            "Fără leziuni osoase. Contuzie ușoară a părților moi ale mâinii.",
            "Repaus relativ 2–3 zile, comprese reci și antiinflamatoare la nevoie.",
        ),
        "rea": Rezultat(
            "Se evidențiază un traiect de fractură incomplet, fără deplasare (fisură), la nivelul colului "
            "metacarpianului V. Aliniamentul osos este păstrat. Tumefiere moderată a părților moi adiacente.",
            "Fisură a metacarpianului V (mâna), fără deplasare.",
            "Imobilizare în atelă gipsată 3–4 săptămâni, antialgice și control radiologic la 14 zile.",
        ),
        "grava": Rezultat(
            "Fractură completă, cominutivă, a colului metacarpianului V, cu deplasarea și angularea fragmentului "
            "distal și eschile osoase multiple. Tumefiere importantă a părților moi și hematom local.",
            "Fractură cominutivă cu deplasare a metacarpianului V — traumatism grav al mâinii.",
            "Reducere ortopedică de urgență sau osteosinteză chirurgicală, imobilizare 6 săptămâni, "
            "apoi recuperare medicală.",
        ),
    },
    "picior": {
        "buna": Rezultat(
            "Tibia și fibula prezintă structură, contur și aliniament normale. Articulațiile genunchiului și "
            "gleznei au aspect radiologic normal. Nu se evidențiază traiecte de fractură.",
            "Aspect radiologic normal al gambei. Fără leziuni osoase.",
            _APT,
        ),
        "normala": Rezultat(
            "Structuri osoase integre, fără fracturi sau deplasări. Ușoară tumefiere a părților moi în treimea "
            "medie a gambei, posttraumatică, fără afectare osoasă.",
            "Fără leziuni osoase. Contuzie a părților moi ale gambei.",
            "Repaus relativ, gheață local, ridicarea membrului și antiinflamatoare la nevoie.",
        ),
        "rea": Rezultat(
            "Se evidențiază o fisură (fractură incompletă, fără deplasare) la nivelul treimii medii a diafizei "
            "tibiale. Fibula este integră. Tumefiere moderată a părților moi.",
            "Fisură a diafizei tibiale, fără deplasare.",
            "Imobilizare gipsată 4–6 săptămâni, mers cu cârje fără sprijin, antialgice și control radiologic "
            "la 3 săptămâni.",
        ),
        "grava": Rezultat(
            "Fractură completă, cu deplasare, a ambelor oase ale gambei (tibie și fibulă) în treimea medie, "
            "cu angularea și încălecarea fragmentelor și eschile osoase. Hematom important al părților moi.",
            "Fractură cu deplasare de tibie și fibulă — traumatism grav al membrului inferior.",
            "Intervenție chirurgicală de urgență (reducere și osteosinteză), internare, profilaxie "
            "antitrombotică și recuperare de durată.",
        ),
    },
    "cap": {
        "buna": Rezultat(
            "Cutia craniană are contur regulat și structură osoasă normală. Orbitele, sinusurile paranazale și "
            "masivul facial au aspect normal. Nu se evidențiază traiecte de fractură.",
            "Aspect radiologic normal al craniului. Fără leziuni osoase.",
            _APT,
        ),
        "normala": Rezultat(
            "Structuri osoase craniene integre, fără traiecte de fractură. Tumefiere ușoară a părților moi "
            "epicraniene în regiunea parietală dreaptă (contuzie).",
            "Fără leziuni osoase. Contuzie ușoară a scalpului.",
            "Supraveghere 24 de ore, comprese reci și antialgice. Revine de urgență la apariția cefaleei, "
            "a vărsăturilor sau a amețelilor.",
        ),
        "rea": Rezultat(
            "Se evidențiază un traiect de fractură liniară, fără înfundare, la nivelul osului parietal drept. "
            "Structurile faciale sunt integre. Tumefiere a părților moi epicraniene adiacente.",
            "Fractură liniară a osului parietal drept, fără deplasare.",
            "Internare pentru supraveghere neurologică 24–48 de ore, CT cerebral, repaus la pat și antialgice.",
        ),
        "grava": Rezultat(
            "Fractură cominutivă cu înfundare la nivelul osului parietal drept, cu traiecte multiple de fractură "
            "iradiate și fragmente osoase deplasate spre interior. Hematom epicranian important.",
            "Fractură cominutivă cu înfundare a craniului — traumatism cranio-cerebral grav.",
            "CT cerebral de urgență, consult neurochirurgical, internare în terapie intensivă și monitorizare "
            "neurologică continuă.",
        ),
    },
    "gat": {
        "buna": Rezultat(
            "Coloana cervicală prezintă aliniere normală, cu lordoză fiziologică păstrată. Corpii vertebrali "
            "C1–C7 au înălțime și structură normale, iar spațiile intervertebrale sunt păstrate.",
            "Aspect radiologic normal al coloanei cervicale.",
            _APT,
        ),
        "normala": Rezultat(
            "Aliniere normală a coloanei cervicale, fără fracturi. Se observă o ușoară rectitudine a lordozei "
            "cervicale, prin contractură musculară posttraumatică.",
            "Fără leziuni osoase. Entorsă cervicală ușoară (contractură musculară).",
            "Guler cervical moale 5–7 zile, antiinflamatoare și miorelaxante la nevoie.",
        ),
        "rea": Rezultat(
            "Se evidențiază o fisură (fractură fără deplasare) la nivelul corpului vertebral C5, fără afectarea "
            "aliniamentului. Contractură musculară paravertebrală.",
            "Fisură a corpului vertebral C5, stabilă, fără deplasare.",
            "Guler cervical rigid 6 săptămâni, antialgice, evitarea efortului și control radiologic.",
        ),
        "grava": Rezultat(
            "Fractură-luxație la nivelul C5–C6, cu tasarea anterioară și deplasarea înainte a corpului vertebral "
            "C5, fragment osos antero-inferior și îngustarea canalului vertebral. Edem important al părților moi "
            "prevertebrale.",
            "Fractură-luxație cervicală C5–C6, instabilă — risc major de leziune medulară.",
            "Imobilizare cervicală strictă, CT/RMN de urgență, consult neurochirurgical și internare în "
            "terapie intensivă.",
        ),
    },
    "genunchi": {
        "buna": Rezultat(
            "Structurile osoase ale genunchiului (femurul distal, rotula, tibia și fibula proximale) au aspect "
            "normal. Spațiul articular este păstrat, fără fracturi sau luxații.",
            "Aspect radiologic normal al genunchiului.",
            _APT,
        ),
        "normala": Rezultat(
            "Structuri osoase integre, fără traiecte de fractură. Se observă un ușor revărsat articular "
            "posttraumatic și tumefierea părților moi periarticulare.",
            "Fără leziuni osoase. Contuzie a genunchiului cu revărsat articular minim.",
            "Repaus, gheață local, bandaj elastic și antiinflamatoare 5–7 zile.",
        ),
        "rea": Rezultat(
            "Se evidențiază o fisură fără deplasare la nivelul platoului tibial lateral. Rotula și femurul "
            "distal sunt integre. Revărsat articular moderat.",
            "Fisură a platoului tibial lateral, fără deplasare.",
            "Imobilizare în orteză, mers cu cârje fără sprijin 4–6 săptămâni, antialgice și control radiologic.",
        ),
        "grava": Rezultat(
            "Fractură cominutivă a platoului tibial lateral, cu înfundarea suprafeței articulare, asociată cu "
            "fractură transversală a rotulei cu separarea fragmentelor. Hemartroză importantă.",
            "Fractură cominutivă de platou tibial și fractură de rotulă — traumatism grav al genunchiului.",
            "Intervenție chirurgicală de urgență (osteosinteză), internare, imobilizare și program de "
            "recuperare medicală de durată.",
        ),
    },
}


# ----------------------------------------------------------------------
# ANALIZE DE LABORATOR
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Analiza:
    group: str
    name: str
    unit: str
    low: float
    high: float
    decimals: int
    rea: Optional[tuple[float, float]] = None
    grava: Optional[tuple[float, float]] = None

    @property
    def reference(self) -> str:
        if self.low == 0:
            return f"< {format_number(self.high, self.decimals)}"
        return f"{format_number(self.low, self.decimals)} – {format_number(self.high, self.decimals)}"


ANALIZE: list[Analiza] = [
    Analiza("Hematologie", "Hemoglobină (HGB)", "g/dL", 12.0, 17.5, 1, (10.2, 11.4), (6.8, 8.6)),
    Analiza("Hematologie", "Hematocrit (HCT)", "%", 36.0, 50.0, 1, (31.0, 34.5), (20.5, 26.0)),
    Analiza("Hematologie", "Leucocite (WBC)", "×10³/µL", 4.0, 10.0, 2, (11.6, 15.4), (17.5, 26.0)),
    Analiza("Hematologie", "Trombocite (PLT)", "×10³/µL", 150, 400, 0, None, (82, 128)),
    Analiza("Biochimie", "Glicemie", "mg/dL", 70, 105, 0, None, (168, 236)),
    Analiza("Biochimie", "Uree", "mg/dL", 15, 45, 0, None, (62, 98)),
    Analiza("Biochimie", "Creatinină", "mg/dL", 0.6, 1.2, 2, None, (1.65, 2.6)),
    Analiza("Biochimie", "TGO (AST)", "U/L", 0, 40, 0, (46, 72), (96, 260)),
    Analiza("Biochimie", "TGP (ALT)", "U/L", 0, 41, 0, None, (84, 210)),
    Analiza("Markeri inflamatori", "Proteina C reactivă (PCR)", "mg/L", 0, 5.0, 1, (18, 58), (86, 190)),
    Analiza("Markeri inflamatori", "VSH", "mm/h", 2, 20, 0, (28, 46), (52, 88)),
]


def format_number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


@dataclass(frozen=True)
class ValoareAnaliza:
    test: Analiza
    value: float

    @property
    def flag(self) -> str:
        """``low``, ``high`` sau ``normal`` față de intervalul de referință."""
        if self.value < self.test.low:
            return "low"
        if self.value > self.test.high:
            return "high"
        return "normal"

    @property
    def text(self) -> str:
        return format_number(self.value, self.test.decimals)

    @property
    def arrow(self) -> str:
        return {"low": "↓", "high": "↑"}.get(self.flag, "")


def generate_lab_results(stare: str, seed: int) -> list[ValoareAnaliza]:
    """Valorile analizelor pentru starea aleasă, reproductibile pentru același ``seed``."""
    rng = random.Random(seed)
    results = []
    for test in ANALIZE:
        span = test.high - test.low
        if stare == "grava" and test.grava:
            low, high = test.grava
        elif stare in {"rea", "grava"} and test.rea:
            low, high = test.rea
        elif stare == "buna":
            low, high = test.low + span * 0.3, test.low + span * 0.7
        else:
            low, high = test.low + span * 0.12, test.low + span * 0.88
        value = round(rng.uniform(low, high), test.decimals)
        results.append(ValoareAnaliza(test, value))
    return results


INTERPRETARE: dict[str, tuple[str, str]] = {
    "buna": (
        "Toți parametrii analizați se încadrează în intervalele de referință. Nu se constată modificări "
        "patologice ale hemogramei, ale probelor biochimice sau ale markerilor inflamatori.",
        "Rezultate normale — pacient sănătos, apt pentru activitate.",
    ),
    "normala": (
        "Parametrii analizați se încadrează în limitele normale, fără modificări cu semnificație clinică. "
        "Unele valori se află spre limitele intervalului de referință, fără a necesita tratament.",
        "Rezultate în limite normale — se recomandă hidratare corespunzătoare și control periodic.",
    ),
    "rea": (
        "Se constată anemie ușoară (hemoglobină și hematocrit scăzute), leucocitoză și valori crescute ale "
        "proteinei C reactive, VSH și TGO, modificări sugestive pentru un proces inflamator sau posttraumatic "
        "în desfășurare.",
        "Stare de sănătate alterată — necesită tratament de specialitate și reevaluarea analizelor "
        "în 48–72 de ore.",
    ),
    "grava": (
        "Valorile indică anemie severă (posibilă hemoragie internă), leucocitoză marcată și sindrom inflamator "
        "sever, trombocitopenie, hiperglicemie de stres, precum și afectare renală (uree și creatinină crescute) "
        "și hepatică (TGO și TGP crescute).",
        "Stare gravă — se impune internarea de urgență în terapie intensivă, monitorizare continuă și "
        "tratament de specialitate.",
    ),
}
