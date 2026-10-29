"""Settings, read from the .env file in the project folder.

Copy .env.example to .env and fill it in. Nothing secret belongs in this file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = _int("GUILD_ID", 0)  # your server's ID; makes slash commands appear instantly
CREATE_TEAM_CHANNELS = _bool("CREATE_TEAM_CHANNELS", True)

# Channel names the bot looks for (and /admin setup creates)
CHANNELS = {
    "announcements": os.getenv("ANNOUNCEMENTS_CHANNEL", "announcements"),
    "exchange": os.getenv("EXCHANGE_CHANNEL", "the-exchange"),
    "policies": os.getenv("POLICY_CHANNEL", "policy-register"),
    "diaries": os.getenv("DIARY_CHANNEL", "secret-diaries"),
    "fair": os.getenv("FAIR_CHANNEL", "college-fair"),
}
TEAM_CATEGORY = os.getenv("TEAM_CATEGORY", "Universities")

# Daily market close
UPDATE_HOUR = _int("UPDATE_HOUR", 18)
UPDATE_MINUTE = _int("UPDATE_MINUTE", 0)
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")

# AI consequences (optional). Without an API key the bot uses the random tables.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5")

# Storage
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "game.db")))
