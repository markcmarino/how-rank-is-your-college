# How Rank is Your College?

A Discord bot for the UnderAcademy Exchange netprov. Players found fictional universities, post absurd AI
policies, and write Secret Diaries about living under them. Every night at midnight Pacific the bot prices each
university as a stock, posts the closing bell in Discord, and publishes the rankings as a public web page,
the **US Snooze & Whirled Retort**.

Players don't need any commands. They just post, starting with hashtags, and the bot files each post.

## How players play

| Channel | What to post | What the bot does |
| --- | --- | --- |
| #college-pitches-rank | `#TaukTechU` then the pitch. Optional lines: `Name:`, `Mascot:`, `Colors:`, `Location:`, `Motto:` | The first post with a new hashtag registers the university and gives it a ticker (TTU). Later posts add to the pitch. 🏛️ |
| #character-intros-rank | `#Ellen #groundskeeper #TaukTechU` then the introduction | Files the character. 👋 |
| #policies-rank | `#TaukTechU` then the policy | Files it as the current round's kind (Policy, Amendment, Extreme Measure, Graduation Speech), guesses its domain from keywords, and prices it in at the next closing bell. 📜 |
| #secret-diary-rank | `#Ellen #groundskeeper #TaukTechU` then the entry | Files it as evidence for the next closing bell. 📓 |

- **In a class?** Add `#10am`, `#11am` or `#1pm` to the university's pitch and to your character's introduction.
  An introduction fills in a missing section, but only a pitch or `/admin school` can change one. Guests leave it off
  and aren't entered in the class winner draw.
- **Misspelled hashtag?** The bot replies "Did you mean #TaukTechU?" A genuinely new university that looks like
  an existing one can add `#new` to its first pitch.
- **Catching up?** Add a round tag, such as `#round1`, `#welcomeweek`, `#midterms`, `#finals` or `#epilogue`, and
  the post counts for that round. A policy post can also say its kind with `#amendment`, `#extrememeasure` or `#speech`.
- **Joining late?** A university registered after the first closing bell starts at the current median, so it
  enters the rankings in the middle of the pack.

Lookup commands for anyone: `/rankings`, `/report`, `/policies`, `/policy TTU-3`, `/round`, and `/vote` when voting is open.

## Running the game (Mark and Rob)

- **Rounds open themselves** at midnight Pacific on the dates in the Sheet's Rounds tab (Nov 9, 13, 17 and 20).
  `/admin round` opens one by hand.
- **The closing bell** runs every night at midnight: commentary, ticker, table and a link to the Retort in #rankings-rank, each
  university's report in a thread under it, then the public page. `/admin convene` runs one early, and
  `preview:True` shows it to you first (post it with `/admin publish`).
- **University Under Review:** each edition of the public page features at least two universities, longest-waiting
  first, so everyone gets a turn before anyone gets a second.
- **The finale**, whenever you like (including for groups playing out of season): `/admin vote open`, then
  `/admin vote close` to announce the people's champion (players can't vote for a university they posted for),
  or `/admin verdict` to crown a winner from the rankings after a randomized Final Audit.
- **Class winners:** `/admin winners` privately draws one university for each class section, with one ticket per
  filed post, and shows everyone's odds. Run it again to redraw, then use `announce:True` to post that draw.
- **Grading:** `/admin participation` downloads a spreadsheet with one row per player: total posts and words,
  counts by kind and by round, and first and last post dates.
- **Backups:** the bot saves a dated copy of the database in a `backups` folder beside it each night and keeps two
  weeks of them. `/admin backup` sends you a copy privately in Discord.
- **If the bot restarts:** it files anything posted while it was away, using the time each post was made, and rings a
  closing bell it missed at midnight.
- **Other tools:** `/admin decree` (a custom event, optionally moving a stat), `/admin strike TTU-3`,
  `/admin school` (fix a name, ticker or mascot), `/admin peek` (hidden stats), `/admin pause`,
  `/admin export` (*The Collected Statutes* and the price history), `/admin setup` (create missing channels).

### Editing the lookup tables

All the flavor text and policy effects live in the Google Sheet
[How Rank is Your College? Lookup Tables](https://docs.google.com/spreadsheets/d/1ubSMUIj99iqO6Dx_BE7EbwDM6_96uyfE2pmGIuhY6Rg/edit).
Its Read Me tab explains each tab and the placeholders. The bot rereads it every night; `/admin tables` reloads it
immediately and reports any tab it couldn't read. If the Sheet can't be reached, the bot uses the last good copy,
and failing that the starter copies in `data/tables/`. Balance numbers that rarely change are in `data/tuning.json`.

## Setup

### 1. Create the bot in Discord (about 10 minutes, once)

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it (for example "UnderAcademy Exchange").
2. Open **Bot**. Under **Privileged Gateway Intents**, turn on **Message Content Intent** (the bot reads posts).
3. On the same page, click **Reset Token** and copy the token. Treat it like a password.
4. Open **OAuth2 → URL Generator**. Check the scopes **bot** and **applications.commands**. Bot permissions: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Read Message History, Add Reactions, Attach Files, Manage Channels. Open the generated URL and add the bot to your server.
5. In Discord, turn on **User Settings → Advanced → Developer Mode**, then right-click the server icon and **Copy Server ID**.

### 2. Install and configure

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit .env
```

In `.env`, paste the bot token into `DISCORD_TOKEN` and the server ID into `GUILD_ID`. The Sheet ID is
already filled in.

### 3. Turn on the public page (optional)

1. Make this repo public (GitHub → Settings → General → Danger Zone → Change visibility). Free GitHub Pages needs it.
2. Create a token at GitHub → Settings → Developer settings → **Fine-grained personal access tokens**: only this
   repository, with **Contents: Read and write**. Paste it into `SITE_GITHUB_TOKEN` in `.env`.
3. After the first closing bell creates the `gh-pages` branch, go to the repo's **Settings → Pages** and set
   the source to **Deploy from a branch**, branch `gh-pages`, folder `/ (root)`.

The page appears at https://markcmarino.github.io/how-rank-is-your-college/ and updates every night, with
an archive of each day at `archive/day-N.html`. Even without a token, the bot writes the page to `site/index.html`.

To recruit players from the page, set `DISCORD_INVITE_URL` (a Discord invite set to never expire) and
`CONTACT_EMAIL` in `.env` (and in Railway's Variables). The front page then shows a "Want to Play?" box with the
invite, a three-step quick start and a "Trouble getting in? Contact us" line. Leave `DISCORD_INVITE_URL` blank to
hide the box. The link preview card and the netprov logo live in `bot/static/`; `scripts/make_card.py` remakes
the card if the design changes.

### 4. Run it

```bash
python -m bot
```

Then in Discord run `/admin setup` to create the channels. The bot must keep running for the whole game, so use
a computer that stays awake or a small cloud server. The database is the single file `game.db`; back it up to
back up the game.

## Testing and tuning

```bash
python -m pytest tests                     # tests
python -m scripts.simulate --days 14       # a fake 25-university season
python -m scripts.simulate --no-curse      # the same, without the Curse of Prestige
```

## How a closing bell works

1. Each new policy post moves its university's stats by its domain's effects (from the Sheet) times a random
   roll. Every post adds Bureaucracy, which dampens future gains, and Chaos, which widens future rolls.
2. Secret Diaries are evidence: they add buzz (Prestige), shift Faculty Morale or Student Satisfaction, and one
   is quoted as a "leak."
3. Every stat drifts a little; hidden stats drift back toward normal.
4. The Curse of Prestige: the further a university is above the median, the likelier and harsher its bad luck.
   The bottom quarter gets a chance at a lucky break.
5. Thresholds: an occupation (low Satisfaction), faculty poaching (low Morale), an accreditation visit that strikes
   down a policy (high Lawsuit Exposure), a fire sale (empty Endowment).
6. Share price = 2.5 × a weighted score of the public stats (Prestige 40%, Endowment, Enrollment and Satisfaction 20% each).
