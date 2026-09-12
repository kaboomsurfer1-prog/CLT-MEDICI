"""Funcții utile: date, ore, durate, formatări."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timezone
from typing import Optional

from config import LOCAL_TZ

RO_MONTHS = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unix_from_iso(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def parse_join_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Format dată invalid. Folosește YYYY-MM-DD sau DD/MM/YYYY.")


def parse_join_time(value: str) -> time:
    value = value.strip().replace(".", ":")
    for fmt in ("%H:%M", "%H"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    raise ValueError("Format oră invalid. Folosește HH:MM, exemplu 20:30.")


def parse_join_datetime(data: str, ora: str) -> datetime:
    join_dt = datetime.combine(parse_join_date(data), parse_join_time(ora), tzinfo=LOCAL_TZ)
    if join_dt > now_local():
        raise ValueError("Data și ora intrării nu pot fi în viitor.")
    return join_dt


def parse_stored_datetime(value: Optional[str]) -> Optional[datetime]:
    """Acceptă ISO complet, dată simplă sau timestamp UTC salvat anterior."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(value), time(0, 0), tzinfo=LOCAL_TZ)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


# Compatibilitate cu numele vechi folosit în bot.
parse_stored_join_datetime = parse_stored_datetime


def duration_seconds_between(start_iso: Optional[str], end_iso: Optional[str] = None) -> Optional[int]:
    start = parse_stored_datetime(start_iso)
    if not start:
        return None
    end = parse_stored_datetime(end_iso) if end_iso else now_local()
    if not end:
        end = now_local()
    return max(0, int((end - start).total_seconds()))


def calculate_duration_seconds(join_date_iso: Optional[str]) -> Optional[int]:
    return duration_seconds_between(join_date_iso, None)


def calculate_days(join_date_iso: Optional[str], end_iso: Optional[str] = None) -> Optional[int]:
    seconds = duration_seconds_between(join_date_iso, end_iso)
    if seconds is None:
        return None
    return seconds // 86400


def format_days(days: Optional[int]) -> str:
    if days is None:
        return "Necunoscut"
    if days == 1:
        return "1 zi"
    return f"{days} zile"


def format_duration_seconds(seconds: Optional[int]) -> str:
    if seconds is None:
        return "Necunoscut"

    total_minutes = seconds // 60
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60

    parts: list[str] = []
    if days == 1:
        parts.append("1 zi")
    elif days > 1:
        parts.append(f"{days} zile")
    if hours == 1:
        parts.append("1 oră")
    elif hours > 1:
        parts.append(f"{hours} ore")
    if minutes == 1:
        parts.append("1 minut")
    elif minutes > 1:
        parts.append(f"{minutes} minute")

    if not parts:
        return "Sub 1 minut"
    return ", ".join(parts)


def format_duration_from_join(join_date_iso: Optional[str], end_iso: Optional[str] = None) -> str:
    return format_duration_seconds(duration_seconds_between(join_date_iso, end_iso))


def format_dt(value: Optional[str], fmt: str = "%d/%m/%Y %H:%M") -> str:
    dt = parse_stored_datetime(value)
    if not dt:
        return "Nesetată" if not value else "Invalidă"
    return dt.strftime(fmt)


# Compatibilitate cu numele vechi folosit în bot.
format_join_date = format_dt


def format_date_ro(value: Optional[str]) -> str:
    """Exemplu: 12 septembrie 2026, ora 20:30"""
    dt = parse_stored_datetime(value)
    if not dt:
        return "—"
    return f"{dt.day} {RO_MONTHS[dt.month - 1]} {dt.year}, ora {dt:%H:%M}"


def is_valid_join_date(join_date_iso: Optional[str]) -> bool:
    return parse_stored_datetime(join_date_iso) is not None


def status_ro(status: str) -> str:
    return {
        "PENDING": "În așteptare",
        "ACCEPTED": "Acceptată",
        "REFUSED": "Refuzată",
        "PENDING_SIGN": "Așteaptă semnătura",
        "SIGNED": "Semnat / Activ",
        "TERMINATED": "Încetat",
        "CANCELLED": "Anulat",
    }.get(status, status)


def user_mention(user_id: str | int) -> str:
    return f"<@{user_id}>"


def clean_line(value: str) -> str:
    """Normalizează un câmp scris de utilizator pe o singură linie."""
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


NAME_RE = re.compile(r"^[A-Za-zĂÂÎȘȚăâîșțŞşŢţ' .\-]{3,60}$")
CNP_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z \-]{2,23}$")
GRADE_RE = re.compile(r"^[A-Za-z0-9ĂÂÎȘȚăâîșțŞşŢţ .,'()\-/&]{2,60}$")


def validate_name(value: str) -> str:
    value = clean_line(value)
    if not NAME_RE.match(value):
        raise ValueError(
            "Numele IC trebuie să aibă între 3 și 60 de caractere și să conțină doar litere, spații, `-` sau `'`."
        )
    return value


def validate_cnp(value: str) -> str:
    value = clean_line(value).upper()
    if not CNP_RE.match(value):
        raise ValueError("CNP-ul trebuie să aibă între 3 și 24 de caractere (cifre/litere).")
    return value


def validate_grade(value: str, field: str = "Gradul") -> str:
    value = clean_line(value)
    if not GRADE_RE.match(value):
        raise ValueError(
            f"{field} trebuie să aibă între 2 și 60 de caractere "
            "(litere, cifre, spații și `- . , ' ( ) /`)."
        )
    return value


def top_role_name(member) -> str:
    """Gradul afișat pe contract = cel mai înalt rol (fără @everyone)."""
    roles = [role for role in getattr(member, "roles", []) if not role.is_default()]
    if not roles:
        return "Membru"
    return max(roles, key=lambda r: r.position).name
