"""Helpers shared by the command modules."""

from __future__ import annotations

import json
import re

import discord
from discord import app_commands

from ..config import DATA_DIR

DOMAINS = [d for d in json.loads((DATA_DIR / "domains.json").read_text(encoding="utf-8"))["domains"]]
DOMAIN_CHOICES = [app_commands.Choice(name=d, value=d) for d in DOMAINS]


async def school_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    rows = interaction.client.db.schools()
    return [app_commands.Choice(name=f"{r['name']} ({r['code']})", value=r["code"])
            for r in rows if current in r["name"].lower() or current in r["code"].lower()][:25]


def parse_policy_ref(db, ref: str):
    """'GRPU-3' or 'GRPU 3' -> (school row, policy row); either may be None."""
    match = re.match(r"^\s*#?([A-Za-z0-9]+)[\s\-#]*(\d+)\s*$", ref or "")
    if not match:
        return None, None
    school = db.find_school(match.group(1))
    if school is None:
        return None, None
    return school, db.policy_by_number(school["id"], int(match.group(2)))


async def reply(interaction: discord.Interaction, text: str, ephemeral: bool = True) -> None:
    """Sends a reply, or a follow-up if the interaction was already answered. Splits long text."""
    from ..reports import split
    chunks = split(text) or ["(nothing to show)"]
    for i, chunk in enumerate(chunks):
        if i == 0 and not interaction.response.is_done():
            await interaction.response.send_message(chunk, ephemeral=ephemeral)
        else:
            await interaction.followup.send(chunk, ephemeral=ephemeral)
