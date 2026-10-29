# How Rank is Your College? (project notes for Claude Code)

Discord bot (discord.py 2.x, Python 3.11+) for Mark Marino's netprov of the same name, part of the
UnderAcademy College storyworld. Satire of AI in higher education: player teams run fictional universities,
pass AI policies, and write Secret Diaries. The bot simulates consequences and ranks schools daily as stocks
on the "UnderAcademy Exchange" plus a "Big Digit Conference" league table. The final winner is a player vote,
so rankings are comic, not decisive.

## Layout

- `bot/engine.py`: pure game logic (no Discord, no DB). `run_day()` is the market close. Test here first.
- `bot/game.py`: glue between DB and engine. `Game.close()` computes a day (stored as `pending`), `commit()` saves it.
- `bot/ai.py`: optional Claude layer. Forced tool call `record_consequences`; effects are clamped by `data/tuning.json` → `ai_limits`. Any failure falls back to the tables.
- `bot/db.py`: SQLite schema and queries. Policies are versioned via `parent_id` (amendments).
- `bot/reports.py`: all Discord text formatting. Keep messages under 1900 chars (`split()`).
- `bot/cogs/`: `players.py` (slash commands + modals), `diaries.py` (parses #character #role #university posts), `admin.py` (`/admin` group, Manage Server only).
- `data/*.json`: tuning numbers and all flavor text. Reloaded at every close. Mark edits these by hand.
- `scripts/simulate.py`: offline season for balance tuning. `tests/`: pytest.

## Conventions

- Run `python -m pytest tests` and `python -m scripts.simulate` after engine changes.
- Stats are 0 to 100 except `lawsuits` (0 to 10). Endowment is an index shown as Fake Dollars (`reports.money`).
- Game text voice: deadpan wire service meets campus newspaper. Mark dislikes em dashes; don't use them in game text or docs.
- Never commit `.env` or `game.db`.

## Open design questions (from Mark's How to Play doc)

- The doc's numbering mixes "ROUND ONE / ROUND TWO" with Rounds 1 to 3 plus an Epilogue; `data/rounds.json` uses the latter.
- Placeholders still to fill in the doc: pitch length, diary entry counts, the "INCLUDE:" list for pitches.
- The final player vote is not implemented in the bot yet (could be a Discord poll or a `/vote` command).
