"""Reads players' posts in the game channels and files them by hashtag.

- College Fair Pitches: #universityname, then the pitch. The first post with a new hashtag registers it.
- Meet the Students: #charactername #role #universityname, then the introduction.
- Policies: #universityname, then the policy. Optional #amendment, #extrememeasure or #speech;
  otherwise the current round decides what kind of policy it is.
- Secret Diaries: #charactername #role #universityname, then the entry.

Filed posts get a reaction. Problems (a misspelled hashtag, say) get a short reply.
Edits to a post aren't re-read; players can delete and repost.
Posts made while the bot was away are filed when it returns, using the time they were posted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from .. import config

log = logging.getLogger("rankbot")

REACTIONS = {"fair": "🏛️", "students": "👋", "policies": "📜", "diaries": "📓"}


class Posts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.handlers = {
            config.CHANNELS["fair"]: ("fair", bot.game.register_or_pitch),
            config.CHANNELS["students"]: ("students", bot.game.file_character),
            config.CHANNELS["policies"]: ("policies", bot.game.file_policy),
            config.CHANNELS["diaries"]: ("diaries", bot.game.file_diary),
        }
        self.handled: set[int] = set()
        self.catch_up_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self.file(message)

    async def catch_up(self) -> None:
        """Files whatever was posted while the bot was away. The first time it sees a channel it only notes
        the current position, so a new game never files old test posts."""
        async with self.catch_up_lock:
            guild = self.bot.home_guild()
            if guild is None:
                return
            try:
                threads = await guild.active_threads()
                for name in self.handlers:
                    channel = discord.utils.get(guild.text_channels, name=name)
                    if channel is None:
                        continue
                    seen = self.bot.db.get(f"seen_{channel.id}")
                    if seen is None:
                        self.bot.db.set(f"seen_{channel.id}", discord.utils.time_snowflake(datetime.now(timezone.utc)))
                        continue
                    await self.replay(channel, int(seen))
                    for thread in threads:
                        if thread.parent_id == channel.id:
                            await self.replay(thread, int(self.bot.db.get(f"seen_{thread.id}") or seen))
            except discord.HTTPException:
                log.exception("Couldn't finish catching up on missed posts")

    async def replay(self, channel, after: int) -> None:
        async for message in channel.history(after=discord.Object(id=after), oldest_first=True, limit=None):
            await self.file(message)

    async def file(self, message: discord.Message) -> None:
        if message.id in self.handled or message.author.bot or not message.guild:
            return
        channel = message.channel
        name = channel.parent.name if isinstance(channel, discord.Thread) and channel.parent else channel.name
        handler = self.handlers.get(name)
        if handler is None or not message.content.strip():
            return
        self.handled.add(message.id)
        seen_key = f"seen_{channel.id}"
        if message.id > int(self.bot.db.get(seen_key) or 0):
            self.bot.db.set(seen_key, message.id)
        if self.bot.db.already_filed(message.id):
            return
        key, file_post = handler
        filed = file_post(message.content, message.author.id, message.author.display_name, message.id,
                          message.created_at)
        if filed.ok:
            try:
                await message.add_reaction(REACTIONS[key])
            except discord.HTTPException:
                pass
            if filed.new_school:
                await message.reply(filed.message, mention_author=False)
                await self.bot.post("announcements", f"🔔 New listing on the UnderAcademy Exchange: "
                                                     f"**{filed.school['name']}** (#{filed.school['hashtag']}) "
                                                     f"trades as **{filed.school['code']}**.")
        elif filed.message:
            await message.reply(filed.message, mention_author=False)


async def setup(bot):
    await bot.add_cog(Posts(bot))
