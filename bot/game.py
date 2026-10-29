"""Connects the database to the engine: runs a market close and saves the results."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from . import ai, reports
from .db import Database
from .engine import (AIResults, Diary, DayResult, NewPolicy, Response, School, load_data, run_day,
                     starting_stats)


@dataclass
class CloseReport:
    """Everything a market close produced, ready to save and post."""
    day: int
    result: DayResult
    ticker: str
    table: str
    commentary: str
    school_reports: dict[int, str] = field(default_factory=dict)
    processed: dict[str, list[int]] = field(default_factory=dict)


class Game:
    def __init__(self, db: Database, rng: random.Random | None = None):
        self.db = db
        self.rng = rng or random.Random()
        self.pending: CloseReport | None = None

    # ---- settings ------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.db.get("mode", "ai")

    def current_round(self) -> dict | None:
        key = self.db.get("round")
        return next((r for r in load_data()["rounds"] if r["key"] == key), None)

    def new_school_stats(self) -> dict:
        return starting_stats(load_data()["tuning"], self.rng)

    # ---- the market close ------------------------------------------------
    async def close(self) -> CloseReport:
        """Computes the next day without saving it. Call commit() to make it official."""
        db, data = self.db, load_data()
        day = db.day + 1
        rows = db.schools()
        stats = db.all_stats()
        schools = [School(r["id"], r["name"], r["code"], r["mascot"], stats[r["id"]]) for r in rows]
        by_id = {r["id"]: r for r in rows}

        new_rows = db.unprocessed_policies()
        new_policies = [NewPolicy(p["id"], p["school_id"], p["number"], p["title"], p["domain"],
                                  is_amendment=p["parent_id"] is not None) for p in new_rows]
        diary_rows = db.diaries(unprocessed_only=True)
        diaries = [Diary(d["id"], d["school_id"], d["character"], d["role"], d["text"]) for d in diary_rows]
        response_rows = db.responses(unprocessed_only=True)
        responses = [Response(r["id"], r["school_id"], r["text"]) for r in response_rows]
        active = {s.id: [(p["id"], p["title"]) for p in db.policies(s.id, "Active")] for s in schools}

        ai_results = AIResults()
        if ai.enabled(self.mode):
            ai_results = await self._ask_ai(schools, by_id, new_rows, diary_rows, response_rows, data)

        result = run_day(schools, new_policies, diaries, active, data, self.rng, ai_results, responses)

        # Ranking report
        prev = db.snapshot(day - 1)
        market_rows = []
        for row in result.market:
            s = by_id[row["school_id"]]
            p = prev.get(row["school_id"])
            market_rows.append({**row, "name": s["name"], "code": s["code"],
                                "prev_price": p["price"] if p else None,
                                "prev_rank": p["rank"] if p else None})
        movers = self._movers(market_rows, result)
        commentary = None
        if ai.enabled(self.mode) and movers:
            commentary = await ai.market_commentary(movers)
        commentary = commentary or reports.template_commentary(movers, self.rng)

        events_by_school: dict[int, list] = {}
        for e in db.events(day):   # Mark's decrees since the last close
            events_by_school.setdefault(e["school_id"], []).append({"text": e["text"]})
        for e in result.events:
            events_by_school.setdefault(e.school_id, []).append({"text": e.text})
        school_reports = {s.id: reports.school_report(by_id[s.id], day, events_by_school.get(s.id, []),
                                                      result.stats[s.id]) for s in schools}

        report = CloseReport(
            day=day, result=result, ticker=reports.ticker(market_rows),
            table=reports.league_table(market_rows, day), commentary=commentary,
            school_reports=school_reports,
            processed={"policies": [p["id"] for p in new_rows], "diaries": [d["id"] for d in diary_rows],
                       "responses": [r["id"] for r in response_rows]})
        self.pending = report
        return report

    def commit(self, report: CloseReport) -> None:
        """Saves a close: new stats, events, policy log, struck-down policies, prices."""
        db, day, result = self.db, report.day, report.result
        db.save_stats(result.stats)
        for e in result.events:
            db.add_event(day, e.school_id, e.kind, e.text)
            if e.policy_id:
                db.log_policy(e.policy_id, day, e.text)
        for pid in result.struck_down:
            db.set_policy_status(pid, "Struck Down")
        db.save_snapshot(day, result.market)
        for table, ids in report.processed.items():
            db.mark_processed(table, ids)
        db.set("day", day)
        self.pending = None

    async def _ask_ai(self, schools, by_id, new_rows, diary_rows, response_rows, data) -> AIResults:
        combined = AIResults()
        challenge = self.current_round()
        for s in schools:
            mine = [p for p in new_rows if p["school_id"] == s.id]
            my_diaries = [d for d in diary_rows if d["school_id"] == s.id]
            my_answer = next((r["text"] for r in response_rows if r["school_id"] == s.id), None)
            if not (mine or my_diaries or my_answer):
                continue
            row = by_id[s.id]
            profile = {k: row[k] for k in ("id", "name", "code", "location", "specialties", "reputation",
                                           "colors", "mascot", "motto", "pitch")}
            register = [{"policy_id": p["id"], "label": f"{row['code']}-{p['number']}", "title": p["title"],
                         "text": p["text"], "pros": p["pros"], "cons": p["cons"], "domain": p["domain"],
                         "status": p["status"],
                         "amends": p["parent_id"]} for p in self.db.policies(s.id)]
            diaries = [{"character": d["character"], "role": d["role"], "entry": d["text"]} for d in my_diaries]
            got = await ai.interpret_school(
                profile, s.stats, register, [p["id"] for p in mine], diaries,
                {"name": challenge["name"], "challenge": challenge["challenge"]} if challenge else None,
                my_answer, data["tuning"])
            combined.policies.update(got.policies)
            combined.diaries.update(got.diaries)
            combined.responses.update(got.responses)
        return combined

    def _movers(self, market_rows: list[dict], result: DayResult) -> list[dict]:
        movers = []
        for r in market_rows:
            if not r["prev_price"]:
                continue
            change = (r["price"] - r["prev_price"]) / r["prev_price"] * 100
            policies = [p["title"] for p in self.db.policies(r["school_id"], "Active")]
            events = [e.text for e in result.events if e.school_id == r["school_id"]]
            movers.append({"name": r["name"], "code": r["code"], "change_pct": round(change, 1),
                           "policies": policies[-5:], "todays_events": events[:4]})
        movers.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
        return movers[:6]

    # ---- admin tools ----------------------------------------------------
    def decree(self, text: str, school_id: int | None, stat: str | None, amount: float) -> None:
        """Mark's custom event. Applies immediately; appears in the next report."""
        stats = self.db.all_stats()
        targets = [school_id] if school_id else list(stats)
        for sid in targets:
            if stat:
                stats[sid][stat] = stats[sid][stat] + amount
                top = 10 if stat == "lawsuits" else 100
                stats[sid][stat] = max(0, min(top, stats[sid][stat]))
            self.db.add_event(self.db.day + 1, sid, "decree", text)
        self.db.save_stats(stats)

    def export_statutes(self) -> str:
        """The Collected Statutes of the Big Digit Conference, as Markdown."""
        db = self.db
        lines = ["# The Collected Statutes of the Big Digit Conference", "",
                 "_As recorded by the UnderAcademy Exchange._", ""]
        final = db.snapshot(db.day)
        for s in sorted(db.schools(), key=lambda s: final[s["id"]]["rank"] if s["id"] in final else 999):
            snap = final.get(s["id"])
            lines.append(f"## {s['name']} ({s['code']})")
            meta = [f"**{k.title()}:** {s[k]}" for k in ("motto", "location", "specialties", "colors", "mascot")
                    if s[k]]
            if snap:
                meta.append(f"**Final share price:** ${snap['price']:.2f} (rank {snap['rank']})")
            lines += meta + [""]
            if s["pitch"]:
                lines += ["### College Fair Pitch", s["pitch"], ""]
            lines.append("### Policies")
            for p in db.policies(s["id"]):
                lines.append(f"**{s['code']}-{p['number']}: {p['title']}** ({p['status']}, {p['domain']})")
                lines.append(p["text"])
                if p["pros"]:
                    lines.append(f"Pros: {p['pros']}")
                if p["cons"]:
                    lines.append(f"Cons: {p['cons']}")
                for entry in db.policy_log(p["id"]):
                    lines.append(f"- Day {entry['day']}: {entry['entry']}")
                lines.append("")
            entries = db.diaries(s["id"])
            if entries:
                lines.append("### Secret Diaries")
                for d in entries:
                    lines.append(f"**#{d['character']} #{d['role']}**")
                    lines.append(d["text"])
                    lines.append("")
        return "\n".join(lines)

    def history_json(self) -> str:
        rows = self.db.conn.execute("SELECT * FROM snapshots ORDER BY day, rank").fetchall()
        return json.dumps([dict(r) for r in rows], indent=1)
