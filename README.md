# How Rank is Your College?

A Discord bot for the UnderAcademy Exchange netprov. Teams found fictional universities, pass absurd AI
policies, and write Secret Diaries about living under them. Every day at the closing bell, the bot prices
each university as a stock, posts a ticker and the Big Digit Conference rankings, and sends each team a
report on what its policies caused. The rankings are for show: the player vote crowns the winner.

## How the game maps to the bot

| How to Play | What players do in Discord |
| --- | --- |
| Invent your University | `/found` (name, ticker, location, specialties, reputation, colors, mascot, motto). Teammates use `/join`. |
| College Fair Pitch | `/pitch` opens a form; the pitch is posted in #college-fair. |
| Write 5 AI policies with pros and cons | `/policy propose` (pick a domain, then fill in a form). Posted in #policy-register as e.g. GRPU-3. |
| Revise policies (patches, Extreme Measures) | `/policy amend GRPU-3` or `/policy repeal GRPU-3`. Old versions stay in the register. |
| Round challenges (A.I. Capone's offer, etc.) | Mark runs `/admin round`; teams answer with `/respond`. |
| Secret Diaries | Post in #secret-diaries starting with `#charactername #role #universityname`. The bot files it (📓) and uses it as evidence. |
| Rankings | Daily closing bell in #the-exchange, plus `/rankings` any time. Teams get a daily report in their private channel, or with `/report`. |
| The archive | `/admin export` downloads *The Collected Statutes* (policies, consequences, pitches, diaries) and the price history. |

Other player commands: `/policies [university]`, `/policy view GRPU-3`, `/round`.

Game-master commands (only visible to people with Manage Server): `/admin setup`, `/admin round`,
`/admin convene` (run a close now, optionally as a preview), `/admin publish`, `/admin decree`,
`/admin strike`, `/admin mode`, `/admin pause`, `/admin peek`, `/admin export`.

## Setup

### 1. Create the bot in Discord (about 10 minutes, once)

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it (for example "UnderAcademy Exchange").
2. Open **Bot** in the sidebar. Under **Privileged Gateway Intents**, turn on **Message Content Intent** (the bot needs it to read Secret Diaries).
3. On the same page, click **Reset Token** and copy the token. Treat it like a password: don't paste it in chats or commit it to GitHub.
4. Open **OAuth2 → URL Generator**. Check the scopes **bot** and **applications.commands**. Under bot permissions, check: View Channels, Send Messages, Read Message History, Add Reactions, Attach Files, Manage Channels, Manage Roles. Open the generated URL and add the bot to your server.
5. In Discord, turn on **User Settings → Advanced → Developer Mode**, then right-click your server's icon and choose **Copy Server ID**.

### 2. Install and configure

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit .env
```

In `.env`, paste your bot token into `DISCORD_TOKEN` and your server ID into `GUILD_ID`. Set the closing
bell time and time zone. To have Claude write the consequences, add an `ANTHROPIC_API_KEY` from
[console.anthropic.com](https://console.anthropic.com) (this is separate from a Claude Pro subscription and
is billed per use). Without a key, the bot uses the random consequence tables.

### 3. Run it

```bash
python -m bot
```

Then in Discord run `/admin setup` to create the public channels, and `/admin round` to open Welcome Week.

To keep the game running while your computer sleeps, run the bot on an always-on machine or a small cloud
server. The database is the single file `game.db`; back it up to back up the game.

## Testing and tuning

```bash
python -m pytest tests                     # engine tests
python -m scripts.simulate                 # a fake 25-school, 25-day season
python -m scripts.simulate --no-curse      # the same season without the Curse of Prestige
```

All balance numbers live in `data/tuning.json`, and all flavor text in the other files in `data/`:
consequence templates by domain (`domains.json`), the Curse of Prestige (`hubris.json`), underdog luck
(`underdog.json`), hidden-stat symptoms (`symptoms.json`) and the rounds and their challenges
(`rounds.json`). The bot rereads them at every closing bell, so edits take effect without a restart.

In the default simulation, the Curse of Prestige keeps first place about 3 points above the median on
average, versus about 8 without it. The whole field is fairly tight; raise the policy effects in
`domains.json` or `daily_drift` in `tuning.json` for bigger swings.

## How a closing bell works

1. Each new policy or amendment moves the school's stats, either as Claude decides (AI mode, clamped to the
   limits in `tuning.json`) or by its domain's baseline effects times a random roll. Every policy adds
   Bureaucracy, which dampens future gains, and Chaos, which widens future rolls.
2. Secret Diaries are evidence: they add buzz (Prestige) and shift Faculty Morale or Student Satisfaction.
   In AI mode, Claude reads them and decides what they reveal.
3. Answers to the round's challenge move the stats too.
4. Every stat drifts a little; hidden stats drift back toward normal.
5. The Curse of Prestige: the further a school is above the median, the more likely and severe its bad luck.
   Schools in the bottom quarter get a chance at a lucky break.
6. Thresholds: an occupation (low Satisfaction), faculty poaching (low Morale), an accreditation visit that
   strikes down a policy (high Lawsuit Exposure), a fire sale (empty Endowment).
7. Share price = 2.5 × a weighted score of the four public stats (Prestige 40%, the others 20% each).
