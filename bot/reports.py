"""Text formatting for Discord: the ticker, the league table, school reports and policy cards."""

from __future__ import annotations

import random

DISCORD_LIMIT = 1900


def money(endowment: float) -> str:
    """Endowment is stored as a 0-100 index; shown in Fake Dollars."""
    return f"${endowment * 12.5:,.1f}M"


def arrow(change: float) -> str:
    if change > 0.005:
        return "▲"
    if change < -0.005:
        return "▼"
    return "■"


def pct_change(price: float, prev: float | None) -> float:
    return (price - prev) / prev * 100 if prev else 0.0


def ticker(rows: list[dict]) -> str:
    """rows: code, price, prev_price. Sorted by price, high to low."""
    lines = ["UNDERACADEMY EXCHANGE · CLOSING PRICES", ""]
    for r in sorted(rows, key=lambda r: r["price"], reverse=True):
        pct = pct_change(r["price"], r.get("prev_price"))
        lines.append(f"{r['code']:<6} ${r['price']:>8.2f}  {arrow(pct)} {abs(pct):5.1f}%")
    return "```\n" + "\n".join(lines) + "\n```"


def league_table(rows: list[dict], day: int) -> str:
    """rows: rank, name, code, score, prev_rank (or None)."""
    lines = [f"**Big Digit Conference Rankings · Day {day}**"]
    for r in sorted(rows, key=lambda r: r["rank"]):
        lines.append(f"`{r['rank']:>2}.` **{r['name']}** ({r['code']}) · {r['score']:.1f}{rank_move(r)}")
    return "\n".join(lines)


def rank_move(r: dict) -> str:
    if not r.get("prev_rank"):
        return ""
    diff = r["prev_rank"] - r["rank"]
    return f" ▲{diff}" if diff > 0 else (f" ▼{-diff}" if diff < 0 else "")


def template_commentary(movers: list[dict], rng: random.Random, phrases: dict) -> str:
    """Closing-bell commentary from the Market Commentary table. Cites each mover's own policies."""
    if not movers:
        return rng.choice(phrases.get("quiet_day") or ["Trading was quiet."])
    up = phrases.get("up_verb") or ["rose"]
    down = phrases.get("down_verb") or ["fell"]
    reasons = phrases.get("reason") or ["on news about {policy}"]
    sentences = []
    for m in movers[:4]:
        cite = f"\"{m['policies'][-1]}\"" if m["policies"] else "an absence of policy"
        verb = rng.choice(up if m["change_pct"] >= 0 else down)
        reason = rng.choice(reasons).replace("{policy}", cite)
        sentences.append(f"{m['name']} ({m['code']}) {verb} {abs(m['change_pct']):.1f}% {reason}.")
    return " ".join(sentences)


def school_report(school, day: int, events: list, stats: dict) -> str:
    lines = [f"**{school['name']}** (#{school['hashtag']} · {school['code']}) · Day {day}"]
    if events:
        lines += [f"• {e['text']}" for e in events]
    else:
        lines.append("• A quiet day. The Board of Trustees is suspicious.")
    lines.append(f"Prestige {stats['prestige']:.0f} · Endowment {money(stats['endowment'])} · "
                 f"Enrollment {stats['enrollment']:.0f} · Student Satisfaction {stats['satisfaction']:.0f}")
    return "\n".join(lines)


def policy_card(policy, school) -> str:
    head = f"**{school['code']}-{policy['number']}** · {policy['kind']} · _{policy['domain'] or 'Unfiled'}_"
    return f"{head}\n{policy['text']}\n_Posted by {policy['author_name'] or 'unknown'} · Status: {policy['status']}_"


def split(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Splits long text into Discord-sized messages on line breaks."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
