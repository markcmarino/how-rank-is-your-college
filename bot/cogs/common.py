"""Helpers shared by the command modules."""

from __future__ import annotations

import re

import discord
from discord import app_commands

from ..reports import split


async def school_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower().lstrip("#")
    rows = interaction.client.db.schools()
    return [app_commands.Choice(name=f"{r['name']} (#{r['hashtag']}, {r['code']})"[:100], value=r["hashtag"])
            for r in rows if current in r["name"].lower() or current in r["hashtag"].lower()
            or current in r["code"].lower()][:25]


def parse_policy_ref(db, ref: str):
    """'TTU-3' or 'TTU 3' -> (school row, policy row); either may be None."""
    match = re.match(r"^\s*#?([A-Za-z0-9]+)[\s\-#]*(\d+)\s*$", ref or "")
    if not match:
        return None, None
    school = db.find_school(match.group(1))
    if school is None:
        return None, None
    return school, db.policy_by_number(school["id"], int(match.group(2)))


async def reply(interaction: discord.Interaction, text: str, ephemeral: bool = True) -> None:
    """Sends a reply, or a follow-up if the interaction was already answered. Splits long text."""
    chunks = split(text) or ["(nothing to show)"]
    for i, chunk in enumerate(chunks):
        if i == 0 and not interaction.response.is_done():
            await interaction.response.send_message(chunk, ephemeral=ephemeral)
        else:
            await interaction.followup.send(chunk, ephemeral=ephemeral)
