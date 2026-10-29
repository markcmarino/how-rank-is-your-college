"""Optional AI layer: Claude reads a school's Policy Register and diaries and decides the consequences.

The engine still does the math. Claude only proposes effects, which are clamped to the limits in
data/tuning.json, so the AI can't wreck the balance. If anything fails, the bot falls back to the
random tables for that school and keeps going.
"""

from __future__ import annotations

import json
import logging

from . import config
from .engine import ALL_STATS, STAT_LABELS, AIResults, Interpretation

log = logging.getLogger(__name__)

PREMISE = """You are the market engine for "How Rank is Your College?", a satirical netprov presented by the \
UnderAcademy Exchange. Players run fictional universities in a not-too-distant-future u-dys-meh-topia where \
the realities of AI in higher education come to absurd fruition. As administrators they pass AI policies; as \
students, staff and faculty they write Secret Diaries about living under those policies. Every university \
trades as a stock on the UnderAcademy Exchange and competes in the Big Digit Conference.

Your job: decide what the policies, diary evidence and challenge answers do to the university. Be funny in \
the deadpan voice of a financial wire service crossed with a campus newspaper. Consequences should follow \
the logic of the policy to an absurd but recognizable extreme: good intentions, bad outcomes, unintended \
side effects, and collisions between the school's own policies. Call back to older policies when they \
collide. Keep each consequence to one or two sentences. Never mention real universities or real people."""

STATS_HELP = """Stats (0 to 100; lawsuits 0 to 10). Public: prestige, endowment, enrollment, satisfaction \
(student satisfaction). Hidden: morale (faculty morale), bureaucracy, lawsuits (lawsuit exposure), chaos. \
Typical effects are between -5 and +5 per stat; reserve larger numbers for truly big moves."""

EFFECTS_SCHEMA = {
    "type": "object",
    "properties": {s: {"type": "number"} for s in ALL_STATS},
    "additionalProperties": False,
}

TOOL = {
    "name": "record_consequences",
    "description": "Record the consequences of today's activity at one university.",
    "input_schema": {
        "type": "object",
        "properties": {
            "policies": {
                "type": "array",
                "description": "One entry for each NEW policy listed, using its policy_id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "integer"},
                        "effects": EFFECTS_SCHEMA,
                        "consequence": {"type": "string"},
                    },
                    "required": ["policy_id", "effects", "consequence"],
                },
            },
            "diaries": {
                "type": "object",
                "description": "Only if diary entries were listed: what they reveal, and the effect on the school.",
                "properties": {"effects": EFFECTS_SCHEMA, "consequence": {"type": "string"}},
                "required": ["effects", "consequence"],
            },
            "challenge": {
                "type": "object",
                "description": "Only if a challenge answer was listed: the consequence of that answer.",
                "properties": {"effects": EFFECTS_SCHEMA, "consequence": {"type": "string"}},
                "required": ["effects", "consequence"],
            },
        },
        "required": ["policies"],
    },
}


def enabled(mode: str) -> bool:
    return mode == "ai" and bool(config.ANTHROPIC_API_KEY)


def _client():
    import anthropic
    return anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


def _clamp(effects: dict, limit: float, lawsuit_limit: float) -> dict:
    out = {}
    for name, value in (effects or {}).items():
        if name in ALL_STATS and isinstance(value, (int, float)):
            cap = lawsuit_limit if name == "lawsuits" else limit
            out[name] = max(-cap, min(cap, float(value)))
    return out


async def interpret_school(school: dict, stats: dict, register: list[dict], new_policy_ids: list[int],
                           diaries: list[dict], challenge: dict | None, answer: str | None,
                           tuning: dict) -> AIResults:
    """Asks Claude about one school. Returns an empty AIResults on any failure."""
    results = AIResults()
    limits = tuning["ai_limits"]
    briefing = {
        "university": school,
        "current_stats": {STAT_LABELS[k]: round(v, 1) for k, v in stats.items()},
        "policy_register": register,
        "new_policy_ids": new_policy_ids,
        "new_secret_diary_entries": diaries,
        "current_round_challenge": challenge,
        "challenge_answer": answer,
    }
    try:
        reply = await _client().messages.create(
            model=config.AI_MODEL,
            max_tokens=2000,
            system=PREMISE + "\n\n" + STATS_HELP,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "record_consequences"},
            messages=[{"role": "user", "content": "Today's briefing:\n" + json.dumps(briefing, indent=1)}],
        )
        data = next(b.input for b in reply.content if b.type == "tool_use")
    except Exception:
        log.exception("AI interpretation failed for %s; using tables", school.get("name"))
        return results

    wanted = set(new_policy_ids)
    for item in data.get("policies", []):
        pid = item.get("policy_id")
        if pid in wanted and item.get("consequence"):
            results.policies[pid] = Interpretation(
                _clamp(item.get("effects"), limits["per_policy"], limits["lawsuits_per_policy"]),
                item["consequence"])
    if diaries and data.get("diaries", {}).get("consequence"):
        d = data["diaries"]
        results.diaries[school["id"]] = Interpretation(
            _clamp(d.get("effects"), limits["diaries"], limits["lawsuits_per_policy"]), d["consequence"])
    if answer and data.get("challenge", {}).get("consequence"):
        c = data["challenge"]
        results.responses[school["id"]] = Interpretation(
            _clamp(c.get("effects"), limits["per_policy"], limits["lawsuits_per_policy"]), c["consequence"])
    return results


async def market_commentary(movers: list[dict]) -> str | None:
    """A few sentences of wire-service commentary on the day's biggest movers, citing their policies."""
    prompt = ("Write the UnderAcademy Exchange closing-bell commentary: 3 to 5 sentences in the voice of a "
              "deadpan financial wire service. Explain the biggest moves by citing each university's own "
              "policies by name and today's events. Use ticker symbols in parentheses. No headings, no lists, "
              "no em dashes.\n\nToday's movers:\n" + json.dumps(movers, indent=1))
    try:
        reply = await _client().messages.create(
            model=config.AI_MODEL, max_tokens=500, system=PREMISE,
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in reply.content if b.type == "text").strip() or None
    except Exception:
        log.exception("AI commentary failed; using template")
        return None
