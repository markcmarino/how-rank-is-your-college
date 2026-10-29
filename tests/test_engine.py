import asyncio
import random

from bot.cogs.diaries import parse_entry
from bot.db import Database
from bot.engine import (AIResults, Diary, Interpretation, NewPolicy, School, load_data, run_day,
                        starting_stats)
from bot.game import Game


def make_schools(n, data, rng):
    return [School(i, f"School {i}", f"S{i}", "Owl", starting_stats(data["tuning"], rng)) for i in range(1, n + 1)]


def test_stats_stay_in_bounds():
    data, rng = load_data(), random.Random(0)
    schools = make_schools(12, data, rng)
    for day in range(30):
        policies = [NewPolicy(day * 100 + s.id, s.id, 1, "Robots attend class", "Teaching") for s in schools]
        result = run_day(schools, policies, [], {}, data, rng)
        for s in schools:
            s.stats = result.stats[s.id]
            for name, value in s.stats.items():
                assert 0 <= value <= (10 if name == "lawsuits" else 100), (name, value)


def test_market_is_ranked_and_priced():
    data, rng = load_data(), random.Random(1)
    result = run_day(make_schools(5, data, rng), [], [], {}, data, rng)
    ranks = [r["rank"] for r in result.market]
    assert ranks == [1, 2, 3, 4, 5]
    scores = [r["score"] for r in result.market]
    assert scores == sorted(scores, reverse=True)
    assert all(r["price"] > 0 for r in result.market)


def test_ai_interpretation_overrides_tables():
    data, rng = load_data(), random.Random(2)
    schools = make_schools(3, data, rng)
    ai = AIResults(policies={7: Interpretation({"prestige": 5}, "The geese approve.")})
    result = run_day(schools, [NewPolicy(7, 1, 1, "Geese", "Teaching")], [], {}, data, rng, ai)
    assert any(e.text == "The geese approve." and e.policy_id == 7 for e in result.events)


def test_curse_hits_runaway_leader():
    data, rng = load_data(), random.Random(3)
    data["tuning"]["daily_drift"] = 0
    schools = make_schools(10, data, rng)
    schools[0].stats.update(prestige=100, endowment=100, enrollment=100, satisfaction=100)
    hits = 0
    for _ in range(200):
        result = run_day(schools, [], [], {}, data, rng)
        hits += any(e.kind == "curse" and e.school_id == schools[0].id for e in result.events)
    assert hits > 60   # roughly half the time at maximum lead


def test_accreditation_strikes_a_policy():
    data, rng = load_data(), random.Random(4)
    schools = make_schools(3, data, rng)
    schools[0].stats["lawsuits"] = 9
    result = run_day(schools, [], [], {1: [(55, "Bad idea")]}, data, rng)
    assert 55 in result.struck_down


def test_diary_parsing():
    find = lambda tag: {"id": 1, "name": "Grand Prairie U"} if tag.lower() in ("grandprairieu", "grpu") else None
    school, character, role, body = parse_entry("#Dana #groundskeeper #GRPU\nThe sprinklers talk now.", find)
    assert school["id"] == 1 and character == "Dana" and role == "groundskeeper"
    assert body == "The sprinklers talk now."
    school, character, role, body = parse_entry("#Dana #student Today I met my robot.", find)
    assert school is None and character == "Dana" and body == "Today I met my robot."


def test_full_close_with_database(tmp_path):
    db = Database(tmp_path / "t.db")
    db.set("mode", "tables")
    game = Game(db, rng=random.Random(5))
    ids = [db.add_school(dict(name=f"U{i}", code=f"UU{i}", location="", specialties="", reputation="",
                              colors="", mascot="Owl", motto=None), game.new_school_stats()) for i in range(4)]
    p = db.add_policy(ids[0], "Robots attend all lectures", "Text", "Pro", "Con", "Teaching", "welcome", 1)
    db.add_diary(ids[0], 1, "Pat", "student", "The robot took my seat.", 0)
    db.add_response(ids[1], "welcome", "Yes, obviously.")
    report = asyncio.run(game.close())
    game.commit(report)
    assert db.day == 1
    assert db.unprocessed_policies() == []
    assert db.policy_log(p["id"])
    assert "UNDERACADEMY EXCHANGE" in report.ticker
    assert "Collected Statutes" in game.export_statutes()
