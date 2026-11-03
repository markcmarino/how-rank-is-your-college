# How Rank is Your College? (project notes for Claude Code)

Discord bot (discord.py 2.x, Python 3.11+) for Mark Marino and Rob Wittig's netprov of the same name, part of the
UnderAcademy College storyworld. Satire of AI in higher education. About 60 students in teams of ~4, plus featured
players with solo universities, play publicly from about Nov 9 to Nov 21, 2026, often asynchronously.

Players play by posting with hashtags; there are no player slash commands for playing. The bot ranks universities
nightly as stocks on the "UnderAcademy Exchange" and publishes a public page, the "US Snooze & Whirled Retort".
The winner is chosen at the end by a player vote or by `/admin verdict` (rankings plus a random Final Audit).

## Layout

- `bot/parsing.py`: hashtags, names, tickers, round and kind tags, keyword domain guessing. Pure functions.
- `bot/engine.py`: pure game logic. `run_day()` is the closing bell. Test here first.
- `bot/game.py`: filing posts (`register_or_pitch`, `file_policy`, `file_character`, `file_diary`), rounds
  (`due_round` from Sheet dates), `close()` / `commit()`, the finale, participation CSV, exports.
- `bot/tables.py`: lookup tables from the Google Sheet (`TABLES_SHEET_ID`, read via CSV export by fixed tab gid
  1001 to 1009), falling back per tab to `data/sheet_cache/` then `data/tables/`.
- `bot/site.py`: builds the public page and publishes it to the `gh-pages` branch via the GitHub contents API.
- `bot/cogs/posts.py` (message listener), `players.py` (lookups and /vote), `admin.py` (`/admin`, Manage Server only).
- `bot/ai.py`: optional Claude layer, off by default (Mark chose tables only).
- `data/tuning.json`: balance numbers. `scripts/simulate.py`: offline season. `tests/`: pytest.

## Conventions

- Run `python -m pytest tests` and `python -m scripts.simulate --days 14` after changes.
- If you change a table's columns, update `tables.TABS`, the CSV in `data/tables/` and the Sheet together, and
  never rename tabs or change their gids: Mark and Rob edit the Sheet directly.
- Stats are 0 to 100 except `lawsuits` (0 to 10). Endowment is an index shown as Fake Dollars (`reports.money`).
- Game text voice: deadpan wire service meets campus newspaper. Mark dislikes em dashes; don't use them anywhere.
- Never commit `.env`, `game.db`, `site/` or `data/sheet_cache/`.

## Ideas for later

- A separate game for late or out-of-season groups (a second bot instance with its own database is simplest).
