"""Reads players' posts in the game channels and files them by hashtag.

- College Fair Pitches: #universityname, then the pitch. The first post with a new hashtag registers it.
- Meet the Students: #charactername #role #universityname, then the introduction.
- Policies: #universityname, then the policy. Optional #amendment, #extrememeasure or #speech;
  otherwise the current round decides what kind of policy it is.
- Secret Diaries: #charactername #role #universityname, then the entry.

Filed posts get a reaction. Problems (a misspelled hashtag, say) get a short reply.
Edits to a post aren't re-read; players can delete and repost.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from .. import config

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        channel = message.channel
        name = channel.parent.name if isinstance(channel, discord.Thread) and channel.parent else channel.name
        handler = self.handlers.get(name)
        if handler is None or not message.content.strip():
            return
        if self.bot.db.already_filed(message.id):
            return
        key, file_post = handler
        filed = file_post(message.content, message.author.id, message.author.display_name, message.id)
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
