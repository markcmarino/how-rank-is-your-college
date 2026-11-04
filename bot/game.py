"""Game logic between Discord and the engine: filing posts, rounds, the market close, the finale, exports."""

from __future__ import annotations

import csv
import io
import json
import random
from dataclasses import dataclass, field
from datetime import date

from . import ai, config, parsing, reports
from .db import Database
from .engine import (AIResults, Diary, DayResult, NewPolicy, School, final_audit, load_data, run_day,
                     starting_stats)


@dataclass
class CloseReport:
    """Everything a market close produced, ready to save and post."""
    day: int
    result: DayResult
    market_rows: list[dict]
    ticker: str
    table: str
    commentary: str
    school_reports: dict[int, str] = field(default_factory=dict)
    processed: dict[str, list[int]] = field(default_factory=dict)


@dataclass
class Filed:
    """What happened when the bot read a post."""
    ok: bool
    message: str = ""          # reply to post in the channel, if any
    school: object = None
    new_school: bool = False


def parse_date(text: str | None) -> date | None:
    """Reads a date typed in the Sheet: 2026-11-13, 11/13/2026 or 11/13."""
    from datetime import datetime
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(f"{text}/{date.today().year}", "%m/%d/%Y").date()
    except ValueError:
        return None


class Game:
    def __init__(self, db: Database, rng: random.Random | None = None):
        self.db = db
        self.rng = rng or random.Random()
        self.pending: CloseReport | None = None
        self.data_override: dict | None = None   # used by the simulator

    def data(self) -> dict:
        return self.data_override or load_data()

    # ---- settings and rounds -------------------------------------------------
    @property
    def mode(self) -> str:
        return self.db.get("mode", "tables")

    def rounds(self) -> list[dict]:
        return self.data()["rounds"]

    def current_round(self) -> dict | None:
        key = self.db.get("round")
        return next((r for r in self.rounds() if r["key"] == key), None)

    def due_round(self, today: date) -> dict | None:
        """The latest round whose Opens date has arrived, if it's later than the current one."""
        rounds = self.rounds()
        current = self.current_round()
        current_index = rounds.index(current) if current in rounds else -1
        due = None
        for i, r in enumerate(rounds):
            opens = parse_date(r["opens"])
            if opens is None:
                continue
            if opens <= today and i > current_index:
                due = r
        return due

    def open_round(self, key: str) -> dict | None:
        self.db.set("round", key)
        return self.current_round()

    def new_school_stats(self) -> dict:
        """Opening stats; a university that joins after the first closing bell starts at the current median."""
        tuning = self.data()["tuning"]
        stats = starting_stats(tuning, self.rng)
        existing = list(self.db.all_stats().values())
        if self.db.day > 0 and existing:
            import statistics
            jitter = tuning["starting_jitter"] / 2
            for name in ("prestige", "endowment", "enrollment", "satisfaction"):
                stats[name] = statistics.median(st[name] for st in existing) + self.rng.uniform(-jitter, jitter)
        return stats

    def school_names(self) -> list[str]:
        return [s["hashtag"] for s in self.db.schools()]

    # ---- filing posts ----------------------------------------------------------
    def register_or_pitch(self, content: str, user_id: int, user_name: str, message_id: int) -> Filed:
        """A post in College Fair Pitches. The first post with a new hashtag registers the university."""
        db = self.db
        tags, body = parsing.leading_tags(content)
        if not tags:
            return Filed(False, "🎪 Start your pitch with your university's hashtag, like `#TaukTechU`.")
        tag = tags[0]
        school = db.find_school(tag)
        fields = parsing.profile_fields(body)
        new = school is None
        if new:
            similar = parsing.did_you_mean(tag, self.school_names())
            if similar and parsing.squash(similar) != parsing.squash(tag) and "#new" not in content.lower():
                return Filed(False, f"🎪 Did you mean **#{similar}**? If #{tag} really is a new university, "
                                    f"post again with `#new` at the end.")
            name = fields.pop("name", None) or parsing.split_camel(tag)
            code = parsing.ticker_for(tag, {s["code"] for s in db.schools()})
            school_id = db.add_school(tag, name, code, self.new_school_stats(), **fields)
            db.update_school(school_id, pitch=body)
        else:
            school_id = school["id"]
            updates = {k: v for k, v in fields.items() if k != "name"}
            if fields.get("name"):
                updates["name"] = fields["name"]
            pitch = ((school["pitch"] or "") + "\n\n" + body).strip()
            db.update_school(school_id, pitch=pitch, **updates)
        db.add_member(user_id, school_id, user_name)
        db.add_post(user_id, user_name, school_id, "pitch", self._round_key(), len(body.split()), message_id)
        school = db.school(school_id)
        if new:
            return Filed(True, f"🏛️ **{school['name']}** is now listed on the UnderAcademy Exchange as "
                               f"**{school['code']}**. Use **#{school['hashtag']}** on all your posts.", school, True)
        return Filed(True, "", school)

    def _school_from_tags(self, tags: list[str]) -> tuple[object, list[str], str | None]:
        """Finds the university among a post's hashtags. Returns (school, other tags, did-you-mean suggestion)."""
        school, others, suggestion = None, [], None
        for tag in tags:
            match = self.db.find_school(tag)
            if match and school is None:
                school = match
            else:
                others.append(tag)
        if school is None:
            for tag in others:
                if parsing.policy_kind([tag]) or parsing.round_tag([tag], self.rounds()):
                    continue
                suggestion = suggestion or parsing.did_you_mean(tag, self.school_names())
        return school, others, suggestion

    def _unknown(self, suggestion: str | None, what: str) -> Filed:
        if suggestion:
            return Filed(False, f"{what} I couldn't find that university. Did you mean **#{suggestion}**?")
        return Filed(False, f"{what} I couldn't find a university hashtag. New universities register with a post "
                            f"in #{config.CHANNELS['fair']} first.")

    def file_policy(self, content: str, user_id: int, user_name: str, message_id: int) -> Filed:
        tags, body = parsing.leading_tags(content)
        school, others, suggestion = self._school_from_tags(tags)
        if school is None:
            return self._unknown(suggestion, "📜")
        if not body:
            return Filed(False, "📜 I found the hashtag but no policy text. Write the policy after the hashtag.")
        rnd = self._round_for(others)
        kind = parsing.policy_kind(others) or (rnd["policy_kind"] if rnd else "Policy")
        domain = parsing.classify(body, self.data()["domains"])
        key = rnd["key"] if rnd else None
        policy = self.db.add_policy(school["id"], kind, parsing.title_for(body), body, domain,
                                    key, user_id, user_name, message_id)
        self.db.add_member(user_id, school["id"], user_name)
        self.db.add_post(user_id, user_name, school["id"], "policy", key, len(body.split()), message_id)
        return Filed(True, f"{school['code']}-{policy['number']}", school)

    def file_character(self, content: str, user_id: int, user_name: str, message_id: int) -> Filed:
        tags, body = parsing.leading_tags(content)
        school, others, suggestion = self._school_from_tags(tags)
        if school is None:
            return self._unknown(suggestion, "👋")
        rnd = self._round_for(others)
        others = self._strip_tags(others)
        if not others:
            return Filed(False, "👋 Start with `#charactername #role #universityname`.")
        self.db.add_character(school["id"], others[0], others[1] if len(others) > 1 else "", body,
                              user_id, user_name, message_id)
        self.db.add_member(user_id, school["id"], user_name)
        self.db.add_post(user_id, user_name, school["id"], "character", rnd["key"] if rnd else None,
                         len(body.split()), message_id)
        return Filed(True, "", school)

    def file_diary(self, content: str, user_id: int, user_name: str, message_id: int) -> Filed:
        tags, body = parsing.leading_tags(content)
        school, others, suggestion = self._school_from_tags(tags)
        if school is None:
            return self._unknown(suggestion, "📓")
        rnd = self._round_for(others)
        others = self._strip_tags(others)
        if not others or not body:
            return Filed(False, "📓 Start your entry with `#charactername #role #universityname`, then write it.")
        key = rnd["key"] if rnd else None
        self.db.add_diary(school["id"], others[0], others[1] if len(others) > 1 else "", body, key,
                          user_id, user_name, message_id)
        self.db.add_member(user_id, school["id"], user_name)
        self.db.add_post(user_id, user_name, school["id"], "diary", key, len(body.split()), message_id)
        return Filed(True, "", school)

    def _round_for(self, tags: list[str]) -> dict | None:
        """A catch-up round tag on the post, or else the current round."""
        return parsing.round_tag(tags, self.rounds()) or self.current_round()

    def _strip_tags(self, tags: list[str]) -> list[str]:
        """Drops round and kind tags, leaving #charactername #role."""
        return [t for t in tags if not parsing.round_tag([t], self.rounds()) and not parsing.policy_kind([t])]

    def _round_key(self) -> str | None:
        rnd = self.current_round()
        return rnd["key"] if rnd else None

    # ---- the market close ------------------------------------------------
    async def close(self) -> CloseReport:
        """Computes the next day without saving it. Call commit() to make it official."""
        db, data = self.db, self.data()
        day = db.day + 1
        rows = db.schools()
        stats = db.all_stats()
        schools = [School(r["id"], r["name"], r["code"], r["mascot"], stats[r["id"]]) for r in rows]
        by_id = {r["id"]: r for r in rows}

        new_rows = db.unprocessed_policies()
        new_policies = [NewPolicy(p["id"], p["school_id"], p["number"], p["title"], p["domain"], p["kind"])
                        for p in new_rows]
        diary_rows = db.diaries(unprocessed_only=True)
        diaries = [Diary(d["id"], d["school_id"], d["character"], d["role"], d["text"]) for d in diary_rows]
        active = {s.id: [(p["id"], p["title"]) for p in db.policies(s.id, "Active")] for s in schools}

        ai_results = AIResults()
        if ai.enabled(self.mode):
            ai_results = await self._ask_ai(schools, by_id, new_rows, diary_rows, data)

        result = run_day(schools, new_policies, diaries, active, data, self.rng, ai_results)

        prev = db.snapshot(day - 1)
        market_rows = []
        for row in result.market:
            s, p = by_id[row["school_id"]], prev.get(row["school_id"])
            market_rows.append({**row, "name": s["name"], "code": s["code"], "hashtag": s["hashtag"],
                                "prev_price": p["price"] if p else None, "prev_rank": p["rank"] if p else None})
        movers = self._movers(market_rows, result)
        commentary = None
        if ai.enabled(self.mode) and movers:
            commentary = await ai.market_commentary(movers)
        commentary = commentary or reports.template_commentary(movers, self.rng, data["commentary"])

        events_by_school: dict[int, list] = {}
        for e in db.events(day):   # Mark's decrees since the last close
            events_by_school.setdefault(e["school_id"], []).append({"text": e["text"]})
        for e in result.events:
            events_by_school.setdefault(e.school_id, []).append({"text": e.text})
        school_reports = {s.id: reports.school_report(by_id[s.id], day, events_by_school.get(s.id, []),
                                                      result.stats[s.id]) for s in schools}

        report = CloseReport(
            day=day, result=result, market_rows=market_rows, ticker=reports.ticker(market_rows),
            table=reports.league_table(market_rows, day), commentary=commentary, school_reports=school_reports,
            processed={"policies": [p["id"] for p in new_rows], "diaries": [d["id"] for d in diary_rows]})
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
        db.set(f"commentary_{day}", report.commentary)
        for table, ids in report.processed.items():
            db.mark_processed(table, ids)
        db.set("day", day)
        self.pending = None

    async def _ask_ai(self, schools, by_id, new_rows, diary_rows, data) -> AIResults:
        combined = AIResults()
        rnd = self.current_round()
        for s in schools:
            mine = [p for p in new_rows if p["school_id"] == s.id]
            my_diaries = [d for d in diary_rows if d["school_id"] == s.id]
            if not (mine or my_diaries):
                continue
            row = by_id[s.id]
            profile = {k: row[k] for k in ("id", "name", "hashtag", "code", "location", "specialties", "reputation",
                                           "colors", "mascot", "motto", "pitch")}
            register = [{"policy_id": p["id"], "label": f"{row['code']}-{p['number']}", "kind": p["kind"],
                         "text": p["text"], "domain": p["domain"], "status": p["status"]}
                        for p in self.db.policies(s.id)]
            diaries = [{"character": d["character"], "role": d["role"], "entry": d["text"]} for d in my_diaries]
            got = await ai.interpret_school(profile, s.stats, register, [p["id"] for p in mine], diaries,
                                            {"name": rnd["name"], "prompt": rnd["institutional"]} if rnd else None,
                                            data["tuning"])
            combined.policies.update(got.policies)
            combined.diaries.update(got.diaries)
        return combined

    def _movers(self, market_rows: list[dict], result: DayResult) -> list[dict]:
        movers = []
        for r in market_rows:
            if not r["prev_price"]:
                continue
            policies = [p["title"] for p in self.db.policies(r["school_id"], "Active")]
            events = [e.text for e in result.events if e.school_id == r["school_id"]]
            movers.append({"name": r["name"], "code": r["code"],
                           "change_pct": round(reports.pct_change(r["price"], r["prev_price"]), 1),
                           "policies": policies[-5:], "todays_events": events[:4]})
        movers.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
        return movers[:6]

    # ---- the finale ---------------------------------------------------------
    def can_vote_for(self, user_id: int, school_id: int) -> bool:
        return school_id not in {s["id"] for s in self.db.schools_of(user_id)}

    def verdict_by_audit(self) -> list[dict]:
        """The rankings-based winner: final scores, shaken once more by the auditors."""
        stats = self.db.all_stats()
        rows = self.db.schools()
        schools = [School(r["id"], r["name"], r["code"], r["mascot"], stats[r["id"]]) for r in rows]
        by_id = {r["id"]: r for r in rows}
        market = final_audit(schools, stats, self.data(), self.rng)
        return [{**m, "name": by_id[m["school_id"]]["name"], "code": by_id[m["school_id"]]["code"]} for m in market]

    # ---- admin tools and exports --------------------------------------------
    def decree(self, text: str, school_id: int | None, stat: str | None, amount: float) -> None:
        """Mark's custom event. Applies immediately; appears in the next report."""
        stats = self.db.all_stats()
        for sid in ([school_id] if school_id else list(stats)):
            if stat:
                top = 10 if stat == "lawsuits" else 100
                stats[sid][stat] = max(0, min(top, stats[sid][stat] + amount))
            self.db.add_event(self.db.day + 1, sid, "decree", text)
        self.db.save_stats(stats)

    def participation_csv(self) -> str:
        """One row per player per kind of post per round, for grading."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Player", "Discord ID", "Universities", "Post kind", "Round", "Posts", "Words",
                         "First post (UTC)", "Last post (UTC)"])
        names = {r["key"]: r["name"] for r in self.rounds()}
        for r in self.db.participation():
            writer.writerow([r["user_name"], r["user_id"], r["universities"], r["kind"],
                             names.get(r["round"], r["round"] or "Before Round 1"), r["posts"], r["words"],
                             r["first_post"], r["last_post"]])
        return out.getvalue()

    def export_statutes(self) -> str:
        """The Collected Statutes of the Big Digit Conference, as Markdown."""
        db = self.db
        lines = ["# The Collected Statutes of the Big Digit Conference", "",
                 "_As recorded by the UnderAcademy Exchange._", ""]
        final = db.snapshot(db.day)
        for s in sorted(db.schools(), key=lambda s: final[s["id"]]["rank"] if s["id"] in final else 999):
            snap = final.get(s["id"])
            lines.append(f"## {s['name']} (#{s['hashtag']}, {s['code']})")
            meta = [f"**{k.title()}:** {s[k]}" for k in ("motto", "location", "specialties", "colors", "mascot")
                    if s[k]]
            if snap:
                meta.append(f"**Final share price:** ${snap['price']:.2f} (rank {snap['rank']})")
            lines += meta + [""]
            if s["pitch"]:
                lines += ["### College Fair Pitch", s["pitch"], ""]
            chars = db.characters(s["id"])
            if chars:
                lines.append("### Characters")
                lines += [f"- **#{c['name']}** ({c['role']}): {c['text']}" for c in chars]
                lines.append("")
            lines.append("### Policies")
            for p in db.policies(s["id"]):
                lines.append(f"**{s['code']}-{p['number']}** ({p['kind']}, {p['status']}), by {p['author_name']}")
                lines.append(p["text"])
                for entry in db.policy_log(p["id"]):
                    lines.append(f"- Day {entry['day']}: {entry['entry']}")
                lines.append("")
            entries = db.diaries(s["id"])
            if entries:
                lines.append("### Secret Diaries")
                for d in entries:
                    lines += [f"**#{d['character']} #{d['role']}**", d["text"], ""]
        return "\n".join(lines)

    def history_json(self) -> str:
        rows = self.db.conn.execute("SELECT * FROM snapshots ORDER BY day, rank").fetchall()
        return json.dumps([dict(r) for r in rows], indent=1)
