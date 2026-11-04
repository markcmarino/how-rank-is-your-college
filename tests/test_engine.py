import asyncio
import csv
import io
import random

from bot import parsing, site
from bot.db import Database
from bot.engine import AIResults, Interpretation, NewPolicy, School, load_data, run_day, starting_stats
from bot.game import Game


def make_schools(n, data, rng):
    return [School(i, f"School {i}", f"S{i}", "Owl", starting_stats(data["tuning"], rng)) for i in range(1, n + 1)]


def new_game(tmp_path, seed=0):
    db = Database(tmp_path / "t.db")
    return db, Game(db, rng=random.Random(seed))


# ---- tables and engine -----------------------------------------------------

def test_starter_tables_load():
    data = load_data()
    assert len(data["domains"]) == 8
    assert len(data["consequences"]) > 50 and data["hubris"] and data["underdog"] and data["diary_leaks"]
    assert [r["key"] for r in data["rounds"]] == ["welcome", "midterms", "finals", "graduation"]
    assert data["commentary"]["reason"]


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


def test_no_unfilled_placeholders():
    data, rng = load_data(), random.Random(9)
    schools = make_schools(6, data, rng)
    for kind in ("Policy", "Amendment", "Extreme Measure", "Graduation Speech"):
        for _ in range(40):
            result = run_day(schools, [NewPolicy(1, 1, 1, "Robots attend class", None, kind)], [], {}, data, rng)
            for e in result.events:
                assert "{" not in e.text, e.text


def test_ai_interpretation_overrides_tables():
    data, rng = load_data(), random.Random(2)
    ai = AIResults(policies={7: Interpretation({"prestige": 5}, "The geese approve.")})
    result = run_day(make_schools(3, data, rng), [NewPolicy(7, 1, 1, "Geese", "Teaching")], [], {}, data, rng, ai)
    assert any(e.text == "The geese approve." and e.policy_id == 7 for e in result.events)


def test_curse_hits_runaway_leader():
    data, rng = load_data(), random.Random(3)
    data["tuning"]["daily_drift"] = 0
    schools = make_schools(10, data, rng)
    schools[0].stats.update(prestige=100, endowment=100, enrollment=100, satisfaction=100)
    hits = sum(any(e.kind == "curse" and e.school_id == 1 for e in run_day(schools, [], [], {}, data, rng).events)
               for _ in range(200))
    assert hits > 60


def test_accreditation_strikes_a_policy():
    data, rng = load_data(), random.Random(4)
    schools = make_schools(3, data, rng)
    schools[0].stats["lawsuits"] = 9
    assert 55 in run_day(schools, [], [], {1: [(55, "Bad idea")]}, data, rng).struck_down


# ---- reading posts -----------------------------------------------------------

def test_leading_tags():
    assert parsing.leading_tags("#Ellen #groundskeeper #TaukTechU\nThe field is daffodils.") == \
        (["Ellen", "groundskeeper", "TaukTechU"], "The field is daffodils.")
    assert parsing.leading_tags("#Tanner #student @TaukTechU\nI learned Hume.") == \
        (["Tanner", "student", "TaukTechU"], "I learned Hume.")
    assert parsing.leading_tags("#TaukTechU All lectures are robots.") == (["TaukTechU"], "All lectures are robots.")


def test_names_tickers_and_matching():
    assert parsing.split_camel("TaukTechU") == "Tauk Tech U"
    assert parsing.split_camel("UniversityoftheCloud") == "University of the Cloud"
    assert parsing.split_camel("UniversityOfTheCloud") == "University of the Cloud"
    assert parsing.split_camel("PembertonCollegeofPrompts") == "Pemberton College of Prompts"
    assert parsing.split_camel("TheInstituteofVibes") == "The Institute of Vibes"
    assert parsing.split_camel("GrandPrairieIslandState") == "Grand Prairie Island State"
    assert parsing.split_camel("university_of_the_cloud") == "University of the Cloud"
    assert parsing.ticker_for("TaukTechU", set()) == "TTU"
    assert parsing.ticker_for("TaukTechU", {"TTU"}) != "TTU"
    assert parsing.did_you_mean("TalkTechU", ["TaukTechU", "GrandPrairie"]) == "TaukTechU"
    domains = load_data()["domains"]
    assert parsing.classify("All dorms become data centers and the cafeteria is a server room.", domains) \
        in ("Student Life", "Facilities")
    rounds = load_data()["rounds"]
    assert parsing.round_tag(["round1"], rounds)["key"] == "welcome"
    assert parsing.round_tag(["Midterms"], rounds)["key"] == "midterms"
    assert parsing.round_tag(["round"], rounds) is None


def test_posting_flow(tmp_path):
    db, game = new_game(tmp_path)
    game.open_round("welcome")
    filed = game.register_or_pitch("#TaukTechU\nWhere robots go to class so you don't have to.\nMascot: Taukens",
                                   1, "Ana", 101)
    assert filed.ok and filed.new_school and filed.school["code"] == "TTU" and filed.school["mascot"] == "Taukens"
    typo = game.register_or_pitch("#TalkTechU\nAnother pitch", 2, "Ben", 102)
    assert not typo.ok and "#TaukTechU" in typo.message
    assert game.file_character("#Ellen #groundskeeper #TaukTechU\nI plant things.", 2, "Ben", 103).ok
    policy = game.file_policy("#TaukTechU Only robots may attend class. Boon: free AI. Concession: no humans.",
                              1, "Ana", 104)
    assert policy.ok and policy.message == "TTU-1"
    late = game.file_policy("#TaukTechU #round1 Dorms become data centers.", 2, "Ben", 105)
    assert late.ok
    game.open_round("midterms")
    patch = game.file_policy("#TaukTechU Robots must now bring humans to class.", 1, "Ana", 106)
    assert db.policy_by_number(filed.school["id"], 3)["kind"] == "Amendment"
    assert patch.ok
    assert game.file_diary("#Ellen #groundskeeper #TaukTechU #round1\nDaffodils everywhere.", 2, "Ben", 107).ok
    bad = game.file_diary("#Ellen #groundskeeper #TaukTekU\nOops.", 2, "Ben", 108)
    assert not bad.ok and "Did you mean" in bad.message
    rows = list(csv.DictReader(io.StringIO(game.participation_csv())))
    assert sorted(r["Player"] for r in rows) == ["Ana", "Ben"]   # one row per player
    ben = next(r for r in rows if r["Player"] == "Ben")
    assert ben["Total posts"] == "3" and ben["Characters"] == "1" and ben["Policies"] == "1"
    assert ben["Diaries"] == "1" and ben["Round 1: Welcome Week"] == "3"
    ana = next(r for r in rows if r["Player"] == "Ana")
    assert ana["Round 2: Midterms"] == "1" and ana["Universities"] == "Tauk Tech U"


def test_close_site_and_finale(tmp_path):
    db, game = new_game(tmp_path, seed=5)
    game.open_round("welcome")
    for i, tag in enumerate(["TaukTechU", "GrandPrairiePoly", "SaintAlgorithm", "LakeHubris"]):
        game.register_or_pitch(f"#{tag}\nA fine institution.", i, f"P{i}", 200 + i)
        game.file_policy(f"#{tag} All lectures are given by robots in the stadium.", i, f"P{i}", 300 + i)
        game.file_diary(f"#Pat #student #{tag}\nThe robot took my seat.", i, f"P{i}", 400 + i)
    for _ in range(3):
        report = asyncio.run(game.close())
        game.commit(report)
    assert db.day == 3 and db.unprocessed_policies() == []
    files = site.build(db, game)
    assert "US Snooze &amp; Whirled Retort" in files["index.html"] and "Tauk Tech U" in files["index.html"]
    assert game.verdict_by_audit()[0]["rank"] == 1
    assert not game.can_vote_for(0, db.find_school("TaukTechU")["id"])
    assert game.can_vote_for(0, db.find_school("LakeHubris")["id"])
    late = game.register_or_pitch("#LateComerU\nWe just got here.", 9, "Late", 500)
    snap = db.all_stats()
    assert abs(snap[late.school["id"]]["prestige"] - snap[db.find_school("TaukTechU")["id"]]["prestige"]) < 15
    assert "Collected Statutes" in game.export_statutes()


def test_due_round(tmp_path):
    from datetime import date
    db, game = new_game(tmp_path)
    assert game.due_round(date(2026, 11, 8)) is None
    assert game.due_round(date(2026, 11, 9))["key"] == "welcome"
    game.open_round("welcome")
    assert game.due_round(date(2026, 11, 12)) is None
    assert game.due_round(date(2026, 11, 18))["key"] == "finals"
