"""Configurare centralizată pentru botul Legacy EMS.

Toate valorile pot fi suprascrise din Railway Variables / .env.
Valorile implicite sunt cele ale serverelor Legacy of CLT.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    raw = raw.strip()
    if not raw.lstrip("-").isdigit():
        return default
    return int(raw)


def env_ids(name: str, default: str = "") -> set[int]:
    raw = os.getenv(name) or default
    ids: set[int] = set()
    for part in re.split(r"[,;\s]+", raw.strip()):
        if part and part.isdigit():
            ids.add(int(part))
    return ids


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "da", "on"}


BOT_VERSION = "2.3.0-legacy-ems-concediere"

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# --- Servere ---
# Serverul principal FiveM Legacy of CLT
MAIN_GUILD_ID = env_int("MAIN_GUILD_ID", 1505903653079351357)
# Serverul Discord al departamentului medical (EMS)
EMS_GUILD_ID = env_int("EMS_GUILD_ID", 1518542545569976492)

# --- Canale ---
# Canalul din serverul principal unde se folosește /contract
CONTRACT_CHANNEL_ID = env_int("CONTRACT_CHANNEL_ID", 1548327664694333520)
# Canalul din serverul EMS unde se postează contractele generate
CONTRACT_LOG_CHANNEL_ID = env_int("CONTRACT_LOG_CHANNEL_ID", 1548329089956581487)
# Canalul din serverul EMS unde membrii depun demisia
DEMISIE_CHANNEL_ID = env_int("DEMISIE_CHANNEL_ID", 0)
# Canale de log
EMS_LOG_CHANNEL_ID = env_int("EMS_LOG_CHANNEL_ID", 0)
MAIN_LOG_CHANNEL_ID = env_int("MAIN_LOG_CHANNEL_ID", 0)
# Canalul folosit pentru generarea invitației în serverul EMS (opțional)
EMS_INVITE_CHANNEL_ID = env_int("EMS_INVITE_CHANNEL_ID", 0)
# Canalele (din oricare server) unde se pot folosi /radiografie și /analize
MEDICAL_CHANNEL_IDS = env_ids("MEDICAL_CHANNEL_IDS", "1553137969899114646,1539978574864326737")

# --- Roluri ---
# Rolurile care pot emite contracte cu /contract
RECRUITER_ROLE_IDS = env_ids("RECRUITER_ROLE_IDS", "1517181051288420372")
# Rolurile care pot accepta / refuza demisii
STAFF_ROLE_IDS = env_ids("STAFF_ROLE_IDS", "")
# Rolurile care pot emite /radiografie și /analize. Gol = oricine scrie în canalele medicale.
MEDICAL_ROLE_IDS = env_ids("MEDICAL_ROLE_IDS", "")

# --- Diverse ---
BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
DB_PATH = os.getenv("DB_PATH", "/data/legacy_ems.db")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Bucharest")
DELETE_TRIGGER_MESSAGE = env_bool("DELETE_TRIGGER_MESSAGE", False)

# Durata invitației către serverul EMS (secunde). 0 = nu expiră niciodată.
INVITE_MAX_AGE = env_int("INVITE_MAX_AGE", 7 * 24 * 3600)
INVITE_MAX_USES = env_int("INVITE_MAX_USES", 1)

# Identitate afișată pe documente
CITY_NAME = os.getenv("CITY_NAME", "Legacy of CLT")
DEPARTMENT_NAME = os.getenv("DEPARTMENT_NAME", "Legacy EMS")
DEPARTMENT_SUBTITLE = os.getenv("DEPARTMENT_SUBTITLE", "Departamentul Medical")
DEFAULT_FUNCTION = os.getenv("DEFAULT_FUNCTION", "Paramedic Stagiar")

# Logo-uri: dacă lipsesc fișierele locale se folosesc iconițele serverelor
MAIN_LOGO_URL = os.getenv("MAIN_LOGO_URL", "").strip()
EMS_LOGO_URL = os.getenv("EMS_LOGO_URL", "").strip()

try:
    LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
except (ZoneInfoNotFoundError, ValueError):
    LOCAL_TZ = timezone.utc

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("legacy-ems-bot")


# Fără acestea botul nu poate porni.
REQUIRED_IDS = {
    "MAIN_GUILD_ID": MAIN_GUILD_ID,
    "EMS_GUILD_ID": EMS_GUILD_ID,
    "CONTRACT_CHANNEL_ID": CONTRACT_CHANNEL_ID,
    "CONTRACT_LOG_CHANNEL_ID": CONTRACT_LOG_CHANNEL_ID,
}

# Opționale: botul pornește, dar funcția respectivă este dezactivată.
OPTIONAL_IDS = {
    "DEMISIE_CHANNEL_ID": DEMISIE_CHANNEL_ID,
    "EMS_LOG_CHANNEL_ID": EMS_LOG_CHANNEL_ID,
    "MAIN_LOG_CHANNEL_ID": MAIN_LOG_CHANNEL_ID,
    "EMS_INVITE_CHANNEL_ID": EMS_INVITE_CHANNEL_ID,
    "MEDICAL_CHANNEL_IDS": MEDICAL_CHANNEL_IDS,
}


def validate_config_startup() -> None:
    missing = [name for name, value in REQUIRED_IDS.items() if not value]
    if missing:
        raise RuntimeError(
            "Lipsesc ID-uri obligatorii în Railway Variables / .env: " + ", ".join(missing)
        )
    if not RECRUITER_ROLE_IDS:
        raise RuntimeError(
            "Lipsește RECRUITER_ROLE_IDS. Adaugă ID-urile rolurilor care pot folosi /contract."
        )

    for name, value in OPTIONAL_IDS.items():
        if not value:
            log.warning("%s nu este setat. Funcția care depinde de el este dezactivată.", name)
    if not STAFF_ROLE_IDS:
        log.warning(
            "STAFF_ROLE_IDS nu este setat. Demisiile pot fi gestionate doar de membrii "
            "cu permisiunea `Gestionare server`."
        )
