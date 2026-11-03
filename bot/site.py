"""The US Snooze & Whirled Retort: a public web page of the rankings, rebuilt after every closing bell.

The page is always written to site/ in the project folder. If SITE_GITHUB_TOKEN and SITE_REPO are set,
it is also published to the repo's gh-pages branch, which GitHub Pages serves as a public website.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, reports

log = logging.getLogger(__name__)
SITE_DIR = config.ROOT / "site"

CSS = """
:root { --paper:#fbf8f1; --ink:#1d1b18; --muted:#6b645a; --rule:#d9d1c3; --accent:#8c1c13; --up:#1f6b3a; --down:#a1261b; --band:#f1ebdf; }
@media (prefers-color-scheme: dark) { :root { --paper:#17150f; --ink:#ece6da; --muted:#a59c8e; --rule:#3a352c; --accent:#e0705f; --up:#6fcf8f; --down:#ff8a7a; --band:#211e17; } }
* { box-sizing:border-box; }
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


def build(db, game) -> dict[str, str]:
    """Returns {path: content} for the site: index.html, rankings.json and a dated archive page."""
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

    table = "".join(
        f"<tr><td class='num'>{r['rank']}</td><td>{_e(r['name'])} <span class='tag'>#{_e(r['hashtag'])}</span>"
        f"<span class='move {move_class(r)}'>{_e(reports.rank_move(r))}</span></td><td>{_e(r['code'])}</td><td class='num'>${r['price']:.2f}</td>"
        f"<td class='num {change(r)[1]}'>{reports.arrow(change(r)[0])} {abs(change(r)[0]):.1f}%</td></tr>"
        for r in rows)

    def story(e):
        name = schools[e["school_id"]]["name"] if e["school_id"] in schools else "The Conference"
        return f"<div class='story'><div class='who'>{_e(name)}</div>{_e(e['text'])}</div>"
    big = [e for e in events if e["kind"] in ("curse", "boon", "threshold", "decree")]
    policy_stories = [e for e in events if e["kind"] == "policy"]
    stories = "".join(story(e) for e in (big + policy_stories)[:10]) or "<p>No news is good news. Or is it?</p>"
    leaks = "".join(story(e) for e in events if e["kind"] == "diary")[:6000] or "<p>The diaries are quiet.</p>"

    recent = db.conn.execute("SELECT p.*, s.name AS school_name, s.code AS code FROM policies p "
                             "JOIN schools s ON s.id = p.school_id ORDER BY p.id DESC LIMIT 6").fetchall()
    register = "".join(f"<blockquote>{_e(reports_excerpt(p['text']))}<cite>{_e(p['code'])}-{p['number']}, "
                       f"{_e(p['kind'])}, {_e(p['school_name'])}</cite></blockquote>" for p in recent) \
        or "<p>No policies yet.</p>"

    today = datetime.now()
    stamp = f"{today:%A, %B} {today.day}, {today.year}"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>US Snooze &amp; Whirled Retort</title>
<meta name="description" content="Rankings of the Big Digit Conference, as traded on the UnderAcademy Exchange.">
<style>{CSS}</style></head>
<body><div class="wrap">
<header class="masthead"><div class="over">The UnderAcademy Exchange presents</div>
<h1>US Snooze &amp; Whirled Retort</h1>
<div class="over">Big Digit Conference Rankings · How Rank is Your College?</div></header>
<div class="dateline"><span>{_e(stamp)}</span><span>Trading Day {day}</span><span>{_e(rnd['name'] if rnd else 'Preseason')}</span></div>
<div class="ticker">{ticker or "<span>Markets closed</span>"}</div>
<section class="lead">{lead_html}</section>
<div class="grid">
<section><h3>The Rankings</h3><table><thead><tr><th class="num">#</th><th>University</th><th>Ticker</th>
<th class="num">Price</th><th class="num">Day</th></tr></thead><tbody>{table}</tbody></table></section>
<section><h3>Top Stories</h3>{stories}</section>
</div>
<div class="grid">
<section><h3>Overheard in the Secret Diaries</h3>{leaks}</section>
<section><h3>From the Policy Register</h3>{register}</section>
</div>
<footer>A netprov. Any resemblance to real universities, living or dead, is purely coincidental.<br>
Share prices are not financial advice. Nothing is.</footer>
</div></body></html>"""
    data = json.dumps({"day": day, "round": rnd["name"] if rnd else None, "commentary": commentary,
                       "rankings": [{k: r[k] for k in ("rank", "name", "hashtag", "code", "price", "score")}
                                    for r in rows]}, indent=1)
    return {"index.html": page, "rankings.json": data, f"archive/day-{day}.html": page}


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
    """Uploads the site to the gh-pages branch. Returns the public URL, or None if not configured."""
    if not (config.SITE_GITHUB_TOKEN and config.SITE_REPO):
        return None
    branch = config.SITE_BRANCH
    _ensure_branch(branch)
    for path, content in files.items():
        sha = None
        try:
            sha = _api("GET", f"/contents/{path}?ref={branch}")["sha"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        body = {"message": f"Update {path}", "branch": branch,
                "content": base64.b64encode(content.encode()).decode()}
        if sha:
            body["sha"] = sha
        _api("PUT", f"/contents/{path}", body)
    owner, repo = config.SITE_REPO.split("/", 1)
    return f"https://{owner}.github.io/{repo}/"
