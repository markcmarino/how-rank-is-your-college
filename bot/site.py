"""The US Snooze & Whirled Retort: a public web page of the rankings, rebuilt after every closing bell.

The page is always written to site/ in the project folder. If SITE_GITHUB_TOKEN and SITE_REPO are set,
it is also published to the repo's gh-pages branch, which GitHub Pages serves as a public website.
"""

from __future__ import annotations

import html
import json
import logging
import random
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import config, parsing, reports

log = logging.getLogger(__name__)
SITE_DIR = config.ROOT / "site"

CSS = """
:root { --paper:#fbf8f1; --ink:#1d1b18; --muted:#6b645a; --rule:#d9d1c3; --accent:#8c1c13; --up:#1f6b3a; --down:#a1261b; --band:#f1ebdf; }
@media (prefers-color-scheme: dark) { :root { --paper:#17150f; --ink:#ece6da; --muted:#a59c8e; --rule:#3a352c; --accent:#e0705f; --up:#6fcf8f; --down:#ff8a7a; --band:#211e17; } }
* { box-sizing:border-box; }
a { color:inherit; text-decoration-color:var(--rule); text-underline-offset:2px; }
a:hover { color:var(--accent); text-decoration-color:currentColor; }
.masthead h1 a { text-decoration:none; color:inherit; }
.days { display:flex; flex-wrap:wrap; gap:6px 14px; border-bottom:1px solid var(--rule); padding:8px 0;
  font:13px/1.4 system-ui, sans-serif; color:var(--muted); }
.section { padding-top:20px; }
.grid > section { min-width:0; }
.body { white-space:pre-line; }
.story, blockquote { overflow-wrap:anywhere; }
.standing { margin:10px 0 0 !important; font:15px/1.4 system-ui, sans-serif; }
.lead p.tag { margin:0; font:14px/1.4 system-ui, sans-serif; }
.facts { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px 24px; margin:14px 0 0; }
.facts dt { font:600 12px/1.4 system-ui, sans-serif; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
.facts dd { margin:0; }
blockquote ul { margin:6px 0 0; padding-left:18px; font:normal 13px/1.45 system-ui, sans-serif; color:var(--muted); }
body { margin:0; background:var(--paper); color:var(--ink); font:17px/1.55 Georgia, "Times New Roman", serif; }
.wrap { max-width:960px; margin:0 auto; padding:24px 16px 64px; }
.masthead { text-align:center; border-bottom:3px double var(--ink); padding-bottom:12px; }
.masthead .over { font:600 12px/1.4 system-ui, sans-serif; letter-spacing:.18em; text-transform:uppercase; color:var(--muted); }
.masthead h1 { font-size:clamp(34px, 7vw, 64px); line-height:1; margin:8px 0 6px; font-weight:700; letter-spacing:-.01em; }
.dateline { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; border-bottom:1px solid var(--rule);
  padding:8px 0; font:13px/1.4 system-ui, sans-serif; color:var(--muted); }
.ticker { overflow-x:auto; white-space:nowrap; border-bottom:1px solid var(--rule); padding:8px 0;
  font:13px/1.4 ui-monospace, Menlo, Consolas, monospace; }
.ticker span { margin-right:22px; }
.up { color:var(--up); } .down { color:var(--down); }
.lead { padding:20px 0; border-bottom:1px solid var(--rule); }
.lead h2 { font-size:clamp(24px, 4vw, 36px); line-height:1.15; margin:0 0 10px; }
.lead p { margin:0; font-size:19px; }
.grid { display:grid; grid-template-columns:1.4fr 1fr; gap:32px; padding-top:20px; }
@media (max-width:760px) { .grid { grid-template-columns:1fr; } }
h3 { font:700 13px/1.3 system-ui, sans-serif; letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
  border-top:2px solid var(--ink); padding-top:8px; margin:0 0 12px; }
table { width:100%; border-collapse:collapse; font:15px/1.4 system-ui, sans-serif; }
th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  border-bottom:1px solid var(--rule); padding:6px 4px; }
td { border-bottom:1px solid var(--rule); padding:8px 4px; vertical-align:top; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.move { font-size:12px; white-space:nowrap; margin-left:4px; }
tr:nth-child(even) td { background:var(--band); }
.tag { color:var(--muted); font-size:13px; }
.story { margin:0 0 16px; padding-bottom:14px; border-bottom:1px solid var(--rule); }
.story:last-child { border-bottom:0; }
.story .who { font:600 12px/1.4 system-ui, sans-serif; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
blockquote { margin:0 0 16px; padding:0 0 0 14px; border-left:3px solid var(--accent); font-style:italic; }
blockquote cite { display:block; font:normal 13px/1.4 system-ui, sans-serif; color:var(--muted); margin-top:4px; }
footer { margin-top:40px; border-top:3px double var(--ink); padding-top:12px; font:13px/1.5 system-ui, sans-serif; color:var(--muted); text-align:center; }
"""


def _e(text) -> str:
    return html.escape(str(text or ""))


def _slug(school) -> str:
    return school["tag_key"] or f"school-{school['id']}"


def _shell(title: str, description: str, home: str, body: str) -> str:
    """The parts every page shares. home is the relative link back to the front page."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<style>{CSS}</style></head>
<body><div class="wrap">
<header class="masthead"><div class="over">The UnderAcademy Exchange presents</div>
<h1><a href="{home}">US Snooze &amp; Whirled Retort</a></h1>
<div class="over">Big Digit Conference Rankings · How Rank is Your College?</div></header>
{body}
<footer>A netprov. Any resemblance to real universities, living or dead, is purely coincidental.<br>
Share prices are not financial advice. Nothing is.</footer>
</div></body></html>"""


def build(db, game) -> dict[str, str]:
    """Returns {path: content} for the site: index.html, rankings.json, a dated archive page and a page for
    each university."""
    day = db.day
    snap, prev = db.snapshot(day), db.snapshot(day - 1)
    schools = {s["id"]: s for s in db.schools()}
    rows = []
    for sid, r in snap.items():
        p = prev.get(sid)
        rows.append({"rank": r["rank"], "name": schools[sid]["name"], "hashtag": schools[sid]["hashtag"],
                     "code": schools[sid]["code"], "price": r["price"], "score": r["score"],
                     "prev_price": p["price"] if p else None, "prev_rank": p["rank"] if p else None,
                     "school_id": sid})
    rows.sort(key=lambda r: r["rank"])
    events = db.events(day)
    rnd = game.current_round()
    commentary = db.get(f"commentary_{day}", "") or ""
    today = datetime.now()
    stamp = f"{today:%A, %B} {today.day}, {today.year}"
    dateline = (f"<div class='dateline'><span>{_e(stamp)}</span><span>Trading Day {day}</span>"
                f"<span>{_e(rnd['name'] if rnd else 'Preseason')}</span></div>")

    def change(r):
        pct = reports.pct_change(r["price"], r["prev_price"])
        cls = "up" if pct > 0.005 else ("down" if pct < -0.005 else "")
        return pct, cls

    # Lead story: the biggest mover
    lead_html = "<h2>Markets await the first closing bell</h2><p>No trading yet. Analysts are stretching.</p>"
    if rows:
        mover = max(rows, key=lambda r: abs(change(r)[0]))
        pct, _ = change(mover)
        verb = "Soars" if pct > 0 else ("Sinks" if pct < 0 else "Holds Steady")
        lead_html = (f"<h2>{_e(mover['name'])} {verb} {abs(pct):.1f}% on the UnderAcademy Exchange</h2>"
                     f"<p>{_e(commentary)}</p>")

    ticker = "".join(
        f"<span>{_e(r['code'])} ${r['price']:.2f} <b class='{change(r)[1]}'>{reports.arrow(change(r)[0])} "
        f"{abs(change(r)[0]):.1f}%</b></span>" for r in rows)

    # Stories that reach the front page. The university pages carry everything, so nothing is lost to these limits.
    rank_of = {r["school_id"]: r["rank"] for r in rows}
    big = [e for e in events if e["kind"] in ("curse", "boon", "threshold", "decree")]
    policy_stories = [e for e in events if e["kind"] == "policy"]
    random.Random(day).shuffle(policy_stories)   # so the same early registrants don't take every slot
    leaks, leaked = [], set()
    for e in sorted((e for e in events if e["kind"] == "diary"), key=lambda e: rank_of.get(e["school_id"], 9999)):
        if e["school_id"] not in leaked:
            leaked.add(e["school_id"])
            leaks.append(e)
    recent = db.conn.execute("SELECT p.*, s.name AS school_name, s.code AS code FROM policies p "
                             "JOIN schools s ON s.id = p.school_id ORDER BY p.id DESC LIMIT 6").fetchall()

    def front(prefix: str, home: str) -> str:
        def link(sid: int, text: str) -> str:
            return f"<a href='{prefix}university/{quote(_slug(schools[sid]))}.html'>{_e(text)}</a>"

        def story(e):
            who = link(e["school_id"], schools[e["school_id"]]["name"]) if e["school_id"] in schools \
                else "The Conference"
            return f"<div class='story'><div class='who'>{who}</div>{_e(e['text'])}</div>"

        table = "".join(
            f"<tr><td class='num'>{r['rank']}</td><td>{link(r['school_id'], r['name'])} "
            f"<span class='tag'>#{_e(r['hashtag'])}</span>"
            f"<span class='move {move_class(r)}'>{_e(reports.rank_move(r))}</span></td><td>{_e(r['code'])}</td>"
            f"<td class='num'>${r['price']:.2f}</td>"
            f"<td class='num {change(r)[1]}'>{reports.arrow(change(r)[0])} {abs(change(r)[0]):.1f}%</td></tr>"
            for r in rows)
        stories = "".join(story(e) for e in (big + policy_stories)[:10]) or "<p>No news is good news. Or is it?</p>"
        diary_html = "".join(story(e) for e in leaks) or "<p>The diaries are quiet.</p>"
        register = "".join(f"<blockquote>{_e(reports_excerpt(p['text']))}<cite>{_e(p['code'])}-{p['number']}, "
                           f"{_e(p['kind'])}, {link(p['school_id'], p['school_name'])}</cite></blockquote>"
                           for p in recent) or "<p>No policies yet.</p>"
        days = "".join(f"<a href='{prefix}archive/day-{n}.html'>Day {n}</a>" for n in range(day - 1, 0, -1))
        back = f"<a href='{home}'>Latest edition</a>" if prefix else ""
        nav = f"<nav class='days'>{back}{'<span>Past editions:</span>' + days if days else ''}</nav>" \
            if back or days else ""
        return _shell("US Snooze & Whirled Retort",
                      "Rankings of the Big Digit Conference, as traded on the UnderAcademy Exchange.", home,
                      f"""{dateline}
<div class="ticker">{ticker or "<span>Markets closed</span>"}</div>
{nav}
<section class="lead">{lead_html}</section>
<div class="grid">
<section><h3>The Rankings</h3><table><thead><tr><th class="num">#</th><th>University</th><th>Ticker</th>
<th class="num">Price</th><th class="num">Day</th></tr></thead><tbody>{table}</tbody></table></section>
<section><h3>Top Stories</h3>{stories}</section>
</div>
<div class="grid">
<section><h3>Overheard in the Secret Diaries</h3>{diary_html}</section>
<section><h3>From the Policy Register</h3>{register}</section>
</div>""")

    round_names = {r["key"]: r["name"] for r in game.rounds()}

    def university(school) -> str:
        sid = school["id"]
        row = next((r for r in rows if r["school_id"] == sid), None)
        if row:
            pct, cls = change(row)
            standing = (f"<p class='standing'>Rank {row['rank']} of {len(rows)} · <b>{_e(school['code'])}</b> "
                        f"${row['price']:.2f} <b class='{cls}'>{reports.arrow(pct)} {abs(pct):.1f}%</b></p>")
        else:
            standing = f"<p class='standing'><b>{_e(school['code'])}</b> · Not yet listed. Trading opens at the next closing bell.</p>"
        facts = "".join(f"<div><dt>{label}</dt><dd>{_e(school[key])}</dd></div>"
                        for label, key in (("Motto", "motto"), ("Mascot", "mascot"), ("Colors", "colors"),
                                           ("Location", "location"), ("Specialties", "specialties"),
                                           ("Reputation", "reputation")) if school[key])
        characters = "".join(f"<div class='story'><div class='who'>{_e(c['name'])}"
                             f"{', ' + _e(c['role']) if c['role'] else ''}</div>"
                             f"<div class='body'>{_e(c['text'])}</div></div>" for c in db.characters(sid))
        policies = ""
        for p in reversed(db.policies(sid)):
            log = "".join(f"<li>Day {entry['day']}: {_e(entry['entry'])}</li>" for entry in db.policy_log(p["id"]))
            struck = " · <b class='down'>Struck Down</b>" if p["status"] != "Active" else ""
            policies += (f"<blockquote class='body'>{_e(p['text'])}<cite>{_e(school['code'])}-{p['number']}, "
                         f"{_e(p['kind'])}, {_e(round_names.get(p['round'], 'Before Round 1'))}{struck}</cite>"
                         f"{'<ul>' + log + '</ul>' if log else ''}</blockquote>")
        diaries = "".join(f"<div class='story'><div class='who'>{_e(d['character'])}"
                          f"{', ' + _e(d['role']) if d['role'] else ''} · "
                          f"{_e(round_names.get(d['round'], 'Before Round 1'))}</div>"
                          f"<div class='body'>{_e(d['text'])}</div></div>" for d in reversed(db.diaries(sid)))
        news = "".join(f"<div class='story'><div class='who'>Day {e['day']}</div>{_e(e['text'])}</div>"
                       for e in db.school_events(sid))
        tagline = school["motto"] or f"Trading as {school['code']} on the UnderAcademy Exchange."
        return _shell(f"{school['name']} · US Snooze & Whirled Retort", tagline, "../index.html",
                      f"""{dateline}
<nav class="days"><a href="../index.html">Back to the front page</a></nav>
<section class="lead"><h2>{_e(school['name'])}</h2>
<p class="tag">#{_e(school['hashtag'])}</p>{standing}{f'<dl class="facts">{facts}</dl>' if facts else ''}</section>
<section class="section"><h3>College Fair Pitch</h3><div class="body">{_e(parsing.pitch_text(school['pitch'])) or 'No pitch on file.'}</div></section>
<section class="section"><h3>Cast of Characters</h3>{characters or '<p>No one has come forward.</p>'}</section>
<div class="grid">
<section><h3>Secret Diaries</h3>{diaries or '<p>The diaries are quiet.</p>'}</section>
<section><h3>Policies</h3>{policies or '<p>No policies yet.</p>'}</section>
</div>
<section class="section"><h3>In the News</h3>{news or '<p>No news is good news. Or is it?</p>'}</section>""")

    data = json.dumps({"day": day, "round": rnd["name"] if rnd else None, "commentary": commentary,
                       "rankings": [{k: r[k] for k in ("rank", "name", "hashtag", "code", "price", "score")}
                                    for r in rows]}, indent=1)
    files = {"index.html": front("", "index.html"), "rankings.json": data,
             f"archive/day-{day}.html": front("../", "../index.html")}
    for school in schools.values():
        files[f"university/{_slug(school)}.html"] = university(school)
    return files


def move_class(r: dict) -> str:
    if not r.get("prev_rank"):
        return ""
    return "up" if r["prev_rank"] > r["rank"] else ("down" if r["prev_rank"] < r["rank"] else "")


def reports_excerpt(text: str, limit: int = 220) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "..."


def write_local(files: dict[str, str]) -> Path:
    for path, content in files.items():
        target = SITE_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return SITE_DIR / "index.html"


# ---- publishing to GitHub Pages -----------------------------------------------

def _api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(f"https://api.github.com/repos/{config.SITE_REPO}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {config.SITE_GITHUB_TOKEN}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "how-rank-is-your-college-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def _ensure_branch(branch: str) -> None:
    try:
        _api("GET", f"/git/ref/heads/{branch}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        default = _api("GET", "")["default_branch"]
        sha = _api("GET", f"/git/ref/heads/{default}")["object"]["sha"]
        _api("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})


def publish(files: dict[str, str]) -> str | None:
    """Uploads the site to the gh-pages branch as one commit. Returns the public URL, or None if not configured."""
    if not (config.SITE_GITHUB_TOKEN and config.SITE_REPO):
        return None
    branch = config.SITE_BRANCH
    _ensure_branch(branch)
    head = _api("GET", f"/git/ref/heads/{branch}")["object"]["sha"]
    base_tree = _api("GET", f"/git/commits/{head}")["tree"]["sha"]
    tree = _api("POST", "/git/trees", {"base_tree": base_tree, "tree": [
        {"path": path, "mode": "100644", "type": "blob", "content": content} for path, content in files.items()]})
    commit = _api("POST", "/git/commits", {"message": "Update the Retort", "tree": tree["sha"], "parents": [head]})
    _api("PATCH", f"/git/refs/heads/{branch}", {"sha": commit["sha"]})
    owner, repo = config.SITE_REPO.split("/", 1)
    return f"https://{owner}.github.io/{repo}/"
