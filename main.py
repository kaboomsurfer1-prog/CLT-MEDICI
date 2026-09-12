"""Legacy EMS — bot de contracte de angajare și demisii.

Flux angajare (serverul principal Legacy of CLT):
    1. Un membru cu rol de recrutare folosește `/contract` în canalul de contracte.
    2. Botul taghează membrul și îi dă două butoane: Acceptă / Semnează sau
       Refuză contractul. Membrul nu trebuie să scrie nimic.
    3. La semnare se generează contractul (imagine PNG) cu ambele semnături,
       se salvează automat data și ora intrării, se postează contractul în
       serverul EMS și se trimite invitația către membru.

Flux demisie (serverul EMS):
    1. Membrul scrie modelul `Nume / Ore / Motiv` în canalul de demisii.
    2. Conducerea acceptă sau refuză din butoane.
    3. La acceptare se generează Decizia de Încetare a Contractului, cu
       semnături, data intrării, data încetării și zilele lucrate.
"""

from __future__ import annotations

import asyncio
import io
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import documents
from config import (
    BOT_PREFIX,
    BOT_VERSION,
    CITY_NAME,
    CONTRACT_CHANNEL_ID,
    CONTRACT_LOG_CHANNEL_ID,
    DB_PATH,
    DEFAULT_FUNCTION,
    DELETE_TRIGGER_MESSAGE,
    DEMISIE_CHANNEL_ID,
    DEPARTMENT_NAME,
    DEPARTMENT_SUBTITLE,
    DISCORD_TOKEN,
    EMS_GUILD_ID,
    EMS_INVITE_CHANNEL_ID,
    EMS_LOGO_URL,
    EMS_LOG_CHANNEL_ID,
    INVITE_MAX_AGE,
    INVITE_MAX_USES,
    LOCAL_TZ,
    MAIN_GUILD_ID,
    MAIN_LOGO_URL,
    MAIN_LOG_CHANNEL_ID,
    RECRUITER_ROLE_IDS,
    STAFF_ROLE_IDS,
    log,
    validate_config_startup,
)
from database import db
from utils import (
    clean_line,
    duration_seconds_between,
    format_date_ro,
    format_days,
    format_dt,
    format_duration_seconds,
    now_iso,
    now_local,
    status_ro,
    top_role_name,
    unix_from_iso,
    user_mention,
    validate_cnp,
    validate_grade,
    validate_name,
)

BASE_DIR = Path(__file__).resolve().parent
LOGO_DIR = BASE_DIR / "assets" / "logos"

CONTRACT_ACCEPT_CUSTOM_ID = "legacy_ems_contract_accept"
CONTRACT_REFUSE_CUSTOM_ID = "legacy_ems_contract_refuse"


# =========================
# HELPERE GENERALE
# =========================

def new_document_id(prefix: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{now_local():%Y%m%d}-{suffix}"


def has_any_role(member: discord.abc.User, role_ids: set[int]) -> bool:
    if not isinstance(member, discord.Member):
        return False
    return any(role.id in role_ids for role in member.roles)


def is_recruiter(member: discord.abc.User) -> bool:
    if has_any_role(member, RECRUITER_ROLE_IDS):
        return True
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def is_staff(member: discord.abc.User) -> bool:
    if has_any_role(member, STAFF_ROLE_IDS):
        return True
    if not isinstance(member, discord.Member):
        return False
    # Fără STAFF_ROLE_IDS configurat, cade pe permisiunea de gestionare server.
    if not STAFF_ROLE_IDS and member.guild_permissions.manage_guild:
        return True
    return member.guild_permissions.administrator


def channel_matches(channel: Optional[discord.abc.GuildChannel], channel_id: int) -> bool:
    if channel is None or not channel_id:
        return False
    if channel.id == channel_id:
        return True
    return getattr(channel, "parent_id", None) == channel_id


def make_file(payload: bytes, filename: str) -> discord.File:
    return discord.File(io.BytesIO(payload), filename=filename)


def display_tag(user: discord.abc.User) -> str:
    name = getattr(user, "name", str(user))
    return f"@{name}"


async def send_to_channel(
    channel_id: int,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    file_payload: Optional[bytes] = None,
    filename: str = "document.png",
) -> Optional[discord.Message]:
    if not channel_id:
        return None
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        log.exception("Nu am putut accesa canalul %s.", channel_id)
        return None

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.warning("Canalul %s nu este TextChannel/Thread.", channel_id)
        return None

    kwargs: dict = {}
    if content:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if file_payload is not None:
        kwargs["file"] = make_file(file_payload, filename)
    try:
        return await channel.send(**kwargs)
    except discord.HTTPException:
        log.exception("Nu am putut trimite mesajul în canalul %s.", channel_id)
        return None


async def try_dm(
    user_id: int,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    file_payload: Optional[bytes] = None,
    filename: str = "document.png",
) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        kwargs: dict = {}
        if content:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if file_payload is not None:
            kwargs["file"] = make_file(file_payload, filename)
        await user.send(**kwargs)
        return True
    except (discord.Forbidden, discord.HTTPException, discord.NotFound):
        return False


# =========================
# LOGO-URI
# =========================

class LogoStore:
    """Logo-urile folosite pe documente.

    Ordine: fișier local în ``assets/logos`` -> variabilă de mediu cu URL -> iconița serverului.
    """

    LOCAL_NAMES = {
        "main": ("main.png", "main.jpg", "main.jpeg", "main.webp", "logo_main.png", "clt.png"),
        "ems": ("ems.png", "ems.jpg", "ems.jpeg", "ems.webp", "logo_ems.png"),
    }

    def __init__(self) -> None:
        self._cache: dict[str, Optional[bytes]] = {}
        self._warned: set[str] = set()

    async def get(self, key: str) -> Optional[bytes]:
        if self._cache.get(key):
            return self._cache[key]

        payload = self._from_disk(key) or await self._from_url(key) or await self._from_guild_icon(key)
        self._cache[key] = payload
        if payload is None and key not in self._warned:
            self._warned.add(key)
            log.warning(
                "Nu am găsit logo pentru '%s'. Documentele folosesc un substitut. "
                "Adaugă assets/logos/%s.png sau setează %s_LOGO_URL.",
                key,
                key,
                key.upper(),
            )
        return payload

    def _from_disk(self, key: str) -> Optional[bytes]:
        for name in self.LOCAL_NAMES.get(key, ()):
            path = LOGO_DIR / name
            if path.exists() and path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    log.exception("Nu am putut citi logo-ul %s.", path)
        return None

    async def _from_url(self, key: str) -> Optional[bytes]:
        url = MAIN_LOGO_URL if key == "main" else EMS_LOGO_URL
        if not url:
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.read()
                    log.warning("Logo %s: răspuns HTTP %s de la %s.", key, response.status, url)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("Nu am putut descărca logo-ul de la %s.", url)
        return None

    async def _from_guild_icon(self, key: str) -> Optional[bytes]:
        guild_id = MAIN_GUILD_ID if key == "main" else EMS_GUILD_ID
        guild = bot.get_guild(guild_id)
        if guild is None or guild.icon is None:
            return None

        asset = guild.icon
        try:
            asset = asset.with_size(512)
        except ValueError:
            pass
        if not asset.is_animated():
            try:
                asset = asset.with_format("png")
            except ValueError:
                pass
        try:
            return await asset.read()
        except (discord.HTTPException, discord.NotFound, discord.DiscordException):
            log.exception("Nu am putut citi iconița serverului %s.", guild_id)
            return None


logos = LogoStore()


async def document_logos() -> tuple[Optional[bytes], Optional[bytes]]:
    return await logos.get("main"), await logos.get("ems")


# =========================
# INVITAȚIE SERVER EMS
# =========================

async def create_ems_invite(reason: str) -> Optional[str]:
    guild = bot.get_guild(EMS_GUILD_ID)
    if guild is None:
        log.warning("Botul nu este în serverul EMS %s, nu pot genera invitația.", EMS_GUILD_ID)
        return None

    candidates: list[discord.abc.GuildChannel] = []
    if EMS_INVITE_CHANNEL_ID:
        channel = guild.get_channel(EMS_INVITE_CHANNEL_ID)
        if channel is not None:
            candidates.append(channel)
    for channel in (guild.rules_channel, guild.system_channel):
        if channel is not None:
            candidates.append(channel)
    candidates.extend(sorted(guild.text_channels, key=lambda c: c.position))

    seen: set[int] = set()
    for channel in candidates:
        if channel.id in seen:
            continue
        seen.add(channel.id)
        permissions = channel.permissions_for(guild.me)
        if not permissions.create_instant_invite:
            continue
        try:
            invite = await channel.create_invite(
                max_age=INVITE_MAX_AGE,
                max_uses=INVITE_MAX_USES,
                unique=True,
                reason=reason[:400],
            )
            return invite.url
        except (discord.Forbidden, discord.HTTPException):
            continue

    log.warning("Nu am putut genera nicio invitație în serverul EMS %s.", EMS_GUILD_ID)
    return None


# =========================
# DATA INTRĂRII
# =========================

async def resolve_join_date(user_id: int, ems_member: Optional[discord.Member] = None) -> Optional[str]:
    """Data intrării: contract semnat -> valoare salvată -> intrarea pe Discord."""
    contract = await db.get_active_contract(user_id)
    if contract and contract.get("signed_at"):
        return contract["signed_at"]

    stored = await db.get_join_date(user_id)
    if stored:
        return stored

    if ems_member is not None and ems_member.joined_at is not None:
        return ems_member.joined_at.astimezone(LOCAL_TZ).isoformat()
    return None


async def fetch_ems_member(user_id: int) -> Optional[discord.Member]:
    guild = bot.get_guild(EMS_GUILD_ID)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None


# =========================
# EMBED-URI CONTRACT
# =========================

def build_contract_pending_embed(row: dict, member: discord.abc.User, recruiter: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📄 Contract de angajare în așteptare",
        description=(
            f"{member.mention}, ai primit un contract de angajare în **{DEPARTMENT_NAME}**.\n\n"
            "Apasă **✍️ Acceptă / Semnează** pentru a semna contractul sau "
            "**❌ Refuză contractul** dacă nu ești de acord. Nu trebuie să scrii nimic.\n"
            "Contractul devine valabil **doar după ce îl accepți tu**."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="👤 Membru", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="🪪 Nume IC", value=row["nume_ic"], inline=True)
    embed.add_field(name="🔢 CNP", value=row["cnp"], inline=True)
    embed.add_field(name="🎖️ Grad acordat", value=row.get("functie") or DEFAULT_FUNCTION, inline=True)
    embed.add_field(name="✍️ Angajator", value=f"{recruiter.mention}\n{row['recruiter_signature']}", inline=True)
    embed.add_field(name="🎖️ Grad angajator", value=row["recruiter_grade"], inline=True)
    embed.add_field(name="📌 Status", value="🟡 Așteaptă răspunsul angajatului", inline=False)
    embed.set_footer(text=f"ID contract: {row['id']}")
    return embed


def build_contract_refused_embed(row: dict, member: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="❌ Contract refuzat",
        description=(
            f"{member.mention} a refuzat contractul de angajare în **{DEPARTMENT_NAME}**.\n"
            "Contractul nu a intrat în vigoare și nu a fost setată nicio dată de intrare."
        ),
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🪪 Nume IC", value=row["nume_ic"], inline=True)
    embed.add_field(name="🎖️ Grad propus", value=row.get("functie") or DEFAULT_FUNCTION, inline=True)
    embed.add_field(name="✍️ Emis de", value=user_mention(row["recruiter_id"]), inline=True)
    embed.add_field(name="📌 Status", value="🔴 Refuzat de angajat", inline=False)
    embed.set_footer(text=f"ID contract: {row['id']}")
    return embed


def build_contract_signed_embed(row: dict) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Contract semnat",
        description=(
            f"{user_mention(row['user_id'])} a semnat contractul de angajare în **{DEPARTMENT_NAME}** "
            f"({DEPARTMENT_SUBTITLE})."
        ),
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🪪 Nume IC", value=row["nume_ic"], inline=True)
    embed.add_field(name="🔢 CNP", value=row["cnp"], inline=True)
    embed.add_field(name="🎖️ Grad acordat", value=row.get("functie") or DEFAULT_FUNCTION, inline=True)
    embed.add_field(name="✍️ Semnătura angajatului", value=row.get("member_signature") or "—", inline=True)
    embed.add_field(name="🎖️ Angajat de", value=f"{row['recruiter_signature']}\n{row['recruiter_grade']}", inline=True)
    signed_ts = unix_from_iso(row.get("signed_at"))
    embed.add_field(
        name="📅 Data intrării",
        value=f"<t:{signed_ts}:F>" if signed_ts else format_dt(row.get("signed_at")),
        inline=True,
    )
    embed.set_image(url="attachment://contract.png")
    embed.set_footer(text=f"ID contract: {row['id']} • {DEPARTMENT_NAME}")
    return embed


def build_termination_embed(contract: Optional[dict], resignation: dict, durata: str, zile: str) -> discord.Embed:
    embed = discord.Embed(
        title="📕 Decizie de încetare a contractului",
        description=(
            f"{user_mention(resignation['user_id'])} nu mai face parte din **{DEPARTMENT_NAME}** "
            f"({DEPARTMENT_SUBTITLE})."
        ),
        color=discord.Color.dark_red(),
        timestamp=datetime.now(timezone.utc),
    )
    if contract:
        embed.add_field(name="🪪 Nume IC", value=contract["nume_ic"], inline=True)
        embed.add_field(name="🔢 CNP", value=contract["cnp"], inline=True)
        embed.add_field(name="🎖️ Grad deținut", value=contract.get("functie") or DEFAULT_FUNCTION, inline=True)
    elif resignation.get("request_name"):
        embed.add_field(name="🪪 Nume", value=resignation["request_name"][:256], inline=True)

    embed.add_field(name="📅 Data intrării", value=format_dt(resignation.get("join_date")), inline=True)
    embed.add_field(
        name="📅 Data încetării",
        value=format_dt(resignation.get("decided_at") or now_iso()),
        inline=True,
    )
    embed.add_field(name="⏳ Perioadă lucrată", value=durata, inline=True)
    embed.add_field(name="🗓️ Total zile", value=zile, inline=True)
    if resignation.get("decided_by"):
        embed.add_field(name="👮 Aprobată de", value=user_mention(resignation["decided_by"]), inline=True)
    if resignation.get("request_reason"):
        embed.add_field(name="📝 Motiv", value=resignation["request_reason"][:1024], inline=False)
    embed.set_image(url="attachment://demisie.png")
    embed.set_footer(text=f"ID cerere: {resignation['id']} • {DEPARTMENT_NAME}")
    return embed


# =========================
# EMBED-URI DEMISIE
# =========================

def build_pending_embed(
    member: discord.Member,
    request_id: str,
    join_date_iso: Optional[str],
    request_reason: str,
    request_name: str,
    request_hours: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="📋 Cerere de Demisie",
        description=(
            f"{member.mention} a depus o cerere de demisie din **{DEPARTMENT_NAME}**.\n\n"
            "Conducerea trebuie să aleagă o acțiune folosind butoanele de mai jos."
        ),
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="👤 Membru", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="🪪 Nume", value=request_name[:256], inline=True)
    embed.add_field(name="⏱️ Ore", value=request_hours[:256], inline=True)
    embed.add_field(name="📅 Data intrării", value=format_dt(join_date_iso), inline=True)
    embed.add_field(
        name="⏳ Timp în departament",
        value=format_duration_seconds(duration_seconds_between(join_date_iso)),
        inline=True,
    )
    embed.add_field(name="📝 Motiv", value=request_reason[:1024], inline=False)
    embed.add_field(name="📌 Status", value="🟡 În așteptare", inline=False)
    embed.set_footer(text=f"ID cerere: {request_id}")
    return embed


def build_decision_embed(row: dict) -> discord.Embed:
    status = row["status"]
    if status == "ACCEPTED":
        title, color, status_line = "✅ Demisie Acceptată", discord.Color.green(), "🟢 Acceptată"
    elif status == "REFUSED":
        title, color, status_line = "❌ Demisie Refuzată", discord.Color.red(), "🔴 Refuzată"
    else:
        title, color, status_line = "📋 Cerere de Demisie", discord.Color.orange(), "🟡 În așteptare"

    embed = discord.Embed(
        title=title,
        description=f"Cererea de demisie pentru {user_mention(row['user_id'])} a fost actualizată.",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="👤 Membru", value=f"{user_mention(row['user_id'])}\n`{row['user_id']}`", inline=True)
    if row.get("request_name"):
        embed.add_field(name="🪪 Nume", value=row["request_name"][:256], inline=True)
    if row.get("request_hours"):
        embed.add_field(name="⏱️ Ore", value=row["request_hours"][:256], inline=True)
    embed.add_field(name="📅 Data intrării", value=format_dt(row.get("join_date")), inline=True)
    embed.add_field(
        name="⏳ Timp în departament",
        value=format_duration_seconds(
            duration_seconds_between(row.get("join_date"), row.get("decided_at") or None)
        ),
        inline=True,
    )
    embed.add_field(name="📌 Status", value=status_line, inline=False)
    if row.get("request_reason"):
        embed.add_field(name="📝 Motiv", value=row["request_reason"][:1024], inline=False)
    if row.get("decided_by"):
        embed.add_field(name="👮 Decizie luată de", value=user_mention(row["decided_by"]), inline=True)
    decided_ts = unix_from_iso(row.get("decided_at"))
    if decided_ts:
        embed.add_field(name="🕒 Data deciziei", value=f"<t:{decided_ts}:F>", inline=True)
    if status == "REFUSED" and row.get("reason"):
        embed.add_field(name="📝 Motivul refuzului", value=row["reason"][:1024], inline=False)

    embed.add_field(name="⚠️ Roluri", value="Rolurile se elimină manual de către conducere.", inline=False)
    embed.set_footer(text=f"ID cerere: {row['id']}")
    return embed


def build_refused_public_embed(row: dict) -> discord.Embed:
    embed = discord.Embed(
        title="❌ Demisie Refuzată",
        description=f"{user_mention(row['user_id'])}, demisia ta a fost refuzată de către conducere.",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    if row.get("decided_by"):
        embed.add_field(name="👮 Refuzată de", value=user_mention(row["decided_by"]), inline=True)
    if row.get("request_name"):
        embed.add_field(name="🪪 Nume", value=row["request_name"][:256], inline=True)
    if row.get("request_hours"):
        embed.add_field(name="⏱️ Ore", value=row["request_hours"][:256], inline=True)
    if row.get("request_reason"):
        embed.add_field(name="📝 Motiv", value=row["request_reason"][:1024], inline=False)
    embed.add_field(name="📝 Motivul refuzului", value=(row.get("reason") or "Nespecificat")[:1024], inline=False)
    embed.set_footer(text=f"{DEPARTMENT_NAME} • {DEPARTMENT_SUBTITLE}")
    return embed


def demisie_format_message() -> str:
    return (
        "⚠️ Trebuie să folosești modelul corect pentru demisie.\n"
        "```\n"
        "Nume: numele tău\n"
        "Ore: numărul de ore\n"
        "Motiv: motivul demisiei\n"
        "```\n"
        "Exemplu:\n"
        "```\n"
        "Nume: Jmarok\n"
        "Ore: 120\n"
        "Motiv: Nu mai am timp să activez în departament.\n"
        "```"
    )


def parse_demisie_template(content: str) -> Optional[tuple[str, str, str]]:
    text = re.sub(r"^\s*(demisia|demisie)\s*[:\-]?\s*", "", content.strip(), flags=re.IGNORECASE)
    match = re.search(
        r"(?is)^\s*nume\s*:\s*(?P<nume>.+?)\s+ore\s*:\s*(?P<ore>.+?)\s+motiv\s*:\s*(?P<motiv>.+?)\s*$",
        text,
    )
    if not match:
        return None
    return (
        re.sub(r"\s+", " ", match.group("nume")).strip(),
        re.sub(r"\s+", " ", match.group("ore")).strip(),
        match.group("motiv").strip(),
    )


# =========================
# GENERARE DOCUMENTE
# =========================

async def build_contract_png(row: dict, member: discord.abc.User, recruiter: discord.abc.User) -> bytes:
    logo_main, logo_ems = await document_logos()
    return await asyncio.to_thread(
        documents.render_contract,
        contract_id=row["id"],
        nume_ic=row["nume_ic"],
        cnp=row["cnp"],
        functie=row.get("functie") or DEFAULT_FUNCTION,
        discord_tag=display_tag(member),
        discord_id=str(row["user_id"]),
        data_angajarii=format_date_ro(row.get("signed_at")),
        semnatura_angajat=row.get("member_signature") or row["nume_ic"],
        semnatura_angajator=row["recruiter_signature"],
        grad_angajator=row["recruiter_grade"],
        angajator_discord=display_tag(recruiter),
        emis_la=format_dt(row.get("signed_at") or row.get("created_at")),
        city=CITY_NAME,
        department=DEPARTMENT_NAME,
        department_subtitle=DEPARTMENT_SUBTITLE,
        logo_main=logo_main,
        logo_ems=logo_ems,
    )


async def build_termination_png(
    *,
    document_id: str,
    contract: Optional[dict],
    resignation: dict,
    member: Optional[discord.abc.User],
    staff: discord.abc.User,
    staff_signature: str,
    staff_grade: str,
    join_date_iso: Optional[str],
    end_iso: str,
    worked_seconds: Optional[int],
) -> bytes:
    logo_main, logo_ems = await document_logos()
    nume_ic = (contract or {}).get("nume_ic") or resignation.get("request_name") or "Necunoscut"
    member_signature = (contract or {}).get("member_signature") or nume_ic
    return await asyncio.to_thread(
        documents.render_termination,
        document_id=document_id,
        contract_id=(contract or {}).get("id") or "fără contract înregistrat",
        nume_ic=nume_ic,
        cnp=(contract or {}).get("cnp") or "—",
        functie=(contract or {}).get("functie") or DEFAULT_FUNCTION,
        discord_tag=display_tag(member) if member else f"ID {resignation['user_id']}",
        discord_id=str(resignation["user_id"]),
        data_angajarii=format_date_ro(join_date_iso) if join_date_iso else "—",
        data_incetarii=format_date_ro(end_iso),
        durata=format_duration_seconds(worked_seconds),
        zile=format_days(worked_seconds // 86400 if worked_seconds is not None else None),
        motiv=resignation.get("request_reason") or "Demisie la cerere.",
        semnatura_angajat=member_signature,
        semnatura_conducere=staff_signature,
        grad_conducere=staff_grade,
        conducere_discord=display_tag(staff),
        city=CITY_NAME,
        department=DEPARTMENT_NAME,
        department_subtitle=DEPARTMENT_SUBTITLE,
        logo_main=logo_main,
        logo_ems=logo_ems,
    )


# =========================
# VIEW CONTRACT (2 BUTOANE)
# =========================

class ContractDecisionView(discord.ui.View):
    """Cele două butoane din mesajul contractului: acceptă sau refuză.

    Angajatul nu trebuie să scrie nimic — semnătura lui este numele IC
    completat de angajator în `/contract`.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @classmethod
    def disabled(cls) -> "ContractDecisionView":
        view = cls()
        for item in view.children:
            item.disabled = True
        return view

    @discord.ui.button(
        label="Acceptă / Semnează",
        style=discord.ButtonStyle.success,
        custom_id=CONTRACT_ACCEPT_CUSTOM_ID,
        emoji="✍️",
    )
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        contract = await resolve_own_contract(interaction)
        if not contract:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await finalize_contract(interaction, contract["id"], contract["nume_ic"])

    @discord.ui.button(
        label="Refuză contractul",
        style=discord.ButtonStyle.danger,
        custom_id=CONTRACT_REFUSE_CUSTOM_ID,
        emoji="❌",
    )
    async def refuse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        contract = await resolve_own_contract(interaction)
        if not contract:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await refuse_contract(interaction, contract)


async def resolve_own_contract(interaction: discord.Interaction) -> Optional[dict]:
    """Contractul din mesajul apăsat, dacă cel care apasă este chiar angajatul."""
    if interaction.guild_id != MAIN_GUILD_ID:
        await interaction.response.send_message(
            "❌ Contractele se semnează doar pe serverul principal Legacy of CLT.",
            ephemeral=True,
        )
        return None

    contract = None
    if interaction.message is not None:
        contract = await db.get_contract_by_message(interaction.message.id)
    if contract is None:
        contract = await db.get_pending_contract(interaction.user.id)
    if contract is None:
        await interaction.response.send_message(
            "❌ Nu am găsit contractul acestui mesaj. Cere conducerii să emită unul nou cu `/contract`.",
            ephemeral=True,
        )
        return None

    if int(contract["user_id"]) != interaction.user.id:
        await interaction.response.send_message(
            f"❌ Doar {user_mention(contract['user_id'])} poate răspunde la acest contract.",
            ephemeral=True,
        )
        return None

    if contract["status"] != "PENDING_SIGN":
        await interaction.response.send_message(
            f"⚠️ Acest contract este deja **{status_ro(contract['status']).lower()}**.",
            ephemeral=True,
        )
        return None

    return contract


async def refuse_contract(interaction: discord.Interaction, contract: dict) -> None:
    updated = await db.refuse_contract(contract["id"], now_iso())
    if not updated or updated["status"] != "REFUSED":
        await interaction.followup.send(
            f"⚠️ Contractul este deja **{status_ro((updated or contract)['status']).lower()}**.",
            ephemeral=True,
        )
        return

    embed = build_contract_refused_embed(updated, interaction.user)
    await update_contract_message(updated, embed)

    recruiter_mention = user_mention(updated["recruiter_id"])
    await send_to_channel(
        CONTRACT_CHANNEL_ID,
        content=f"❌ {recruiter_mention} — {interaction.user.mention} a refuzat contractul `{updated['id']}`.",
        embed=build_contract_refused_embed(updated, interaction.user),
    )
    await try_dm(
        int(updated["recruiter_id"]),
        content=(
            f"❌ {interaction.user.mention} a refuzat contractul `{updated['id']}` "
            f"pentru **{updated['nume_ic']}**."
        ),
    )
    await interaction.followup.send(
        "❌ Ai refuzat contractul. Conducerea a fost anunțată.", ephemeral=True
    )


async def update_contract_message(row: dict, embed: Optional[discord.Embed] = None) -> None:
    """Dezactivează butoanele din mesajul original al contractului."""
    if not row.get("message_id") or not row.get("channel_id"):
        return
    try:
        channel = bot.get_channel(int(row["channel_id"])) or await bot.fetch_channel(int(row["channel_id"]))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        message = await channel.fetch_message(int(row["message_id"]))
        if embed is not None:
            await message.edit(embed=embed, view=ContractDecisionView.disabled())
        else:
            await message.edit(view=ContractDecisionView.disabled())
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        log.exception("Nu am putut actualiza mesajul contractului %s.", row["id"])


async def finalize_contract(interaction: discord.Interaction, contract_id: str, signature: str) -> None:
    signed_at = now_local()
    row = await db.sign_contract(contract_id, signature, signed_at.isoformat())
    if not row:
        await interaction.followup.send("❌ Contractul nu mai există în baza de date.", ephemeral=True)
        return
    if row["status"] != "SIGNED":
        await interaction.followup.send(
            f"⚠️ Contractul este deja **{status_ro(row['status']).lower()}**.", ephemeral=True
        )
        return

    member = interaction.user
    recruiter_id = int(row["recruiter_id"])
    recruiter = bot.get_user(recruiter_id)
    if recruiter is None:
        try:
            recruiter = await bot.fetch_user(recruiter_id)
        except (discord.NotFound, discord.HTTPException):
            recruiter = member

    # Data și ora intrării se setează automat la momentul semnării.
    await db.set_join_date(member.id, signed_at, recruiter_id)

    try:
        png = await build_contract_png(row, member, recruiter)
    except Exception:  # noqa: BLE001
        log.exception("Eroare la generarea contractului %s.", contract_id)
        await interaction.followup.send(
            "❌ Contractul a fost semnat, dar generarea imaginii a eșuat. Anunță un administrator.",
            ephemeral=True,
        )
        return

    embed = build_contract_signed_embed(row)

    # 1. Canalul de contracte din serverul principal.
    await send_to_channel(
        CONTRACT_CHANNEL_ID,
        content=f"📄 Contract finalizat pentru {member.mention} · angajat de {recruiter.mention}",
        embed=embed,
        file_payload=png,
        filename="contract.png",
    )

    # 2. Canalul de contracte din serverul EMS.
    await send_to_channel(
        CONTRACT_LOG_CHANNEL_ID,
        content=f"📄 Contract nou în {DEPARTMENT_NAME} · {member.mention}",
        embed=build_contract_signed_embed(row),
        file_payload=png,
        filename="contract.png",
    )

    # 3. Dezactivează butonul din mesajul inițial.
    await update_contract_message(row)

    # 4. Invitație în serverul EMS + document prin DM.
    invite_url = await create_ems_invite(f"Angajare {row['nume_ic']} ({member.id})")
    dm_lines = [
        f"🎉 **Bun venit în {DEPARTMENT_NAME}, {row['nume_ic']}!**",
        f"Contractul tău (`{row['id']}`) a fost semnat pe **{format_date_ro(row['signed_at'])}**.",
    ]
    if invite_url:
        dm_lines.append(f"\n🔗 Intră pe serverul departamentului: {invite_url}")
    dm_sent = await try_dm(
        member.id,
        content="\n".join(dm_lines),
        file_payload=png,
        filename="contract.png",
    )

    confirmation = [
        f"✅ Contractul **{row['id']}** a fost semnat și generat.",
        f"📅 Data intrării a fost setată automat: **{format_dt(row['signed_at'])}**.",
    ]
    if invite_url:
        confirmation.append(f"🔗 Invitația ta în serverul {DEPARTMENT_NAME}: {invite_url}")
    else:
        confirmation.append(
            "⚠️ Nu am putut genera invitația automat. Cere linkul conducerii."
        )
    if not dm_sent:
        confirmation.append("⚠️ Nu am putut să-ți trimit DM. Salvează contractul din canal.")

    await interaction.followup.send("\n".join(confirmation), ephemeral=True)


# =========================
# VIEW + MODAL DEMISIE
# =========================

class DemisieDecisionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @classmethod
    def disabled(cls) -> "DemisieDecisionView":
        view = cls()
        for item in view.children:
            item.disabled = True
        return view

    async def _get_pending_request_or_reply(self, interaction: discord.Interaction) -> Optional[dict]:
        if not interaction.message:
            await interaction.response.send_message("❌ Nu am putut identifica mesajul cererii.", ephemeral=True)
            return None

        row = await db.get_by_message_id(interaction.message.id)
        if not row:
            await interaction.response.send_message("❌ Cererea nu există în baza de date.", ephemeral=True)
            return None
        if row["status"] != "PENDING":
            await interaction.response.send_message(
                f"⚠️ Această cerere este deja **{status_ro(row['status']).lower()}**.",
                ephemeral=True,
            )
            return None
        return row

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != EMS_GUILD_ID:
            await interaction.response.send_message(
                "❌ Acest buton funcționează doar pe serverul EMS.", ephemeral=True
            )
            return False
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Nu ai permisiune să gestionezi demisii.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Acceptă Demisia",
        style=discord.ButtonStyle.success,
        custom_id="legacy_ems_demisie_accept",
        emoji="✅",
    )
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        row = await self._get_pending_request_or_reply(interaction)
        if not row:
            return

        default_signature = ""
        staff_contract = await db.get_last_contract(interaction.user.id)
        if staff_contract and staff_contract.get("member_signature"):
            default_signature = staff_contract["member_signature"]

        await interaction.response.send_modal(
            AcceptDemisieModal(
                int(row["message_id"]),
                default_signature,
                top_role_name(interaction.user),
            )
        )

    @discord.ui.button(
        label="Refuză Demisia",
        style=discord.ButtonStyle.danger,
        custom_id="legacy_ems_demisie_refuse",
        emoji="❌",
    )
    async def refuse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        row = await self._get_pending_request_or_reply(interaction)
        if not row:
            return
        await interaction.response.send_modal(RefuzDemisieModal(int(row["message_id"])))


class AcceptDemisieModal(discord.ui.Modal, title="Acceptare demisie"):
    def __init__(self, message_id: int, default_signature: str, default_grade: str):
        super().__init__(timeout=600)
        self.message_id = message_id
        self.semnatura = discord.ui.TextInput(
            label="Semnătura ta (Nume și Prenume IC)",
            placeholder="Exemplu: Mihai Ionescu",
            default=default_signature[:60] if default_signature else None,
            min_length=3,
            max_length=60,
            required=True,
        )
        self.grad = discord.ui.TextInput(
            label="Gradul tău",
            placeholder="Exemplu: Director Medical",
            default=default_grade[:60] if default_grade else None,
            min_length=2,
            max_length=60,
            required=True,
        )
        self.observatii = discord.ui.TextInput(
            label="Observații (opțional)",
            placeholder="Apare pe decizia de încetare, sub motivul demisiei.",
            style=discord.TextStyle.paragraph,
            max_length=400,
            required=False,
        )
        self.add_item(self.semnatura)
        self.add_item(self.grad)
        self.add_item(self.observatii)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Nu ai permisiune să accepți demisii.", ephemeral=True)
            return
        try:
            signature = validate_name(str(self.semnatura.value))
            grade = validate_grade(str(self.grad.value), "Gradul tău")
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await finalize_termination(
            interaction,
            self.message_id,
            signature,
            grade,
            clean_line(str(self.observatii.value or "")),
        )


class RefuzDemisieModal(discord.ui.Modal, title="Refuz Demisie"):
    motiv = discord.ui.TextInput(
        label="Motivul refuzului",
        placeholder="Scrie motivul complet pentru care demisia este refuzată...",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=1000,
        required=True,
    )

    def __init__(self, message_id: int):
        super().__init__(timeout=300)
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Nu ai permisiune să refuzi demisii.", ephemeral=True)
            return

        row = await db.get_by_message_id(self.message_id)
        if not row:
            await interaction.response.send_message("❌ Cererea nu există în baza de date.", ephemeral=True)
            return
        if row["status"] != "PENDING":
            await interaction.response.send_message(
                f"⚠️ Această cerere este deja **{status_ro(row['status']).lower()}**.", ephemeral=True
            )
            return

        updated = await db.decide(
            self.message_id,
            status="REFUSED",
            decided_by=interaction.user.id,
            reason=str(self.motiv.value).strip(),
            join_date_iso=row.get("join_date"),
            days=None,
        )
        if not updated or updated["status"] != "REFUSED":
            await interaction.response.send_message("⚠️ Cererea nu mai este în așteptare.", ephemeral=True)
            return

        await interaction.response.send_message(
            "❌ Demisia a fost refuzată. Mesajele au fost trimise.", ephemeral=True
        )

        try:
            channel = interaction.channel
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                channel = bot.get_channel(int(row["channel_id"])) or await bot.fetch_channel(int(row["channel_id"]))
            original = await channel.fetch_message(self.message_id)
            await original.edit(embed=build_decision_embed(updated), view=DemisieDecisionView.disabled())
            await channel.send(embed=build_refused_public_embed(updated))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.exception("Nu am putut actualiza mesajul demisiei refuzate.")

        await send_to_channel(EMS_LOG_CHANNEL_ID, embed=build_decision_embed(updated))
        await try_dm(int(updated["user_id"]), embed=build_refused_public_embed(updated))


async def finalize_termination(
    interaction: discord.Interaction,
    message_id: int,
    staff_signature: str,
    staff_grade: str,
    observatii: str,
) -> None:
    row = await db.get_by_message_id(message_id)
    if not row:
        await interaction.followup.send("❌ Cererea nu există în baza de date.", ephemeral=True)
        return
    if row["status"] != "PENDING":
        await interaction.followup.send(
            f"⚠️ Această cerere este deja **{status_ro(row['status']).lower()}**.", ephemeral=True
        )
        return

    user_id = int(row["user_id"])
    ems_member = await fetch_ems_member(user_id)
    join_date_iso = await resolve_join_date(user_id, ems_member) or row.get("join_date")
    end_dt = now_local()
    end_iso = end_dt.isoformat()
    worked_seconds = duration_seconds_between(join_date_iso, end_iso)
    days = worked_seconds // 86400 if worked_seconds is not None else None

    updated = await db.decide(
        message_id,
        status="ACCEPTED",
        decided_by=interaction.user.id,
        reason=observatii or None,
        join_date_iso=join_date_iso,
        days=days,
    )
    if not updated or updated["status"] != "ACCEPTED":
        await interaction.followup.send("⚠️ Cererea nu mai este în așteptare.", ephemeral=True)
        return

    contract = await db.get_active_contract(user_id) or await db.get_last_contract(user_id)
    document_id = new_document_id("DEM")

    if observatii:
        updated = dict(updated)
        updated["request_reason"] = f"{updated.get('request_reason') or ''}\n\nObservații conducere: {observatii}".strip()

    member_user = bot.get_user(user_id) or ems_member
    if member_user is None:
        try:
            member_user = await bot.fetch_user(user_id)
        except (discord.NotFound, discord.HTTPException):
            member_user = None

    png: Optional[bytes] = None
    try:
        png = await build_termination_png(
            document_id=document_id,
            contract=contract,
            resignation=updated,
            member=member_user,
            staff=interaction.user,
            staff_signature=staff_signature,
            staff_grade=staff_grade,
            join_date_iso=join_date_iso,
            end_iso=end_iso,
            worked_seconds=worked_seconds,
        )
    except Exception:  # noqa: BLE001
        log.exception("Eroare la generarea deciziei de încetare %s.", document_id)

    if contract and contract["status"] == "SIGNED":
        await db.terminate_contract(
            contract["id"],
            terminated_by=interaction.user.id,
            terminated_signature=staff_signature,
            terminated_grade=staff_grade,
            terminated_reason=updated.get("request_reason") or "Demisie la cerere.",
            terminated_at_iso=end_iso,
            worked_seconds=worked_seconds,
        )

    durata = format_duration_seconds(worked_seconds)
    zile = format_days(days)
    decision_embed = build_decision_embed(updated)

    # Mesajul original din canalul de demisii.
    try:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            channel = bot.get_channel(int(updated["channel_id"])) or await bot.fetch_channel(int(updated["channel_id"]))
        original = await channel.fetch_message(message_id)
        await original.edit(embed=decision_embed, view=DemisieDecisionView.disabled())
        if png:
            await channel.send(
                content=f"📕 Decizie de încetare pentru {user_mention(user_id)}",
                file=make_file(png, "demisie.png"),
            )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        log.exception("Nu am putut actualiza mesajul demisiei acceptate.")

    if png:
        termination_embed = build_termination_embed(contract, updated, durata, zile)
        await send_to_channel(
            CONTRACT_LOG_CHANNEL_ID,
            content=f"📕 Încetare contract · {user_mention(user_id)}",
            embed=termination_embed,
            file_payload=png,
            filename="demisie.png",
        )
        await send_to_channel(
            EMS_LOG_CHANNEL_ID,
            embed=build_termination_embed(contract, updated, durata, zile),
            file_payload=png,
            filename="demisie.png",
        )
        await send_to_channel(
            MAIN_LOG_CHANNEL_ID,
            content=(
                f"📢 {user_mention(user_id)} a părăsit **{DEPARTMENT_NAME}** după **{durata}**."
            ),
            embed=build_termination_embed(contract, updated, durata, zile),
            file_payload=png,
            filename="demisie.png",
        )
        await try_dm(
            user_id,
            content=(
                f"📕 Demisia ta din **{DEPARTMENT_NAME}** a fost acceptată.\n"
                f"📅 Data intrării: **{format_dt(join_date_iso)}**\n"
                f"📅 Data încetării: **{format_dt(end_iso)}**\n"
                f"⏳ Perioadă lucrată: **{durata}**"
            ),
            file_payload=png,
            filename="demisie.png",
        )
    else:
        await send_to_channel(EMS_LOG_CHANNEL_ID, embed=decision_embed)
        await send_to_channel(MAIN_LOG_CHANNEL_ID, embed=decision_embed)

    summary = [
        f"✅ Demisia a fost acceptată. Perioadă lucrată: **{durata}** ({zile}).",
    ]
    if png:
        summary.append("📕 Decizia de încetare a fost generată și trimisă.")
    else:
        summary.append("⚠️ Nu am putut genera imaginea deciziei. Logurile text au fost trimise.")
    await interaction.followup.send("\n".join(summary), ephemeral=True)


# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True


class LegacyEMSBot(commands.Bot):
    async def setup_hook(self) -> None:
        self.add_view(ContractDecisionView())
        self.add_view(DemisieDecisionView())

        # Comenzile vechi (/setintrare, /intrare, /demisii) erau înregistrate pe
        # serverul EMS și global. Le ștergem explicit.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        ems_guild = discord.Object(id=EMS_GUILD_ID)
        self.tree.clear_commands(guild=ems_guild)
        await self.tree.sync(guild=ems_guild)

        synced = await self.tree.sync(guild=discord.Object(id=MAIN_GUILD_ID))
        log.info(
            "Comenzi sincronizate pe serverul principal: %s",
            ", ".join(command.name for command in synced) or "niciuna",
        )


bot = LegacyEMSBot(command_prefix=BOT_PREFIX, intents=intents)
main_guild_obj = discord.Object(id=MAIN_GUILD_ID)


@bot.event
async def on_ready() -> None:
    log.info("Bot online ca %s | Servere: %s", bot.user, len(bot.guilds))
    log.info("Versiune bot: %s | DB: %s", BOT_VERSION, DB_PATH)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    await bot.process_commands(message)

    if not message.guild or message.guild.id != EMS_GUILD_ID:
        return
    if not DEMISIE_CHANNEL_ID or message.channel.id != DEMISIE_CHANNEL_ID:
        return
    if not isinstance(message.author, discord.Member):
        return

    looks_like_demisie = bool(
        re.match(r"^\s*(demisia|demisie)\b", message.content, flags=re.IGNORECASE)
        or re.search(r"(?im)^\s*nume\s*:", message.content)
    )
    if not looks_like_demisie:
        return

    parsed = parse_demisie_template(message.content)
    if not parsed:
        await message.reply(demisie_format_message(), mention_author=True)
        return

    request_name, request_hours, request_reason = parsed
    problems = []
    if len(request_name) < 2:
        problems.append("Câmpul `Nume` trebuie completat corect.")
    elif len(request_name) > 100:
        problems.append("Câmpul `Nume` este prea lung. Maxim 100 de caractere.")
    if not request_hours:
        problems.append("Câmpul `Ore` trebuie completat.")
    elif len(request_hours) > 30:
        problems.append("Câmpul `Ore` este prea lung. Maxim 30 de caractere.")
    if len(request_reason) < 3:
        problems.append("Câmpul `Motiv` trebuie completat corect.")
    elif len(request_reason) > 1000:
        problems.append("Câmpul `Motiv` este prea lung. Maxim 1000 de caractere.")
    if problems:
        await message.reply("⚠️ " + "\n⚠️ ".join(problems), mention_author=True)
        return

    existing = await db.get_pending_for_user(message.author.id)
    if existing:
        await message.reply(
            "⚠️ Ai deja o cerere de demisie în așteptare: "
            f"https://discord.com/channels/{EMS_GUILD_ID}/{existing['channel_id']}/{existing['message_id']}",
            mention_author=True,
        )
        return

    join_date_iso = await resolve_join_date(message.author.id, message.author)
    if not join_date_iso:
        await message.reply(
            "❌ Nu pot determina data intrării tale în departament. Anunță conducerea.",
            mention_author=True,
        )
        return

    contract = await db.get_active_contract(message.author.id)
    request_id = new_document_id("DMS")
    seconds = duration_seconds_between(join_date_iso)

    sent = await message.channel.send(
        embed=build_pending_embed(
            message.author, request_id, join_date_iso, request_reason, request_name, request_hours
        ),
        view=DemisieDecisionView(),
    )

    await db.create_resignation(
        request_id=request_id,
        user_id=message.author.id,
        channel_id=message.channel.id,
        message_id=sent.id,
        join_date_iso=join_date_iso,
        days=seconds // 86400 if seconds is not None else None,
        request_reason=request_reason,
        request_name=request_name,
        request_hours=request_hours,
        contract_id=contract["id"] if contract else None,
    )

    if DELETE_TRIGGER_MESSAGE:
        try:
            await message.delete()
        except discord.HTTPException:
            pass


# =========================
# SLASH COMMANDS
# =========================

@bot.tree.command(
    name="contract",
    description="Emite un contract de angajare în Legacy EMS pentru un membru.",
    guild=main_guild_obj,
)
@app_commands.describe(
    user="Membrul care este angajat.",
    nume_ic="Numele și prenumele IC al membrului angajat.",
    cnp="CNP-ul IC al membrului angajat.",
    semnatura="Semnătura ta: numele și prenumele tău IC (angajatorul).",
    grad_angajator="Gradul tău, al celui care face contractul.",
    grad_angajat="Gradul pe care îl primește membrul angajat.",
)
async def contract_command(
    interaction: discord.Interaction,
    user: discord.Member,
    nume_ic: str,
    cnp: str,
    semnatura: str,
    grad_angajator: str,
    grad_angajat: str,
):
    if interaction.guild_id != MAIN_GUILD_ID:
        await interaction.response.send_message(
            "❌ Această comandă funcționează doar pe serverul principal Legacy of CLT.", ephemeral=True
        )
        return
    if not channel_matches(interaction.channel, CONTRACT_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ Folosește această comandă doar în <#{CONTRACT_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not is_recruiter(interaction.user):
        await interaction.response.send_message(
            "❌ Nu ai permisiune să emiți contracte de angajare.", ephemeral=True
        )
        return
    if user.bot:
        await interaction.response.send_message("❌ Nu poți angaja un bot.", ephemeral=True)
        return
    if user.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ Nu poți emite un contract pentru tine însuți.", ephemeral=True
        )
        return

    try:
        nume_ic_clean = validate_name(nume_ic)
        semnatura_clean = validate_name(semnatura)
        cnp_clean = validate_cnp(cnp)
        grad_angajator_clean = validate_grade(grad_angajator, "Gradul angajatorului")
        grad_angajat_clean = validate_grade(grad_angajat, "Gradul angajatului")
    except ValueError as exc:
        await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        return

    active = await db.get_active_contract(user.id)
    if active:
        await interaction.response.send_message(
            f"⚠️ {user.mention} are deja un contract activ (`{active['id']}`) din "
            f"**{format_dt(active.get('signed_at'))}**.\n"
            "Contractul trebuie încetat prin demisie înainte de a emite unul nou.",
            ephemeral=True,
        )
        return

    # Un contract în așteptare mai vechi este anulat de create_contract;
    # îi dezactivăm și butoanele ca să nu rămână două mesaje active.
    superseded = await db.get_pending_contract(user.id)

    contract_id = new_document_id("CTR")
    row = await db.create_contract(
        contract_id=contract_id,
        user_id=user.id,
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        nume_ic=nume_ic_clean,
        cnp=cnp_clean,
        functie=grad_angajat_clean,
        recruiter_id=interaction.user.id,
        recruiter_signature=semnatura_clean,
        recruiter_grade=grad_angajator_clean,
    )

    # Fără defer, ca mențiunea membrului să genereze o notificare reală.
    await interaction.response.send_message(
        content=(
            f"{user.mention} — ai un contract de angajare în **{DEPARTMENT_NAME}**.\n"
            "Apasă un buton de mai jos: **Acceptă / Semnează** sau **Refuză contractul**."
        ),
        embed=build_contract_pending_embed(row, user, interaction.user),
        view=ContractDecisionView(),
        allowed_mentions=discord.AllowedMentions(users=[user]),
    )
    message = await interaction.original_response()
    await db.set_contract_message(contract_id, message.id)

    if superseded:
        await update_contract_message(superseded)


@contract_command.error
async def contract_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.exception("Eroare în /contract: %s", error)
    payload = "❌ A apărut o eroare la emiterea contractului. Încearcă din nou."
    if interaction.response.is_done():
        await interaction.followup.send(payload, ephemeral=True)
    else:
        await interaction.response.send_message(payload, ephemeral=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("Lipsește DISCORD_TOKEN. Adaugă tokenul în Railway Variables sau în .env local.")
    validate_config_startup()
    bot.run(DISCORD_TOKEN)
