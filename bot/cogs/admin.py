"""Game-master commands (/admin ...). Only people with Manage Server permission can see them."""

from __future__ import annotations

import io

import discord
from discord import app_commands
from discord.ext import commands

from .. import ai, config
from ..engine import ALL_STATS, STAT_LABELS, load_data
from .common import parse_policy_ref, reply, school_autocomplete

ROUND_CHOICES = [app_commands.Choice(name=r["name"], value=r["key"]) for r in load_data()["rounds"]]
STAT_CHOICES = [app_commands.Choice(name=STAT_LABELS[s], value=s) for s in ALL_STATS]


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Admin(commands.GroupCog, group_name="admin", group_description="Game-master tools"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="setup", description="Create the game's public channels if they're missing.")
    async def setup_channels(self, interaction: discord.Interaction):
        guild = interaction.guild
        made = []
        for key, name in config.CHANNELS.items():
            if discord.utils.get(guild.text_channels, name=name) is None:
                await guild.create_text_channel(name)
                made.append(f"#{name}")
        await reply(interaction, "Created " + ", ".join(made) if made else "All channels already exist.")

    @app_commands.command(name="round", description="Start a round and post its challenge.")
    @app_commands.choices(which=ROUND_CHOICES)
    async def start_round(self, interaction: discord.Interaction, which: app_commands.Choice[str]):
        self.bot.db.set("round", which.value)
        rnd = self.bot.game.current_round()
        await self.bot.post("announcements",
                            f"📯 **{rnd['name']} begins!**\n\n**The challenge:** {rnd['challenge']}\n\n"
                            f"**Administrators:** {rnd['institutional']}\n"
                            f"**Characters (Secret Diaries):** {rnd['character']}")
        await reply(interaction, f"{rnd['name']} is open.")

    @app_commands.command(name="convene", description="Run a market close now.")
    @app_commands.describe(preview="Show it to you first; post it with /admin publish")
    async def convene(self, interaction: discord.Interaction, preview: bool = False):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not self.bot.db.schools():
            return await interaction.followup.send("No universities yet.", ephemeral=True)
        if preview:
            async with self.bot.close_lock:
                report = await self.bot.game.close()
            sample = "\n\n".join(list(report.school_reports.values())[:3])
            return await reply(interaction, f"**Preview of Day {report.day}** (nothing posted yet)\n\n"
                                            f"{report.commentary}\n{report.ticker}\n{sample}\n\n"
                                            f"Run /admin publish to post it, or /admin convene again to reroll.")
        report = await self.bot.run_close()
        await interaction.followup.send(f"Day {report.day} is closed and posted.", ephemeral=True)

    @app_commands.command(name="publish", description="Post the close you previewed.")
    async def publish(self, interaction: discord.Interaction):
        report = self.bot.game.pending
        if report is None or report.day != self.bot.db.day + 1:
            return await reply(interaction, "Nothing to publish. Run /admin convene preview:True first.")
        await interaction.response.defer(ephemeral=True)
        async with self.bot.close_lock:
            self.bot.game.commit(report)
        await self.bot.publish(report)
        await interaction.followup.send(f"Day {report.day} posted.", ephemeral=True)

    @app_commands.command(name="decree", description="Announce a custom event, optionally moving a stat.")
    @app_commands.autocomplete(university=school_autocomplete)
    @app_commands.choices(stat=STAT_CHOICES)
    async def decree(self, interaction: discord.Interaction, text: str, university: str | None = None,
                     stat: app_commands.Choice[str] | None = None, amount: float = 0.0):
        school = self.bot.db.find_school(university) if university else None
        if university and school is None:
            return await reply(interaction, "I couldn't find that university.")
        self.bot.game.decree(text, school["id"] if school else None, stat.value if stat else None, amount)
        target = school["name"] if school else "all universities"
        await self.bot.post("announcements", f"⚖️ **Decree** ({target}): {text}")
        await reply(interaction, "Decreed.")

    @app_commands.command(name="strike", description="Strike down a policy, e.g. GRPU-3.")
    async def strike(self, interaction: discord.Interaction, policy: str, reason: str = "By order of the Board."):
        school, row = parse_policy_ref(self.bot.db, policy)
        if row is None:
            return await reply(interaction, "I couldn't find that policy.")
        self.bot.db.set_policy_status(row["id"], "Struck Down")
        self.bot.db.log_policy(row["id"], self.bot.db.day + 1, f"Struck down. {reason}")
        await self.bot.post("policies", f"⚖️ {school['code']}-{row['number']} ({row['title']}) has been "
                                        f"struck down. {reason}")
        await reply(interaction, "Struck down.")

    @app_commands.command(name="mode", description="Choose who writes consequences: AI or random tables.")
    @app_commands.choices(mode=[app_commands.Choice(name="AI (needs ANTHROPIC_API_KEY)", value="ai"),
                                app_commands.Choice(name="Random tables only", value="tables")])
    async def mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        self.bot.db.set("mode", mode.value)
        note = ""
        if mode.value == "ai" and not ai.enabled("ai"):
            note = " No API key is set, so the bot will keep using the tables until you add one."
        await reply(interaction, f"Mode set to {mode.name}.{note}")

    @app_commands.command(name="pause", description="Pause or resume the daily closing bell.")
    async def pause(self, interaction: discord.Interaction, paused: bool):
        self.bot.db.set("paused", "1" if paused else "0")
        await reply(interaction, "Daily closes paused." if paused else "Daily closes resumed.")

    @app_commands.command(name="peek", description="See a university's hidden stats.")
    @app_commands.autocomplete(university=school_autocomplete)
    async def peek(self, interaction: discord.Interaction, university: str):
        school = self.bot.db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        stats = self.bot.db.all_stats()[school["id"]]
        await reply(interaction, f"**{school['name']}**\n" +
                    "\n".join(f"{STAT_LABELS[k]}: {v:.1f}" for k, v in stats.items()))

    @app_commands.command(name="export", description="Download the Collected Statutes and price history.")
    async def export(self, interaction: discord.Interaction):
        game = self.bot.game
        files = [discord.File(io.BytesIO(game.export_statutes().encode()), filename="collected-statutes.md"),
                 discord.File(io.BytesIO(game.history_json().encode()), filename="price-history.json")]
        await interaction.response.send_message("Here's the archive.", files=files, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
