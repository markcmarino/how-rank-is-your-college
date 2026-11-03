"""Player commands. Playing the game needs none of these (it's all hashtag posts); they're for looking things up."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import reports
from .common import parse_policy_ref, reply, school_autocomplete


class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rankings", description="The latest prices and Big Digit Conference rankings.")
    async def rankings(self, interaction: discord.Interaction):
        db = self.bot.db
        if db.day == 0:
            return await reply(interaction, "The Exchange hasn't closed yet. Check back after the first closing bell.")
        rows = self.bot.market_rows(db.day)
        await reply(interaction, reports.ticker(rows) + "\n" + reports.league_table(rows, db.day))

    @app_commands.command(name="report", description="A university's latest daily report.")
    @app_commands.autocomplete(university=school_autocomplete)
    async def report(self, interaction: discord.Interaction, university: str):
        db = self.bot.db
        school = db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        events = [{"text": e["text"]} for e in db.events(db.day, school["id"])]
        await reply(interaction, reports.school_report(school, db.day, events, db.all_stats()[school["id"]]))

    @app_commands.command(name="policies", description="A university's Policy Register.")
    @app_commands.autocomplete(university=school_autocomplete)
    async def policies(self, interaction: discord.Interaction, university: str):
        school = self.bot.db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        rows = self.bot.db.policies(school["id"])
        if not rows:
            return await reply(interaction, f"{school['name']} has no policies yet.")
        lines = [f"**{school['name']} · Policy Register**"]
        lines += [f"`{school['code']}-{p['number']}` {p['kind']}: {p['title']} · _{p['status']}_" for p in rows]
        await reply(interaction, "\n".join(lines))

    @app_commands.command(name="policy", description="Read one policy and its consequences, e.g. TTU-3.")
    async def policy(self, interaction: discord.Interaction, label: str):
        school, row = parse_policy_ref(self.bot.db, label)
        if row is None:
            return await reply(interaction, "I couldn't find that policy. Labels look like TTU-3.")
        text = reports.policy_card(row, school)
        log = self.bot.db.policy_log(row["id"])
        if log:
            text += "\n**Consequences:**\n" + "\n".join(f"• Day {e['day']}: {e['entry']}" for e in log)
        await reply(interaction, text)

    @app_commands.command(name="round", description="The current round and what to write.")
    async def round_info(self, interaction: discord.Interaction):
        rnd = self.bot.game.current_round()
        if rnd is None:
            return await reply(interaction, "The game hasn't started a round yet.")
        await reply(interaction, f"**{rnd['name']}**\n**Administrators:** {rnd['institutional']}\n"
                                 f"**Characters:** {rnd['character']}")

    @app_commands.command(name="vote", description="Vote for the Big Digit Conference winner (not your own!).")
    @app_commands.autocomplete(university=school_autocomplete)
    async def vote(self, interaction: discord.Interaction, university: str):
        db = self.bot.db
        if db.get("vote_open") != "1":
            return await reply(interaction, "Voting isn't open right now.")
        school = db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        if not self.bot.game.can_vote_for(interaction.user.id, school["id"]):
            return await reply(interaction, "Nice try. You can't vote for a university you've posted for.")
        db.cast_vote(interaction.user.id, interaction.user.display_name, school["id"])
        await reply(interaction, f"Your vote for **{school['name']}** is in. You can change it until voting closes.")


async def setup(bot):
    await bot.add_cog(Players(bot))
