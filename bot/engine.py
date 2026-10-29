"""The market close: turns a day's policies and diaries into stat changes, events and share prices.

Pure game logic with no Discord or database code, so it can be tested and simulated on its own.
Balance numbers live in data/tuning.json; flavor text lives in the other data/*.json files.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field

from .config import DATA_DIR

PUBLIC_STATS = ["prestige", "endowment", "enrollment", "satisfaction"]
HIDDEN_STATS = ["morale", "bureaucracy", "lawsuits", "chaos"]
ALL_STATS = PUBLIC_STATS + HIDDEN_STATS
STAT_LABELS = {
    "prestige": "Prestige", "endowment": "Endowment", "enrollment": "Enrollment",
    "satisfaction": "Student Satisfaction", "morale": "Faculty Morale",
    "bureaucracy": "Bureaucracy", "lawsuits": "Lawsuit Exposure", "chaos": "Chaos",
}


def load_data() -> dict:
    """Reads every data file. Called at each market close so edits take effect without a restart."""
    def read(name):
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    return {
        "tuning": read("tuning.json"),
        "domains": read("domains.json"),
        "hubris": read("hubris.json")["events"],
        "underdog": read("underdog.json")["events"],
        "symptoms": read("symptoms.json"),
        "rounds": read("rounds.json")["rounds"],
    }


# ---- inputs and outputs ---------------------------------------------------

@dataclass
class School:
    id: int
    name: str
    code: str
    mascot: str
    stats: dict


@dataclass
class NewPolicy:
    id: int
    school_id: int
    number: int
    title: str
    domain: str
    is_amendment: bool = False


@dataclass
class Diary:
    id: int
    school_id: int
    character: str
    role: str
    text: str


@dataclass
class Response:
    """A school's answer to the current round's challenge (for example, A.I. Capone's offer)."""
    id: int
    school_id: int
    text: str


@dataclass
class Interpretation:
    """What the AI (or anyone) decided a policy or a batch of diaries does."""
    effects: dict
    text: str


@dataclass
class AIResults:
    policies: dict[int, Interpretation] = field(default_factory=dict)   # by policy id
    diaries: dict[int, Interpretation] = field(default_factory=dict)    # by school id
    responses: dict[int, Interpretation] = field(default_factory=dict)  # by school id


@dataclass
class Event:
    school_id: int
    kind: str          # policy, diary, curse, boon, threshold, symptom, decree
    text: str
    policy_id: int | None = None


@dataclass
class DayResult:
    stats: dict[int, dict]
    events: list[Event]
    struck_down: list[int]               # policy ids
    market: list[dict]                   # one row per school, sorted by rank


# ---- helpers ---------------------------------------------------------------

def clamp_stats(stats: dict) -> None:
    for name in ALL_STATS:
        top = 10 if name == "lawsuits" else 100
        stats[name] = round(min(top, max(0.0, stats[name])), 2)


def score(stats: dict, tuning: dict) -> float:
    return round(sum(stats[k] * w for k, w in tuning["score_weights"].items()), 2)


def share_price(value: float, tuning: dict) -> float:
    return round(value * tuning["share_price_per_point"], 2)


def starting_stats(tuning: dict, rng: random.Random) -> dict:
    stats = dict(tuning["starting_stats"])
    jitter = tuning["starting_jitter"]
    for name in PUBLIC_STATS:
        stats[name] += rng.uniform(-jitter, jitter)
    clamp_stats(stats)
    return stats


def _apply(stats: dict, effects: dict, scale: float = 1.0, dampen: float = 0.0) -> None:
    """Adds effects to stats. Gains (not losses) shrink by `dampen`, which is how Bureaucracy slows things."""
    for name, amount in effects.items():
        if name not in stats:
            continue
        change = amount * scale
        if change > 0 and name in PUBLIC_STATS:
            change *= max(0.0, 1 - dampen)
        stats[name] += change


def _fill(template: str, school: School, rival: School | None, policy: str, rng: random.Random, data: dict) -> str:
    return template.format(
        school=school.name, mascot=school.mascot or "mascot", policy=policy,
        rival=rival.name if rival else "a rival university",
        department=rng.choice(data["domains"]["departments"]))


def _rival(school: School, schools: list[School], rng: random.Random) -> School | None:
    others = [s for s in schools if s.id != school.id]
    return rng.choice(others) if others else None


# ---- the market close -------------------------------------------------------

def run_day(schools: list[School], new_policies: list[NewPolicy], diaries: list[Diary],
            active_titles: dict[int, list[tuple[int, str]]], data: dict, rng: random.Random,
            ai: AIResults | None = None, responses: list[Response] | None = None) -> DayResult:
    """Runs one day.

    active_titles maps school id to (policy id, title) for every Active policy, used for
    accreditation visits and for flavor. `ai` overrides the tables wherever it has an answer.
    """
    tuning = data["tuning"]
    ai = ai or AIResults()
    by_id = {s.id: s for s in schools}
    stats = {s.id: dict(s.stats) for s in schools}
    events: list[Event] = []
    struck: list[int] = []

    # 1. New policies and amendments
    ptune = tuning["policy"]
    domains = data["domains"]["domains"]
    for p in new_policies:
        school = by_id.get(p.school_id)
        if school is None:
            continue
        st = stats[p.school_id]
        dampen = st["bureaucracy"] * ptune["bureaucracy_dampens_gains"]
        if p.id in ai.policies:
            interp = ai.policies[p.id]
            _apply(st, interp.effects, dampen=dampen)
            text = interp.text
        else:
            domain = domains.get(p.domain) or domains[next(iter(domains))]
            spread = ptune["roll_spread"] + st["chaos"] * ptune["chaos_widens_spread"]
            roll = rng.uniform(1 - spread, 1 + spread)   # a big spread can make a policy backfire
            _apply(st, domain["effects"], scale=roll, dampen=dampen)
            text = _fill(rng.choice(domain["templates"]), school, _rival(school, schools, rng), p.title, rng, data)
        st["bureaucracy"] += ptune["bureaucracy_per_amendment"] if p.is_amendment else ptune["bureaucracy_per_policy"]
        st["chaos"] += ptune["chaos_per_policy"]
        events.append(Event(p.school_id, "policy", text, policy_id=p.id))

    # 2. Secret Diaries as evidence
    dtune = tuning["diaries"]
    diaries_by_school: dict[int, list[Diary]] = {}
    for d in diaries:
        diaries_by_school.setdefault(d.school_id, []).append(d)
    for school_id, entries in diaries_by_school.items():
        if school_id not in stats:
            continue
        st = stats[school_id]
        st["prestige"] += min(len(entries) * dtune["buzz_per_entry"], dtune["max_buzz_per_day"])
        if school_id in ai.diaries:
            _apply(st, ai.diaries[school_id].effects)
            events.append(Event(school_id, "diary", ai.diaries[school_id].text))
        else:
            for d in entries:
                target = "morale" if _is_employee(d.role) else "satisfaction"
                st[target] += rng.uniform(-dtune["mood_swing"], dtune["mood_swing"])
            pick = rng.choice(entries)
            events.append(Event(school_id, "diary",
                                f"Sources close to the administration report a leaked diary entry from "
                                f"{pick.character or 'an anonymous diarist'}: \"{_excerpt(pick.text)}\""))

    # 2b. Answers to the round's challenge
    answered = set()
    for r in responses or []:
        if r.school_id not in stats or r.school_id in answered:
            continue
        answered.add(r.school_id)
        st = stats[r.school_id]
        if r.school_id in ai.responses:
            _apply(st, ai.responses[r.school_id].effects)
            events.append(Event(r.school_id, "challenge", ai.responses[r.school_id].text))
        else:
            gamble = rng.choice(PUBLIC_STATS)
            st[gamble] += rng.uniform(-4, 6)
            st["chaos"] += 1
            events.append(Event(r.school_id, "challenge",
                                f"{by_id[r.school_id].name} announced its answer: \"{_excerpt(r.text)}\" "
                                f"Analysts are watching its {STAT_LABELS[gamble]} closely."))

    # 3. Market drift; hidden stats drift back toward normal
    for school in schools:
        st = stats[school.id]
        for name in PUBLIC_STATS:
            st[name] += rng.gauss(0, tuning["daily_drift"] * (1 + st["chaos"] / 50))
        for name in ("morale", "chaos"):
            st[name] += (tuning["starting_stats"][name] - st[name]) * tuning["hidden_reversion"]
        clamp_stats(st)

    # 4. The Curse of Prestige and the underdog boons
    if len(schools) >= 3:
        events += _regression_to_the_mean(schools, stats, data, rng)

    # 5. Thresholds
    for school in schools:
        events += _thresholds(school, schools, stats, active_titles.get(school.id, []), struck, data, rng)

    # 6. Symptoms of hidden stats
    for school in schools:
        symptom = _symptom(stats[school.id], data, rng)
        if symptom:
            events.append(Event(school.id, "symptom", symptom))

    # 7. Prices and ranks
    for st in stats.values():
        clamp_stats(st)
    market = sorted(({"school_id": s.id, "score": score(stats[s.id], tuning)} for s in schools),
                    key=lambda r: r["score"], reverse=True)
    for rank, row in enumerate(market, start=1):
        row["rank"] = rank
        row["price"] = share_price(row["score"], tuning)
        row["stats_json"] = json.dumps(stats[row["school_id"]])
    return DayResult(stats=stats, events=events, struck_down=struck, market=market)


def _regression_to_the_mean(schools, stats, data, rng) -> list[Event]:
    tuning = data["tuning"]
    curse, boon = tuning["curse_of_prestige"], tuning["underdog"]
    scores = {s.id: score(stats[s.id], tuning) for s in schools}
    median, top, bottom = statistics.median(scores.values()), max(scores.values()), min(scores.values())
    ranked = sorted(schools, key=lambda s: scores[s.id])
    bottom_ids = {s.id for s in ranked[:max(1, round(len(schools) * boon["bottom_fraction"]))]}
    events = []
    for school in schools:
        sc = scores[school.id]
        if sc > median and top > median:
            lead = (sc - median) / (top - median)
            if rng.random() < curse["base_chance"] + curse["chance_per_lead"] * lead:
                severity = curse["base_severity"] + curse["severity_per_lead"] * lead
                events.append(_table_event(school, schools, stats, rng.choice(data["hubris"]), severity, "curse", rng))
        elif school.id in bottom_ids and median > bottom:
            deficit = (median - sc) / (median - bottom)
            if rng.random() < boon["base_chance"] + boon["chance_per_deficit"] * deficit:
                severity = boon["base_severity"] + boon["severity_per_deficit"] * deficit
                events.append(_table_event(school, schools, stats, rng.choice(data["underdog"]), severity, "boon", rng))
    return events


def _table_event(school, schools, stats, entry, severity, kind, rng) -> Event:
    rival = _rival(school, schools, rng)
    _apply(stats[school.id], entry.get("effects", {}), scale=severity)
    if rival and entry.get("rival_effects"):
        _apply(stats[rival.id], entry["rival_effects"], scale=severity)
    text = entry["text"].format(school=school.name, mascot=school.mascot or "mascot",
                                rival=rival.name if rival else "a rival university")
    if kind == "curse":
        text = "OFFICE OF REGRESSION TO THE MEAN: " + text
    return Event(school.id, kind, text)


def _thresholds(school, schools, stats, active, struck, data, rng) -> list[Event]:
    t = data["tuning"]["thresholds"]
    st = stats[school.id]
    events = []
    if st["satisfaction"] < t["occupation_below_satisfaction"]:
        st["prestige"] -= 3
        st["satisfaction"] += 6
        events.append(Event(school.id, "threshold",
                            f"Students have occupied the administration building at {school.name}. "
                            f"Demands include a refund and a human."))
    if st["morale"] < t["poaching_below_morale"]:
        rival = _rival(school, schools, rng)
        st["prestige"] -= 2
        st["morale"] += 8
        if rival:
            stats[rival.id]["prestige"] += 2
        events.append(Event(school.id, "threshold",
                            f"A wave of faculty has fled {school.name}"
                            + (f" for {rival.name}." if rival else ".")))
    if st["lawsuits"] >= t["accreditation_at_lawsuits"]:
        st["lawsuits"] -= 2
        st["prestige"] -= 2
        candidates = [(pid, title) for pid, title in active if pid not in struck]
        if candidates:
            pid, title = rng.choice(candidates)
            struck.append(pid)
            events.append(Event(school.id, "threshold",
                                f"An accreditation team visited {school.name} and struck down \"{title}.\"",
                                policy_id=pid))
        else:
            events.append(Event(school.id, "threshold",
                                f"An accreditation team visited {school.name} and found nothing to strike down, "
                                f"which they found suspicious."))
    if st["endowment"] < t["fire_sale_below_endowment"]:
        st["endowment"] += 15
        st["prestige"] -= 5
        dept = rng.choice(data["domains"]["departments"])
        events.append(Event(school.id, "threshold", f"{school.name} has held a fire sale. {dept[0].upper() + dept[1:]} "
                                                    f"was sold to the highest bidder."))
    clamp_stats(st)
    return events


def _symptom(st: dict, data: dict, rng: random.Random) -> str | None:
    symptoms = data["symptoms"]
    conditions = []
    if st["morale"] < 40:
        conditions.append("low_morale")
    if st["bureaucracy"] > 40:
        conditions.append("high_bureaucracy")
    if st["lawsuits"] >= 2:
        conditions.append("high_lawsuits")
    if st["chaos"] > 40:
        conditions.append("high_chaos")
    if st["satisfaction"] < 35:
        conditions.append("low_satisfaction")
    if not conditions:
        return None
    return rng.choice(symptoms[rng.choice(conditions)])


def _is_employee(role: str) -> bool:
    role = (role or "").lower()
    return any(word in role for word in ("prof", "faculty", "staff", "lecturer", "dean", "admin",
                                         "custodian", "groundskeeper", "coach", "librarian", "advisor"))


def _excerpt(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."
