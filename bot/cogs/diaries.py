"""Reads Secret Diary posts. Each entry starts with #charactername #role #universityname."""

from __future__ import annotations

import re

import discord
from discord.ext import commands

from .. import config

TAG = re.compile(r"#([\w\-]+)")


def parse_entry(content: str, find_school):
    """Returns (school row or None, character, role, body).

    The hashtags at the start of the post are read in order: the first is the character, the
    second is the role, and any tag that names a university (by name or ticker) is the university.
    """
    lines = content.strip().split("\n")
    head_tags, body_start = [], 0
    for i, line in enumerate(lines):
        tags = TAG.findall(line)
        leftover = TAG.sub("", line).strip(" ,·|")
        if tags and not leftover:
            head_tags += tags
            body_start = i + 1
        else:
            break
    if not head_tags:   # tags may share the first line with text
        head_tags = TAG.findall(lines[0])[:3]
        lines[0] = TAG.sub("", lines[0]).strip()
        body_start = 0
    school, others = None, []
    for tag in head_tags:
        match = find_school(tag)
        if match and school is None:
            school = match
        else:
            others.append(tag)
    character = others[0] if others else ""
    role = others[1] if len(others) > 1 else ""
    body = "\n".join(lines[body_start:]).strip()
    return school, character, role, body


class Diaries(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        if message.channel.name != config.CHANNELS["diaries"]:
            return
        db = self.bot.db
        school, character, role, body = parse_entry(message.content, db.find_school)
        school = school or db.school_of(message.author.id)
        if school is None or not character or not body:
            await message.reply("📓 I couldn't file this diary entry. Start it with "
                                "`#charactername #role #universityname`, then write the entry below.",
                                mention_author=False)
            return
        db.add_diary(school["id"], message.author.id, character, role, body, message.id)
        try:
            await message.add_reaction("📓")
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Diaries(bot))
