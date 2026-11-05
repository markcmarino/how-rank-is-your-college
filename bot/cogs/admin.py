"""Game-master commands (/admin ...). Only people with Manage Server permission can see them."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .. import ai, config, tables
from ..engine import ALL_STATS, STAT_LABELS
from ..parsing import SECTIONS
from .common import parse_policy_ref, reply, school_autocomplete

STAT_CHOICES = [app_commands.Choice(name=STAT_LABELS[s], value=s) for s in ALL_STATS]


async def round_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=r["name"], value=r["key"]) for r in interaction.client.game.rounds()
            if current.lower() in r["name"].lower()][:25]


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Admin(commands.GroupCog, group_name="admin", group_description="Game-master tools"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="setup", description="Create the game's channels if they're missing.")
    async def setup_channels(self, interaction: discord.Interaction):
        made = []
        for name in config.CHANNELS.values():
            if discord.utils.get(interaction.guild.text_channels, name=name) is None:
                await interaction.guild.create_text_channel(name)
                made.append(f"#{name}")
        await reply(interaction, "Created " + ", ".join(made) if made else "All channels already exist.")

    @app_commands.command(name="round", description="Open a round now (rounds also open on their own dates).")
    @app_commands.autocomplete(which=round_autocomplete)
    async def start_round(self, interaction: discord.Interaction, which: str):
        if not any(r["key"] == which for r in self.bot.game.rounds()):
            return await reply(interaction, "Pick a round from the list.")
        await self.bot.announce_round(self.bot.game.open_round(which))
        await reply(interaction, "Round opened.")

    @app_commands.command(name="convene", description="Run a closing bell now.")
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

    @app_commands.command(name="publish", description="Post the closing bell you previewed.")
    async def publish(self, interaction: discord.Interaction):
        report = self.bot.game.pending
        if report is None or report.day != self.bot.db.day + 1:
            return await reply(interaction, "Nothing to publish. Run /admin convene preview:True first.")
        await interaction.response.defer(ephemeral=True)
        async with self.bot.close_lock:
            self.bot.game.commit(report)
        await self.bot.publish(report)
        await interaction.followup.send(f"Day {report.day} posted.", ephemeral=True)

    @app_commands.command(name="tables", description="Reload the lookup tables from the Google Sheet now.")
    async def reload_tables(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        status = await self.bot.loop.run_in_executor(None, tables.refresh)
        lines = [f"• {tables.TABS[name][0]}: {where}" for name, where in status.items()]
        note = "" if config.TABLES_SHEET_ID else "\nNo TABLES_SHEET_ID is set, so the bot uses the copies in data/tables."
        await interaction.followup.send("**Lookup tables**\n" + "\n".join(lines) + note, ephemeral=True)

    @app_commands.command(name="decree", description="Announce a custom event, optionally moving a stat.")
    @app_commands.autocomplete(university=school_autocomplete)
    @app_commands.choices(stat=STAT_CHOICES)
    async def decree(self, interaction: discord.Interaction, text: str, university: str | None = None,
                     stat: app_commands.Choice[str] | None = None, amount: float = 0.0):
        school = self.bot.db.find_school(university) if university else None
        if university and school is None:
            return await reply(interaction, "I couldn't find that university.")
        self.bot.game.decree(text, school["id"] if school else None, stat.value if stat else None, amount)
        await self.bot.post("announcements", f"⚖️ **Decree** ({school['name'] if school else 'all universities'}): "
                                             f"{text}")
        await reply(interaction, "Decreed.")

    @app_commands.command(name="strike", description="Strike down a policy, e.g. TTU-3.")
    async def strike(self, interaction: discord.Interaction, policy: str, reason: str = "By order of the Board."):
        school, row = parse_policy_ref(self.bot.db, policy)
        if row is None:
            return await reply(interaction, "I couldn't find that policy.")
        self.bot.db.set_policy_status(row["id"], "Struck Down")
        self.bot.db.log_policy(row["id"], self.bot.db.day + 1, f"Struck down. {reason}")
        await self.bot.post("announcements", f"⚖️ {school['code']}-{row['number']} ({school['name']}) has been "
                                             f"struck down. {reason}")
        await reply(interaction, "Struck down.")

    @app_commands.command(name="school", description="Fix a university's name, ticker, mascot or class section.")
    @app_commands.autocomplete(university=school_autocomplete)
    @app_commands.choices(section=[app_commands.Choice(name=s, value=s) for s in SECTIONS]
                          + [app_commands.Choice(name="Guest (no section)", value="guest")])
    async def school(self, interaction: discord.Interaction, university: str, name: str | None = None,
                     ticker: str | None = None, mascot: str | None = None,
                     section: app_commands.Choice[str] | None = None):
        db = self.bot.db
        school = db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        updates = {k: v for k, v in (("name", name), ("code", ticker.upper() if ticker else None),
                                     ("mascot", mascot)) if v}
        if section:
            updates["section"] = None if section.value == "guest" else section.value
        if not updates:
            return await reply(interaction, "Nothing to change.")
        if "code" in updates and any(s["code"] == updates["code"] and s["id"] != school["id"] for s in db.schools()):
            return await reply(interaction, "That ticker is taken.")
        db.update_school(school["id"], **updates)
        await reply(interaction, "Updated.")

    @app_commands.command(name="mode", description="Who writes consequences: the lookup tables, or AI.")
    @app_commands.choices(mode=[app_commands.Choice(name="Lookup tables", value="tables"),
                                app_commands.Choice(name="AI (needs ANTHROPIC_API_KEY)", value="ai")])
    async def mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        self.bot.db.set("mode", mode.value)
        note = " No API key is set, so the bot will keep using the tables." if mode.value == "ai" and \
            not ai.enabled("ai") else ""
        await reply(interaction, f"Mode set to {mode.name}.{note}")

    @app_commands.command(name="pause", description="Pause or resume the nightly closing bell and round openings.")
    async def pause(self, interaction: discord.Interaction, paused: bool):
        self.bot.db.set("paused", "1" if paused else "0")
        await reply(interaction, "Paused." if paused else "Resumed.")

    @app_commands.command(name="peek", description="See a university's hidden stats.")
    @app_commands.autocomplete(university=school_autocomplete)
    async def peek(self, interaction: discord.Interaction, university: str):
        school = self.bot.db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        stats = self.bot.db.all_stats()[school["id"]]
        await reply(interaction, f"**{school['name']}**\n" + "\n".join(f"{STAT_LABELS[k]}: {v:.1f}"
                                                                       for k, v in stats.items()))

    # ---- the finale ----------------------------------------------------------
    vote = app_commands.Group(name="vote", description="The player vote for the Big Digit Conference winner")

    @vote.command(name="open", description="Open voting (players use /vote).")
    async def vote_open(self, interaction: discord.Interaction, reset: bool = False):
        if reset:
            self.bot.db.clear_votes()
        self.bot.db.set("vote_open", "1")
        await self.bot.post("announcements", "🗳️ **Voting is open for the Big Digit Conference championship!** "
                                             "Use `/vote` to pick your favorite university. You can't vote for "
                                             "one you've posted for.")
        await reply(interaction, "Voting is open.")

    @vote.command(name="close", description="Close voting and announce the winner.")
    async def vote_close(self, interaction: discord.Interaction):
        db = self.bot.db
        db.set("vote_open", "0")
        tally = [t for t in db.vote_tally() if t["votes"]]
        if not tally:
            return await reply(interaction, "Voting closed. Nobody voted.")
        lines = [f"`{t['votes']:>3}` {t['name']} ({t['code']})" for t in tally[:10]]
        top = [t for t in tally if t["votes"] == tally[0]["votes"]]
        winner = " and ".join(f"**{t['name']}**" for t in top)
        await self.bot.post("announcements", f"🏆 **The people have spoken.** The Big Digit Conference champion "
                                             f"{'is' if len(top) == 1 else 'are'} {winner}!\n" + "\n".join(lines))
        await reply(interaction, "Voting closed and the winner announced.")

    @app_commands.command(name="verdict", description="Crown a winner from the rankings, after a final audit.")
    async def verdict(self, interaction: discord.Interaction):
        audit = self.bot.game.verdict_by_audit()
        if not audit:
            return await reply(interaction, "No universities yet.")
        lines = [f"`{r['rank']:>2}.` {r['name']} ({r['code']}) · {r['score']:.1f}" for r in audit[:10]]
        await self.bot.post("announcements",
                            "📋 **The Final Audit.** The Big Digit Conference's auditors have reviewed every "
                            "ranking, reweighted the vibes, and rounded in all directions.\n\n"
                            f"🏆 Your champion: **{audit[0]['name']}** ({audit[0]['code']})!\n\n" + "\n".join(lines))
        await reply(interaction, "Verdict announced.")

    @app_commands.command(name="winners", description="Draw a winning university for each class section.")
    @app_commands.describe(announce="Post the draw you already saw, instead of drawing again")
    async def winners(self, interaction: discord.Interaction, announce: bool = False):
        game = self.bot.game
        if not announce:
            return await reply(interaction, game.draw_report(game.draw_winners()))
        draw = game.saved_draw()
        if draw is None:
            return await reply(interaction, "No draw to announce. Run /admin winners first.")
        await self.bot.post("announcements", game.draw_announcement(draw))
        game.clear_draw()
        await reply(interaction, "Winners announced.")

    # ---- exports -------------------------------------------------------------
    @app_commands.command(name="participation", description="Download a participation report for grading.")
    async def participation(self, interaction: discord.Interaction):
        data = self.bot.game.participation_csv().encode()
        await interaction.response.send_message("Participation, one row per player.",
                                                file=discord.File(io.BytesIO(data), filename="participation.csv"),
                                                ephemeral=True)

    @app_commands.command(name="backup", description="Download a safe copy of the game's database.")
    async def backup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"{config.DB_PATH.stem}-backup.db"
            self.bot.db.backup_to(path)
            if path.stat().st_size > 8_000_000:
                return await interaction.followup.send("The database is too large to send through Discord. Download "
                                                       "it from the host's backups folder instead.", ephemeral=True)
            await interaction.followup.send("Here's a copy of the database. It holds players' Discord IDs, so keep "
                                            "it private.", file=discord.File(path), ephemeral=True)

    @app_commands.command(name="export", description="Download the Collected Statutes and price history.")
    async def export(self, interaction: discord.Interaction):
        game = self.bot.game
        files = [discord.File(io.BytesIO(game.export_statutes().encode()), filename="collected-statutes.md"),
                 discord.File(io.BytesIO(game.history_json().encode()), filename="price-history.json")]
        await interaction.response.send_message("Here's the archive.", files=files, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
