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


def ticker(rows: list[dict]) -> str:
    """rows: code, price, prev_price. Sorted by price, high to low."""
    lines = ["UNDERACADEMY EXCHANGE · CLOSING PRICES", ""]
    for r in sorted(rows, key=lambda r: r["price"], reverse=True):
        prev = r.get("prev_price") or r["price"]
        pct = (r["price"] - prev) / prev * 100 if prev else 0.0
        lines.append(f"{r['code']:<6} ${r['price']:>8.2f}  {arrow(pct)} {abs(pct):5.1f}%")
    return "```\n" + "\n".join(lines) + "\n```"


def league_table(rows: list[dict], day: int) -> str:
    """rows: rank, name, code, score, prev_rank (or None)."""
    lines = [f"**Big Digit Conference Rankings · Day {day}**"]
    for r in sorted(rows, key=lambda r: r["rank"]):
        move = ""
        if r.get("prev_rank"):
            diff = r["prev_rank"] - r["rank"]
            move = f" ▲{diff}" if diff > 0 else (f" ▼{-diff}" if diff < 0 else "")
        lines.append(f"`{r['rank']:>2}.` **{r['name']}** ({r['code']}) · {r['score']:.1f}{move}")
    return "\n".join(lines)


def template_commentary(movers: list[dict], rng: random.Random) -> str:
    """Fallback closing-bell commentary when the AI is off. Cites each mover's own policies."""
    if not movers:
        return "Trading was quiet. Analysts blamed the weather, then the analysts."
    sentences = []
    for m in movers[:4]:
        up = m["change_pct"] >= 0
        cite = f"\"{m['policies'][0]}\"" if m["policies"] else "an absence of policy"
        verb = rng.choice(["rallied", "surged", "climbed", "inched up"]) if up else \
            rng.choice(["slid", "tumbled", "sagged", "fell"])
        reason = rng.choice([
            f"as investors digested {cite}",
            f"on renewed confidence in {cite}",
            f"after traders reread {cite}",
            f"amid fresh questions about {cite}",
            f"while {cite} continued to be {cite}",
        ])
        sentences.append(f"{m['name']} ({m['code']}) {verb} {abs(m['change_pct']):.1f}% {reason}.")
    return " ".join(sentences)


def school_report(school, day: int, events: list, stats: dict) -> str:
    lines = [f"**{school['name']} · Daily Report · Day {day}**"]
    if events:
        lines += [f"• {e['text']}" for e in events]
    else:
        lines.append("• A quiet day. The Board of Trustees is suspicious.")
    lines.append("")
    lines.append(f"Prestige {stats['prestige']:.0f} · Endowment {money(stats['endowment'])} · "
                 f"Enrollment {stats['enrollment']:.0f} · Student Satisfaction {stats['satisfaction']:.0f}")
    return "\n".join(lines)


def policy_card(policy, code: str, amended_from: int | None = None) -> str:
    head = f"**{code}-{policy['number']}: {policy['title']}**  _({policy['domain']})_"
    if amended_from:
        head += f"\n_Amends {code}-{amended_from}_"
    parts = [head, policy["text"]]
    if policy["pros"]:
        parts.append(f"**Pros:** {policy['pros']}")
    if policy["cons"]:
        parts.append(f"**Cons:** {policy['cons']}")
    return "\n".join(parts)


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
