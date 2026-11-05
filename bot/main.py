"""The Discord bot: startup, posting, and the nightly routine (tables, rounds, closing bell, public page)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from . import config, reports, site, tables
from .db import Database
from .game import CloseReport, Game

log = logging.getLogger("rankbot")

ZONE = ZoneInfo(config.TIMEZONE)
NIGHTLY = time(hour=config.UPDATE_HOUR, minute=config.UPDATE_MINUTE, tzinfo=ZONE)


class RankBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True   # needed to read players' posts
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(config.DB_PATH)
        self.game = Game(self.db)
        self.close_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        await self.loop.run_in_executor(None, tables.refresh)
        for ext in ("bot.cogs.posts", "bot.cogs.players", "bot.cogs.admin"):
            await self.load_extension(ext)
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.nightly.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s; closing bell daily at %s %s", self.user, NIGHTLY, config.TIMEZONE)
        await self.get_cog("Posts").catch_up()   # also runs after a reconnect, which can miss posts too

    # ---- helpers ---------------------------------------------------------
    def home_guild(self) -> discord.Guild | None:
        if config.GUILD_ID:
            return self.get_guild(config.GUILD_ID)
        return self.guilds[0] if self.guilds else None

    def channel(self, key: str) -> discord.TextChannel | None:
        guild = self.home_guild()
        return discord.utils.get(guild.text_channels, name=config.CHANNELS[key]) if guild else None

    async def post(self, key: str, text: str) -> discord.Message | None:
        channel = self.channel(key)
        if channel is None:
            log.warning("Channel #%s not found; run /admin setup", config.CHANNELS[key])
            return None
        first = None
        for chunk in reports.split(text):
            sent = await channel.send(chunk)
            first = first or sent
        return first

    def market_rows(self, day: int) -> list[dict]:
        snap, prev = self.db.snapshot(day), self.db.snapshot(day - 1)
        rows = []
        for s in self.db.schools():
            if s["id"] in snap:
                r, p = snap[s["id"]], prev.get(s["id"])
                rows.append({"name": s["name"], "code": s["code"], "price": r["price"], "score": r["score"],
                             "rank": r["rank"], "prev_price": p["price"] if p else None,
                             "prev_rank": p["rank"] if p else None})
        return rows

    async def announce_round(self, rnd: dict | None) -> None:
        if rnd:
            def link(key: str) -> str:
                channel = self.channel(key)
                return channel.mention if channel else f"#{config.CHANNELS[key]}"

            await self.post("announcements", f"📯 **{rnd['name']} begins!**\n\n"
                                             f"**Administrators:** {rnd['institutional']} "
                                             f"Post it in {link('policies')}.\n\n"
                                             f"**Characters:** {rnd['character']} "
                                             f"Post it in {link('diaries')}.\n\n"
                                             f"_Catching up on an earlier round? Add its tag, like #round1, "
                                             f"to your post._")

    async def publish(self, report: CloseReport) -> None:
        """Posts a closing bell: commentary, ticker and table, with each university's report in a thread."""
        await self.post("exchange", f"🔔 **Closing Bell · Day {report.day}**\n{report.commentary}")
        await self.post("exchange", report.ticker)
        table_msg = await self.post("exchange", report.table)
        if table_msg is not None and report.school_reports:
            try:
                thread = await table_msg.create_thread(name=f"Day {report.day} university reports")
                for text in report.school_reports.values():
                    for chunk in reports.split(text):
                        await thread.send(chunk)
            except discord.HTTPException:
                log.exception("Couldn't post the daily reports thread")
        await self.update_site()
        url = site.public_url()
        if url:
            await self.post("exchange", f"📰 **Read the full story in the US Snooze & Whirled Retort:**\n{url}")

    async def update_site(self) -> None:
        try:
            files = site.build(self.db, self.game)
            site.write_local(files)
            url = await self.loop.run_in_executor(None, site.publish, files)
            if url:
                log.info("Published the US Snooze & Whirled Retort at %s", url)
        except Exception:
            log.exception("Couldn't update the public rankings page")

    async def run_close(self) -> CloseReport | None:
        async with self.close_lock:
            if not self.db.schools():
                return None
            report = await self.game.close()
            self.game.commit(report)
        await self.publish(report)
        return report

    # ---- every night at the closing bell ---------------------------------------
    @tasks.loop(time=NIGHTLY)
    async def nightly(self) -> None:
        await self.closing_routine()

    def backup(self) -> None:
        """Keeps a safe dated copy of the database beside it, for the last two weeks."""
        folder = config.DB_PATH.parent / "backups"
        folder.mkdir(exist_ok=True)
        self.db.backup_to(folder / f"{config.DB_PATH.stem}-{datetime.now(ZONE):%Y-%m-%d}.db")
        for old in sorted(folder.glob(f"{config.DB_PATH.stem}-*.db"))[:-14]:
            old.unlink()

    async def closing_routine(self) -> None:
        self.db.set("last_bell", datetime.now(ZONE).date().isoformat())
        try:
            self.backup()
        except Exception:
            log.exception("Nightly backup failed")
        if self.db.get("paused") == "1":
            log.info("Nightly routine skipped: paused")
            return
        try:
            await self.loop.run_in_executor(None, tables.refresh)
            await self.run_close()
            due = self.game.due_round(datetime.now(ZONE).date())
            if due:
                await self.announce_round(self.game.open_round(due["key"]))
        except Exception:
            log.exception("Nightly routine failed")

    @nightly.before_loop
    async def _wait_until_ready(self) -> None:
        await self.wait_until_ready()
        await self.get_cog("Posts").catch_up()
        today = datetime.now(ZONE).date().isoformat()
        last_bell = self.db.get("last_bell")
        if last_bell is None:
            self.db.set("last_bell", today)
        elif last_bell < today:                                # the bot was off at midnight
            log.info("Ringing the closing bell missed since %s", last_bell)
            await self.closing_routine()
        due = self.game.due_round(datetime.now(ZONE).date())   # catch up if the bot was off when a round opened
        if due:
            await self.announce_round(self.game.open_round(due["key"]))


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in (see README).")
    RankBot().run(config.DISCORD_TOKEN, log_handler=None)
