"""The US Snooze & Whirled Retort: a public web page of the rankings, rebuilt after every closing bell.

The page is always written to site/ in the project folder. If SITE_GITHUB_TOKEN and SITE_REPO are set,
it is also published to the repo's gh-pages branch, which GitHub Pages serves as a public website.
"""

from __future__ import annotations

import html
import json
import logging
import math
import random
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote as quote_url

from . import config, parsing, reports

log = logging.getLogger(__name__)
REVIEW_EDITIONS = 13   # nights in the game, so every university is reviewed at least once
SITE_DIR = config.ROOT / "site"

CSS = """
:root { --paper:#fbf8f1; --ink:#1d1b18; --muted:#6b645a; --rule:#d9d1c3; --accent:#8c1c13; --up:#1f6b3a; --down:#a1261b; --band:#f1ebdf;
  --s0:#2a78d6; --s1:#eb6834; --s2:#1baf7a; --s3:#eda100; --s4:#e87ba4; --s5:#008300; --s6:#6250d6; --s7:#e34948; --pack:#d9d1c3; }
@media (prefers-color-scheme: dark) { :root { --paper:#17150f; --ink:#ece6da; --muted:#a59c8e; --rule:#3a352c; --accent:#e0705f; --up:#6fcf8f; --down:#ff8a7a; --band:#211e17;
  --s0:#3987e5; --s1:#d95926; --s2:#199e70; --s3:#c98500; --s4:#d55181; --s5:#008300; --s6:#9085e9; --s7:#e66767; --pack:#3a352c; } }
* { box-sizing:border-box; }
.chart { padding:20px 0 16px; border-bottom:1px solid var(--rule); }
.chart h3 { margin-bottom:4px; }
.chart .note { margin:0 0 8px; font:13px/1.4 system-ui, sans-serif; color:var(--muted); }
.chart svg { display:block; width:100%; height:auto; }
.chart text { font:14px system-ui, sans-serif; fill:var(--muted); }
.chart text.end { fill:var(--ink); font-weight:700; }
.chart .grid-line { stroke:var(--rule); stroke-width:1; }
.chart .series { fill:none; stroke-width:2.5; stroke-linejoin:round; stroke-linecap:round; }
.chart .pack { fill:none; stroke:var(--pack); stroke-width:1; stroke-linejoin:round; }
.chart .hit { fill:transparent; }
.chart .dot { stroke:var(--paper); stroke-width:2; }
.trend { width:72px; padding-left:8px; padding-right:8px; }
.trend svg { display:block; width:64px; height:20px; }
.trend polyline, .review polyline { fill:none; stroke:var(--muted); stroke-width:1.5; stroke-linejoin:round; stroke-linecap:round; }
@media (max-width:560px), (min-width:861px) and (max-width:959px) { .trend { display:none; } }
.reviews { padding:20px 0 16px; border-bottom:1px solid var(--rule); }
.reviews .note { margin:0 0 12px; font:13px/1.4 system-ui, sans-serif; color:var(--muted); }
.review-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px 32px; }
.review { min-width:0; overflow-wrap:anywhere; }
.review h4 { margin:0; font-size:21px; line-height:1.2; }
.review .standing { display:flex; align-items:center; flex-wrap:wrap; gap:4px 12px; margin:6px 0 10px !important; font-size:14px; }
.review .standing svg { width:80px; height:25px; flex:none; }
.review blockquote { margin:0 0 8px; }
.review .more { font:13px/1.4 system-ui, sans-serif; }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; margin-top:8px; font:13px/1.4 system-ui, sans-serif; }
.legend i { display:inline-block; width:14px; height:3px; border-radius:2px; margin-right:6px; vertical-align:middle; }
@media (max-width:560px) { .chart text { font-size:24px; } }
.lead .chart { padding:14px 0 0; border-bottom:0; max-width:520px; }
a { color:var(--accent); text-underline-offset:2px; }
a:hover { text-decoration-thickness:2px; }
td a, .who a { font-weight:700; }
.schools { border-bottom:1px solid var(--rule); padding:8px 0; font:14px/1.4 system-ui, sans-serif; }
.schools summary { cursor:pointer; font-weight:700; color:var(--accent); }
.schools div { display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:6px 16px; padding-top:10px; }
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
@media (max-width:860px) { .grid { grid-template-columns:1fr; } }
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


def _nice_ticks(low: float, high: float) -> list[float]:
    """Three to five round prices spanning the range."""
    span = max(high - low, 1)
    step = next((s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if span / s <= 4), 1000)
    tick = (low // step) * step
    ticks = []
    while tick < high + step:
        ticks.append(tick)
        tick += step
    return ticks


def _price_chart(series: list[dict], pack: list[list[tuple[int, float]]], day: int, label: str) -> str:
    """An inline line chart. series: {code, color, points}. pack: other schools, drawn faintly behind."""
    width, height = 640, 240
    left, right, top, bottom = 62, 112, 12, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    prices = [p for s in series for _, p in s["points"]] + [p for points in pack for _, p in points]
    ticks = _nice_ticks(min(prices), max(prices))
    low, high = ticks[0], ticks[-1]

    def x(d):
        return left + plot_w * (d - 1) / max(day - 1, 1)

    def y(price):
        return top + plot_h * (high - price) / (high - low)

    def line(points):
        return " ".join(f"{x(d):.1f},{y(p):.1f}" for d, p in points)

    parts = []
    for tick in ticks:
        parts.append(f"<line class='grid-line' x1='{left}' x2='{width - right}' y1='{y(tick):.1f}' y2='{y(tick):.1f}'/>"
                     f"<text x='{left - 8}' y='{y(tick) + 5:.1f}' text-anchor='end'>${tick:.0f}</text>")
    every = max(1, (day - 1 + 4) // 5)
    days = [d for d in range(1, day + 1) if (d - 1) % every == 0]
    for d in days:
        parts.append(f"<text x='{x(d):.1f}' y='{height - 8}' text-anchor='middle'>{'Day ' if d == 1 else ''}{d}</text>")
    parts += [f"<polyline class='pack' points='{line(points)}'/>" for points in pack if len(points) > 1]
    for s in reversed(series):
        if len(s["points"]) > 1:
            parts.append(f"<polyline class='series' style='stroke:var(--s{s['color']})' points='{line(s['points'])}'/>")
    # Direct labels at the line ends, nudged apart so tickers don't collide
    ends = sorted(series, key=lambda s: y(s["points"][-1][1]))
    label_y, previous = {}, top - 20
    for s in ends:
        previous = max(y(s["points"][-1][1]) + 5, previous + 24)
        label_y[s["code"]] = previous
    overflow = max(0, previous - (height - bottom + 5))
    for s in series:
        d, p = s["points"][-1]
        text_y = label_y[s["code"]] - overflow
        parts.append(f"<line style='stroke:var(--s{s['color']})' stroke-width='1.5' x1='{x(d) + 4:.1f}' y1='{y(p):.1f}' "
                     f"x2='{x(d) + 24:.1f}' y2='{text_y - 5:.1f}'/>"
                     f"<circle class='dot' style='fill:var(--s{s['color']})' cx='{x(d):.1f}' cy='{y(p):.1f}' r='5'/>"
                     f"<text class='end' x='{x(d) + 28:.1f}' y='{text_y:.1f}'>{_e(s['code'])}</text>")
        for d, p in s["points"]:
            parts.append(f"<circle class='hit' cx='{x(d):.1f}' cy='{y(p):.1f}' r='9'>"
                         f"<title>{_e(s['code'])}, Day {d}: ${p:.2f}</title></circle>")
    return (f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{_e(label)}'>{''.join(parts)}</svg>")


def _trend(points: list[tuple[int, float]], cls: str, code: str) -> str:
    """A tiny price line for the rankings table, scaled to that school's own range."""
    if len(points) < 2:
        return ""
    prices = [p for _, p in points]
    low, span = min(prices), (max(prices) - min(prices)) or 1
    first, last = points[0][0], points[-1][0]

    def x(d):
        return 2 + 58 * (d - first) / max(last - first, 1)

    def y(price):
        return 17 - 14 * (price - low) / span

    line = " ".join(f"{x(d):.1f},{y(p):.1f}" for d, p in points)
    color = {"up": "var(--up)", "down": "var(--down)"}.get(cls, "var(--muted)")
    return (f"<svg viewBox='0 0 64 20' role='img' aria-label='{_e(code)} price trend'><polyline points='{line}'/>"
            f"<circle cx='{x(last):.1f}' cy='{y(prices[-1]):.1f}' r='2.5' style='fill:{color}'/></svg>")


def _under_review(db, day: int, school_ids: list[int]) -> list[int]:
    """The universities reviewed in this edition: whoever has waited longest, so everyone gets a turn before
    anyone gets a second. The choice is saved, so rebuilding an edition doesn't change it."""
    saved = db.get(f"under_review_{day}")
    if saved is not None:
        return [sid for sid in json.loads(saved) if sid in school_ids]
    last_seen: dict[int, int] = {}
    for earlier in range(1, day):
        for sid in json.loads(db.get(f"under_review_{earlier}") or "[]"):
            last_seen[sid] = earlier
    per_edition = max(2, math.ceil(len(school_ids) / REVIEW_EDITIONS))
    picks = sorted(school_ids, key=lambda sid: (last_seen.get(sid, 0), sid))[:per_edition]
    db.set(f"under_review_{day}", json.dumps(picks))
    return picks


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

    # The chart: the top five by today's rank, the rest as faint context. Colors follow the university.
    history = db.price_history()
    top_rows = [r for r in rows if r["school_id"] in history][:5]
    used: set[int] = set()
    series = []
    for r in top_rows:
        color = next(c % 8 for c in range(r["school_id"] - 1, r["school_id"] + 7) if c % 8 not in used)
        used.add(color)
        series.append({"school_id": r["school_id"], "code": r["code"], "name": r["name"], "color": color,
                       "points": history[r["school_id"]]})
    chart_svg = ""
    if day > 1 and series:
        top_ids = {r["school_id"] for r in top_rows}
        pack = [points for sid, points in history.items() if sid not in top_ids]
        leader = series[0]
        chart_svg = _price_chart(series, pack, day, f"Share prices by trading day. {leader['name']} leads at "
                                                    f"${leader['points'][-1][1]:.2f} on Day {day}.")

    reviewed = _under_review(db, day, [r["school_id"] for r in rows]) if rows else []

    def front(prefix: str, home: str) -> str:
        def link(sid: int, text: str) -> str:
            return f"<a href='{prefix}university/{quote_url(_slug(schools[sid]))}.html'>{_e(text)}</a>"

        def story(e):
            who = link(e["school_id"], schools[e["school_id"]]["name"]) if e["school_id"] in schools \
                else "The Conference"
            return f"<div class='story'><div class='who'>{who}</div>{_e(e['text'])}</div>"

        def trend_cell(r):
            return f"<td class='trend'>{_trend(history.get(r['school_id'], []), change(r)[1], r['code'])}</td>" if day > 1 else ""

        table = "".join(
            f"<tr><td class='num'>{r['rank']}</td><td>{link(r['school_id'], r['name'])} "
            f"<span class='tag'>#{_e(r['hashtag'])}</span>"
            f"<span class='move {move_class(r)}'>{_e(reports.rank_move(r))}</span></td><td>{_e(r['code'])}</td>"
            f"{trend_cell(r)}<td class='num'>${r['price']:.2f}</td>"
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
        def review(sid: int) -> str:
            school, row = schools[sid], next(r for r in rows if r["school_id"] == sid)
            pct, cls = change(row)
            diary = (db.diaries(sid) or [None])[-1]
            if diary:
                who = f"{diary['character']}, {diary['role']}" if diary["role"] else diary["character"]
                quote = f"<blockquote>{_e(reports_excerpt(diary['text']))}<cite>{_e(who)}, in a Secret Diary</cite></blockquote>"
            elif db.policies(sid):
                policy = db.policies(sid)[-1]
                quote = (f"<blockquote>{_e(reports_excerpt(policy['text']))}<cite>{_e(school['code'])}-{policy['number']}, "
                         f"{_e(policy['kind'])}</cite></blockquote>")
            else:
                quote = f"<blockquote>{_e(reports_excerpt(parsing.pitch_text(school['pitch'])))}<cite>College Fair Pitch</cite></blockquote>"
            motto = f"<p class='tag'>{_e(school['motto'])}</p>" if school["motto"] else ""
            return (f"<article class='review'><h4>{link(sid, school['name'])}</h4>{motto}<p class='standing'>"
                    f"<span>Rank {row['rank']} of {len(rows)} · ${row['price']:.2f} <b class='{cls}'>{reports.arrow(pct)} "
                    f"{abs(pct):.1f}%</b></span>{_trend(history.get(sid, []), cls, school['code'])}</p>{quote}"
                    f"<a class='more' href='{prefix}university/{quote_url(_slug(school))}.html'>Read the full file</a></article>")

        reviews = ""
        if reviewed:
            reviews = ("<section class='reviews'><h3>University Under Review</h3><p class='note'>Each edition, the Retort's "
                       "auditors visit another corner of the Conference. Every university's turn will come.</p>"
                       f"<div class='review-grid'>{''.join(review(sid) for sid in reviewed)}</div></section>")
        title = "The Exchange: Top Five" if len(rows) > 5 else "The Exchange"
        if chart_svg:
            note = "Share prices by trading day." + (" Gray lines: the rest of the Conference." if len(rows) > 5 else "")
            legend = "".join(f"<span><i style='background:var(--s{s['color']})'></i>"
                             f"{link(s['school_id'], s['name'])}</span>" for s in series) if len(series) > 1 else ""
            chart = (f"<section class='chart'><h3>{title}</h3><p class='note'>{note}</p>{chart_svg}"
                     f"{f'<div class=legend>{legend}</div>' if legend else ''}</section>")
        elif rows:
            chart = (f"<section class='chart'><h3>{title}</h3>"
                     "<p class='note'>Insufficient data. Analysts remain confident.</p></section>")
        else:
            chart = ""
        return _shell("US Snooze & Whirled Retort",
                      "Rankings of the Big Digit Conference, as traded on the UnderAcademy Exchange.", home,
                      f"""{dateline}
<div class="ticker">{ticker or "<span>Markets closed</span>"}</div>
{nav}
{school_menu(prefix)}
{chart}
<section class="lead">{lead_html}</section>
{reviews}
<div class="grid">
<section><h3>The Rankings</h3><table><thead><tr><th class="num">#</th><th>University</th><th>Ticker</th>
{'<th class="trend">Trend</th>' if day > 1 else ''}<th class="num">Price</th><th class="num">Day</th></tr></thead><tbody>{table}</tbody></table></section>
<section><h3>Top Stories</h3>{stories}</section>
</div>
<div class="grid">
<section><h3>Overheard in the Secret Diaries</h3>{diary_html}</section>
<section><h3>From the Policy Register</h3>{register}</section>
</div>""")

    def school_menu(prefix: str) -> str:
        links = "".join(f"<a href='{prefix}university/{quote_url(_slug(s))}.html'>{_e(s['name'])}</a>"
                        for s in sorted(schools.values(), key=lambda s: s["name"].lower()))
        return f"<details class='schools'><summary>All universities ({len(schools)})</summary><div>{links}</div></details>"

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
        own = history.get(sid, [])
        price_line = ""
        if day > 1 and len(own) > 1:
            price_line = ("<div class='chart'>" + _price_chart(
                [{"code": school["code"], "color": 0, "points": own}], [], day,
                f"{school['name']} share price by trading day, now ${own[-1][1]:.2f}.") + "</div>")
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
{school_menu("../")}
<section class="lead"><h2>{_e(school['name'])}</h2>
<p class="tag">#{_e(school['hashtag'])}</p>{standing}{price_line}{f'<dl class="facts">{facts}</dl>' if facts else ''}</section>
<section class="section"><h3>College Fair Pitch</h3><div class="body">{_e(parsing.pitch_text(school['pitch'])) or 'No pitch on file.'}</div></section>
<section class="section"><h3>College Characters</h3>{characters or '<p>No one has come forward.</p>'}</section>
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
