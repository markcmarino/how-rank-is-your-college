"""The Discord bot: startup, posting, and the daily market close."""

from __future__ import annotations

import asyncio
import logging
from datetime import time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from . import config, reports
from .db import Database
from .game import CloseReport, Game

log = logging.getLogger("rankbot")

CLOSE_TIME = time(hour=config.UPDATE_HOUR, minute=config.UPDATE_MINUTE, tzinfo=ZoneInfo(config.TIMEZONE))


class RankBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True   # needed to read Secret Diary posts
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(config.DB_PATH)
        self.game = Game(self.db)
        self.close_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        await self.load_extension("bot.cogs.players")
        await self.load_extension("bot.cogs.diaries")
        await self.load_extension("bot.cogs.admin")
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.market_close.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s; market closes daily at %s %s", self.user, CLOSE_TIME, config.TIMEZONE)

    # ---- helpers ---------------------------------------------------------
    def home_guild(self) -> discord.Guild | None:
        if config.GUILD_ID:
            return self.get_guild(config.GUILD_ID)
        return self.guilds[0] if self.guilds else None

    def channel(self, key: str) -> discord.TextChannel | None:
        guild = self.home_guild()
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=config.CHANNELS[key])

    async def post(self, key: str, text: str) -> None:
        channel = self.channel(key)
        if channel is None:
            log.warning("Channel #%s not found; run /admin setup", config.CHANNELS[key])
            return
        for chunk in reports.split(text):
            await channel.send(chunk)

    async def publish(self, report: CloseReport) -> None:
        """Posts a market close: commentary, ticker and table to the exchange; reports to team channels."""
        await self.post("exchange", f"🔔 **Closing Bell · Day {report.day}**\n{report.commentary}")
        await self.post("exchange", report.ticker)
        await self.post("exchange", report.table)
        for school in self.db.schools():
            text = report.school_reports.get(school["id"])
            channel = self.get_channel(school["channel_id"]) if school["channel_id"] else None
            if text and channel:
                for chunk in reports.split(text):
                    await channel.send(chunk)

    async def run_close(self) -> CloseReport | None:
        async with self.close_lock:
            if not self.db.schools():
                return None
            report = await self.game.close()
            self.game.commit(report)
        await self.publish(report)
        return report

    # ---- the daily market close --------------------------------------------
    @tasks.loop(time=CLOSE_TIME)
    async def market_close(self) -> None:
        if self.db.get("paused") == "1":
            log.info("Market close skipped: paused")
            return
        try:
            await self.run_close()
        except Exception:
            log.exception("Market close failed")

    @market_close.before_loop
    async def _wait_until_ready(self) -> None:
        await self.wait_until_ready()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in (see README).")
    RankBot().run(config.DISCORD_TOKEN, log_handler=None)
