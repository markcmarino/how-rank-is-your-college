"""Player commands: found and join a university, pitch it, pass policies, answer challenges, check rankings."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from .. import config, reports
from .common import DOMAIN_CHOICES, parse_policy_ref, reply, school_autocomplete


# ---- forms (Discord modals) -------------------------------------------------

class PitchForm(discord.ui.Modal, title="College Fair Pitch"):
    pitch = discord.ui.TextInput(label="Your pitch", style=discord.TextStyle.paragraph, max_length=4000)

    def __init__(self, cog: "Players", school):
        super().__init__()
        self.cog, self.school = cog, school
        if school["pitch"]:
            self.pitch.default = school["pitch"]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        db = self.cog.bot.db
        db.update_school(self.school["id"], pitch=self.pitch.value)
        await self.cog.bot.post("fair", f"🎪 **{self.school['name']}** ({self.school['code']})\n"
                                        f"_{self.school['motto'] or ''}_\n\n{self.pitch.value}")
        await reply(interaction, "Your pitch is posted at the College Fair.")


class PolicyForm(discord.ui.Modal):
    policy_title = discord.ui.TextInput(label="Policy title", max_length=120)
    text = discord.ui.TextInput(label="The policy", style=discord.TextStyle.paragraph, max_length=1500)
    pros = discord.ui.TextInput(label="Pros", style=discord.TextStyle.paragraph, max_length=800, required=False)
    cons = discord.ui.TextInput(label="Cons", style=discord.TextStyle.paragraph, max_length=800, required=False)

    def __init__(self, cog: "Players", school, domain: str, amends=None):
        super().__init__(title=f"Amend {school['code']}-{amends['number']}" if amends else "New AI Policy")
        self.cog, self.school, self.domain, self.amends = cog, school, domain, amends
        if amends:
            self.policy_title.default = amends["title"]
            self.text.default = amends["text"]
            self.pros.default = amends["pros"] or ""
            self.cons.default = amends["cons"] or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        db, game = self.cog.bot.db, self.cog.bot.game
        rnd = game.current_round()
        policy = db.add_policy(self.school["id"], self.policy_title.value, self.text.value, self.pros.value,
                               self.cons.value, self.domain, rnd["key"] if rnd else None, interaction.user.id,
                               parent_id=self.amends["id"] if self.amends else None)
        if self.amends:
            db.set_policy_status(self.amends["id"], "Amended")
        card = reports.policy_card(policy, self.school["code"],
                                   amended_from=self.amends["number"] if self.amends else None)
        await self.cog.bot.post("policies", f"📜 **{self.school['name']}**\n{card}")
        await reply(interaction, f"Filed as **{self.school['code']}-{policy['number']}**. "
                                 f"The market will price it in at the next closing bell.")


# ---- commands ---------------------------------------------------------------

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def my_school(self, interaction: discord.Interaction):
        return self.bot.db.school_of(interaction.user.id)

    @app_commands.command(name="found", description="Found a new university and list it on the UnderAcademy Exchange.")
    @app_commands.describe(name="Full name of your university", ticker="2 to 5 letter stock symbol, e.g. GRPU",
                           location="Where it is", specialties="Academic specialties",
                           reputation="Its reputation", colors="School colors", mascot="Mascot",
                           motto="Motto (optional)")
    async def found(self, interaction: discord.Interaction, name: str, ticker: str, location: str,
                    specialties: str, reputation: str, colors: str, mascot: str, motto: str | None = None):
        db = self.bot.db
        ticker = ticker.upper().strip()
        if not re.fullmatch(r"[A-Z]{2,5}", ticker):
            return await reply(interaction, "The ticker must be 2 to 5 letters, like GRPU.")
        if db.find_school(name) or db.find_school(ticker):
            return await reply(interaction, "That name or ticker is already taken on the Exchange.")
        school_id = db.add_school(dict(name=name.strip(), code=ticker, location=location, specialties=specialties,
                                       reputation=reputation, colors=colors, mascot=mascot, motto=motto),
                                  self.bot.game.new_school_stats())
        db.join(interaction.user.id, school_id)
        channel = await self._team_channel(interaction.guild, db.school(school_id), interaction.user)
        await self.bot.post("announcements",
                            f"🏛️ **{name}** ({ticker}) is now listed on the UnderAcademy Exchange!\n"
                            f"{location} · {specialties} · Colors: {colors} · Mascot: {mascot}"
                            + (f"\n_{motto}_" if motto else ""))
        await reply(interaction, f"Welcome, administrator. {name} trades as **{ticker}**."
                                 + (f" Your team channel is {channel.mention}." if channel else "")
                                 + " Teammates can join with /join. Next: /pitch.")

    @app_commands.command(name="join", description="Join a university's team.")
    @app_commands.autocomplete(university=school_autocomplete)
    async def join(self, interaction: discord.Interaction, university: str):
        school = self.bot.db.find_school(university)
        if school is None:
            return await reply(interaction, "I couldn't find that university.")
        self.bot.db.join(interaction.user.id, school["id"])
        if school["channel_id"]:
            channel = interaction.guild.get_channel(school["channel_id"]) if interaction.guild else None
            if channel:
                try:
                    await channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
                except discord.Forbidden:
                    pass
        await reply(interaction, f"You're on the team at **{school['name']}**.")

    @app_commands.command(name="pitch", description="Write or edit your College Fair pitch.")
    async def pitch(self, interaction: discord.Interaction):
        school = self.my_school(interaction)
        if school is None:
            return await reply(interaction, "Join a university first with /found or /join.")
        await interaction.response.send_modal(PitchForm(self, school))

    policy = app_commands.Group(name="policy", description="Your university's AI policies")

    @policy.command(name="propose", description="Propose a new AI policy for your university.")
    @app_commands.choices(domain=DOMAIN_CHOICES)
    async def propose(self, interaction: discord.Interaction, domain: app_commands.Choice[str]):
        school = self.my_school(interaction)
        if school is None:
            return await reply(interaction, "Join a university first with /found or /join.")
        rnd = self.bot.game.current_round()
        if rnd:
            used = self.bot.db.count_new_policies(school["id"], rnd["key"])
            if used >= rnd["new_policy_limit"]:
                return await reply(interaction, f"Your university has used all {rnd['new_policy_limit']} new "
                                                f"policies for {rnd['name']}. You can still /policy amend.")
        await interaction.response.send_modal(PolicyForm(self, school, domain.value))

    @policy.command(name="amend", description="Amend one of your policies, e.g. GRPU-3.")
    async def amend(self, interaction: discord.Interaction, policy: str):
        school, row = parse_policy_ref(self.bot.db, policy)
        mine = self.my_school(interaction)
        if row is None:
            return await reply(interaction, "I couldn't find that policy. Use its label, like GRPU-3.")
        if mine is None or mine["id"] != school["id"]:
            return await reply(interaction, "You can only amend your own university's policies.")
        if row["status"] != "Active":
            return await reply(interaction, f"That policy is {row['status']}, so it can't be amended.")
        await interaction.response.send_modal(PolicyForm(self, school, row["domain"], amends=row))

    @policy.command(name="repeal", description="Repeal one of your policies, e.g. GRPU-3.")
    async def repeal(self, interaction: discord.Interaction, policy: str):
        school, row = parse_policy_ref(self.bot.db, policy)
        mine = self.my_school(interaction)
        if row is None or mine is None or mine["id"] != school["id"]:
            return await reply(interaction, "I couldn't find that policy among yours.")
        self.bot.db.set_policy_status(row["id"], "Repealed")
        self.bot.db.log_policy(row["id"], self.bot.db.day + 1, "Repealed by the administration.")
        await self.bot.post("policies", f"🗑️ **{school['name']}** has repealed {school['code']}-{row['number']}: "
                                        f"{row['title']}")
        await reply(interaction, "Repealed.")

    @policy.command(name="view", description="Read one policy and its consequences, e.g. GRPU-3.")
    async def view(self, interaction: discord.Interaction, policy: str):
        school, row = parse_policy_ref(self.bot.db, policy)
        if row is None:
            return await reply(interaction, "I couldn't find that policy.")
        text = reports.policy_card(row, school["code"]) + f"\n**Status:** {row['status']}"
        log = self.bot.db.policy_log(row["id"])
        if log:
            text += "\n**Consequences:**\n" + "\n".join(f"• Day {e['day']}: {e['entry']}" for e in log)
        await reply(interaction, text)

    @app_commands.command(name="policies", description="List a university's policies (yours by default).")
    @app_commands.autocomplete(university=school_autocomplete)
    async def policies(self, interaction: discord.Interaction, university: str | None = None):
        school = self.bot.db.find_school(university) if university else self.my_school(interaction)
        if school is None:
            return await reply(interaction, "Pick a university, or join one first.")
        rows = self.bot.db.policies(school["id"])
        if not rows:
            return await reply(interaction, f"{school['name']} has no policies yet.")
        lines = [f"**{school['name']} · Policy Register**"]
        lines += [f"`{school['code']}-{p['number']}` {p['title']} · _{p['status']}_" for p in rows]
        await reply(interaction, "\n".join(lines))

    @app_commands.command(name="respond", description="Answer the current round's challenge for your university.")
    async def respond(self, interaction: discord.Interaction, answer: str):
        school = self.my_school(interaction)
        rnd = self.bot.game.current_round()
        if school is None:
            return await reply(interaction, "Join a university first with /found or /join.")
        if rnd is None:
            return await reply(interaction, "There's no challenge open right now.")
        self.bot.db.add_response(school["id"], rnd["key"], answer)
        await self.bot.post("announcements", f"📣 **{school['name']}** responds to {rnd['name']}:\n> {answer}")
        await reply(interaction, "Your answer is on the record. The market reacts at the closing bell.")

    @app_commands.command(name="round", description="Show the current round and its challenge.")
    async def round_info(self, interaction: discord.Interaction):
        rnd = self.bot.game.current_round()
        if rnd is None:
            return await reply(interaction, "The game hasn't started a round yet.")
        await reply(interaction, f"**{rnd['name']}**\n**Challenge:** {rnd['challenge']}\n"
                                 f"**Administrators:** {rnd['institutional']}\n**Characters:** {rnd['character']}")

    @app_commands.command(name="rankings", description="The latest prices and Big Digit Conference rankings.")
    async def rankings(self, interaction: discord.Interaction):
        db = self.bot.db
        day = db.day
        if day == 0:
            return await reply(interaction, "The Exchange hasn't closed yet. Check back after the first closing bell.")
        snap, prev = db.snapshot(day), db.snapshot(day - 1)
        rows = []
        for s in db.schools():
            if s["id"] in snap:
                r, p = snap[s["id"]], prev.get(s["id"])
                rows.append({"name": s["name"], "code": s["code"], "price": r["price"], "score": r["score"],
                             "rank": r["rank"], "prev_price": p["price"] if p else None,
                             "prev_rank": p["rank"] if p else None})
        await reply(interaction, reports.ticker(rows) + "\n" + reports.league_table(rows, day))

    @app_commands.command(name="report", description="Your university's latest daily report.")
    async def report(self, interaction: discord.Interaction):
        school = self.my_school(interaction)
        if school is None:
            return await reply(interaction, "Join a university first with /found or /join.")
        db = self.bot.db
        events = [{"text": e["text"]} for e in db.events(db.day, school["id"])]
        await reply(interaction, reports.school_report(school, db.day, events, db.all_stats()[school["id"]]))

    async def _team_channel(self, guild: discord.Guild | None, school, founder) -> discord.TextChannel | None:
        """Creates a private channel for the team, if the bot has permission."""
        if guild is None or not config.CREATE_TEAM_CHANNELS:
            return None
        try:
            category = discord.utils.get(guild.categories, name=config.TEAM_CATEGORY) \
                or await guild.create_category(config.TEAM_CATEGORY)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                founder: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            name = re.sub(r"[^a-z0-9]+", "-", school["name"].lower()).strip("-")[:90]
            channel = await guild.create_text_channel(name, category=category, overwrites=overwrites,
                                                      topic=f"{school['name']} ({school['code']}) team channel")
            self.bot.db.update_school(school["id"], channel_id=channel.id)
            return channel
        except discord.Forbidden:
            return None


async def setup(bot):
    await bot.add_cog(Players(bot))
