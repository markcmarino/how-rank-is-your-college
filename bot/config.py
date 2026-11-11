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

# Channel names the bot reads and posts in (/admin setup creates any that are missing)
CHANNELS = {
    "announcements": os.getenv("ANNOUNCEMENTS_CHANNEL", "start-here-rank"),
    "fair": os.getenv("FAIR_CHANNEL", "college-pitches-rank"),
    "students": os.getenv("STUDENTS_CHANNEL", "character-intros-rank"),
    "policies": os.getenv("POLICY_CHANNEL", "policies-rank"),
    "diaries": os.getenv("DIARY_CHANNEL", "secret-diary-rank"),
    "exchange": os.getenv("EXCHANGE_CHANNEL", "rankings-rank"),
}

# Daily closing bell (and the time rounds open on their dates). Midnight Pacific by default.
UPDATE_HOUR = _int("UPDATE_HOUR", 0)
UPDATE_MINUTE = _int("UPDATE_MINUTE", 0)
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")

# Lookup tables in Google Sheets (the long ID in the Sheet's web address). Blank = use data/tables/.
TABLES_SHEET_ID = os.getenv("TABLES_SHEET_ID", "")

# Public rankings page (US Snooze & Whirled Retort) on GitHub Pages. Blank token = local copy in site/ only.
SITE_GITHUB_TOKEN = os.getenv("SITE_GITHUB_TOKEN", "")
SITE_REPO = os.getenv("SITE_REPO", "")            # e.g. markcmarino/how-rank-is-your-college
SITE_BRANCH = os.getenv("SITE_BRANCH", "gh-pages")
# Recruiting box on the Retort's front page. It's left out unless DISCORD_INVITE_URL is set.
DISCORD_INVITE_URL = os.getenv("DISCORD_INVITE_URL", "").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "").strip()

# AI consequences (optional). Without an API key the bot uses the random tables.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5")

# Storage
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "game.db")))
