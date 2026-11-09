import asyncio
import csv
import io
import json
import random
from datetime import datetime, timezone
from types import SimpleNamespace

from bot import config, parsing, site
from bot.cogs.posts import Posts
from bot.db import Database
from bot.engine import (AIResults, Interpretation, NewPolicy, School, load_data, run_day, starting_stats,
                        team_weights)
from bot.game import Game
from scripts.simulate import NAMES


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


def test_university_pages_keep_every_diary(tmp_path):
    db, game = new_game(tmp_path, seed=3)
    game.open_round("welcome")
    tags = [name.replace(" ", "").replace("&", "") for name in NAMES]
    for i, tag in enumerate(tags):
        game.register_or_pitch(f"#{tag}\nA fine institution.\nMotto: Onward", i, f"RealName{i}", 1000 + i)
    assert len(db.schools()) == 25                        # real names that share a word aren't taken for typos
    game.commit(asyncio.run(game.close()))
    for i, tag in enumerate(tags):
        for who in range(3):
            game.file_diary(f"#Pat{who} #student #{tag}\nEntry {who} from {tag}. " + "Long entry. " * 60, i,
                            f"RealName{i}", 2000 + i * 10 + who)
    game.file_policy(f"#{tags[0]} All lectures are given by robots.", 0, "RealName0", 5000)
    game.commit(asyncio.run(game.close()))
    files = site.build(db, game)
    front = files["index.html"]
    assert front.count("<div") == front.count("</div>")   # the diary section is no longer cut off mid-entry
    section = front.split("Overheard in the Secret Diaries")[1].split("</section>")[0]
    assert section.count("class='story'") == 25           # one leak per university, none dropped
    assert "All universities (25)" in front and "All universities (25)" in files["university/fernhillcollege.html"]
    assert "archive/day-1.html" in front and "university/grandprairiepolytechnic.html" in front
    assert "../university/grandprairiepolytechnic.html" in files["archive/day-2.html"]
    page = files["university/grandprairiepolytechnic.html"]
    assert all(f"Entry {who} from GrandPrairiePolytechnic" in page for who in range(3))
    assert page.index("Entry 2 from") < page.index("Entry 0 from")   # newest first
    assert "All lectures are given by robots." in page and "Onward" in page and "Motto: Onward" not in page
    assert not any("RealName" in text for text in files.values())    # Discord names stay private


def test_price_charts(tmp_path):
    db, game = new_game(tmp_path, seed=4)
    game.open_round("welcome")
    tags = [name.replace(" ", "").replace("&", "") for name in NAMES[:8]]
    for i, tag in enumerate(tags):
        game.register_or_pitch(f"#{tag}\nA fine institution.", i, f"P{i}", 100 + i)
    assert "<svg" not in site.build(db, game)["index.html"]             # no trading yet: no chart
    game.commit(asyncio.run(game.close()))
    first = site.build(db, game)["index.html"]
    assert "Insufficient data" in first and "<svg" not in first         # one day can't make a line
    for _ in range(3):
        game.commit(asyncio.run(game.close()))
    late = game.register_or_pitch("#ZzyzxCollege\nWe just got here.", 9, "Late", 900)
    game.commit(asyncio.run(game.close()))
    files = site.build(db, game)
    front = files["index.html"]
    assert "The Exchange: Top Five" in front and front.count("class='dot'") == 5
    # Every university with two or more days gets a line, bright or faint; the newest has one point so far
    assert front.count("class='series'") + front.count("class='pack'") == 8
    assert "NaN" not in front and "<svg" in files[f"archive/day-{db.day}.html"]
    assert "<svg" in files["university/grandprairiepolytechnic.html"]
    assert "<svg" not in files[f"university/{late.school['tag_key']}.html"]   # one point so far


def test_every_university_gets_reviewed_before_any_repeats(tmp_path):
    db, game = new_game(tmp_path, seed=8)
    game.open_round("welcome")
    tags = [name.replace(" ", "").replace("&", "") for name in NAMES]
    for i, tag in enumerate(tags):
        game.register_or_pitch(f"#{tag}\nA fine institution.", i, f"RealName{i}", 100 + i)
    seen = []
    for _ in range(13):
        game.commit(asyncio.run(game.close()))
        first = site.build(db, game)
        again = site.build(db, game)
        assert first["index.html"] == again["index.html"]      # rebuilding an edition keeps its choice
        section = first["index.html"].split("University Under Review")[1].split("</section>")[0]
        seen += json.loads(db.get(f"under_review_{db.day}"))
        assert "Read the full file" in section and "RealName" not in section
    assert len(seen) == 26 and len(set(seen)) == 25            # everyone once, then the second time around begins
    late = game.register_or_pitch("#ZzyzxCollege\nWe just got here.", 99, "Late", 900)
    game.commit(asyncio.run(game.close()))
    site.build(db, game)
    assert late.school["id"] in json.loads(db.get(f"under_review_{db.day}"))   # a late joiner goes straight to the front


def test_register_shows_every_policy_filed_since_the_last_bell(tmp_path):
    db, game = new_game(tmp_path, seed=6)
    game.open_round("welcome")
    tags = [name.replace(" ", "").replace("&", "") for name in NAMES[:10]]
    for i, tag in enumerate(tags):
        game.register_or_pitch(f"#{tag}\nA fine institution.", i, f"P{i}", 100 + i)
        assert game.file_policy(f"#{tag} Policy number {i} from this school.", i, f"P{i}", 200 + i).ok
    game.commit(asyncio.run(game.close()))
    register = site.build(db, game)["index.html"].split("From the Policy Register")[1].split("</section>")[0]
    assert all(f"Policy number {i} from" in register for i in range(10))   # not just the newest six
    game.commit(asyncio.run(game.close()))
    quiet = site.build(db, game)["index.html"].split("From the Policy Register")[1].split("</section>")[0]
    assert "No new filings" in quiet and quiet.count("<blockquote>") == 6


def test_class_section_hashtag_on_a_pitch(tmp_path):
    db, game = new_game(tmp_path)
    filed = game.register_or_pitch("#TaukTechU #10am\nA fine place.", 1, "A", 1)
    assert filed.school["hashtag"] == "TaukTechU" and filed.school["section"] == "10am"
    assert "10am" in filed.message and "#10am" not in filed.school["pitch"]
    # The section tag can come first and in any capitals, and is never mistaken for the university
    assert game.register_or_pitch("#1PM #LakeHubris\nDamp.", 2, "B", 2).school["section"] == "1pm"
    assert db.find_school("10am") is None and db.find_school("1pm") is None
    # A guest skips it and gets told how to add it; a later pitch fixes it
    guest = game.register_or_pitch("#SaintAlgorithm\nHoly.", 3, "C", 3)
    assert guest.school["section"] is None and "#11am" in guest.message
    fixed = game.register_or_pitch("#SaintAlgorithm #11am\nStill holy.", 3, "C", 4)
    assert fixed.school["section"] == "11am" and "11am" in fixed.message and fixed.notify
    # A plain later pitch leaves the section alone and stays quiet
    later = game.register_or_pitch("#SaintAlgorithm\nEven holier.", 3, "C", 5)
    assert later.school["section"] == "11am" and later.message == ""
    # A section tag alone isn't a university
    assert not game.register_or_pitch("#10am\nWhich school?", 4, "D", 6).ok


def test_class_section_hashtag_on_a_character_intro(tmp_path):
    db, game = new_game(tmp_path)
    game.open_round("welcome")
    game.register_or_pitch("#TaukTechU\nA fine place.", 1, "A", 1)
    # Wherever the section tag sits, it isn't taken for the character's name or role, and fills in a blank section
    filed = game.file_character("#10am #Ellen #groundskeeper #TaukTechU\nTends the quad.", 1, "A", 2)
    assert filed.ok and filed.notify and "10am" in filed.message and db.find_school("TaukTechU")["section"] == "10am"
    # Agreeing is quiet; disagreeing is flagged and doesn't move the university
    assert game.file_character("#Sanya #10am #student #TaukTechU\nWorks.", 2, "B", 3).message == ""
    clash = game.file_character("#Tanner #student #TaukTechU #1pm\nFoosball.", 3, "C", 4)
    assert clash.ok and clash.notify and "10am" in clash.message and db.find_school("TaukTechU")["section"] == "10am"
    people = {(c["name"], c["role"]) for c in db.conn.execute("SELECT name, role FROM characters")}
    assert people == {("Ellen", "groundskeeper"), ("Sanya", "student"), ("Tanner", "student")}
    # A habit of adding it to a diary or policy does no harm
    assert game.file_diary("#10am #Ellen #groundskeeper #TaukTechU\nDear diary.", 1, "A", 5).ok
    row = db.conn.execute("SELECT character, role FROM diaries").fetchone()
    assert (row["character"], row["role"]) == ("Ellen", "groundskeeper")
    policy = game.file_policy("#TaukTechU #10am Robots teach.", 1, "A", 6)
    assert policy.ok and not policy.notify               # filed policies stay quiet in the channel


def test_winner_draw_rewards_posts_within_each_section(tmp_path):
    db, game = new_game(tmp_path, seed=3)
    game.open_round("welcome")
    game.register_or_pitch("#BusyU #10am\nBusy.", 1, "A", 1)
    game.register_or_pitch("#QuietU #10am\nQuiet.", 2, "B", 2)
    game.register_or_pitch("#OnlyU #1pm\nOnly.", 3, "C", 3)
    game.register_or_pitch("#GuestU\nFriend of the show.", 4, "D", 4)
    for i in range(9):
        game.file_policy(f"#BusyU Robots run department {i}.", 1, "A", 100 + i)
    wins = {"BusyU": 0, "Quiet U": 0}
    names = {"Busy U": "BusyU", "Quiet U": "Quiet U"}
    for _ in range(300):
        draw = game.draw_winners()
        wins[names[draw["sections"]["10am"]["winner"]["name"]]] += 1
        assert draw["sections"]["1pm"]["winner"]["name"] == "Only U"
        assert draw["sections"]["11am"]["winner"] is None
        assert draw["guests"] == ["Guest U"]
    assert wins["BusyU"] > 240 and wins["Quiet U"] > 5      # 10 tickets to 1: favored, but not certain

    # What gets announced is the draw that was shown, once
    shown = game.draw_winners()
    report, winner = game.draw_report(shown), shown["sections"]["10am"]["winner"]["name"]
    assert winner in report and "91%" in report and "Guest U" in report
    assert game.saved_draw() == shown
    text = game.draw_announcement(game.saved_draw())
    assert winner in text and "Guest U" not in text and "11am" not in text
    game.clear_draw()
    assert game.saved_draw() is None


def test_older_game_gets_the_section_column(tmp_path):
    path = tmp_path / "old.db"
    db = Database(path)
    db.conn.execute("ALTER TABLE schools DROP COLUMN section")
    db.conn.commit()
    db.conn.close()
    reopened = Database(path)
    assert "section" in [r["name"] for r in reopened.conn.execute("PRAGMA table_info(schools)")]


def test_lone_university_gets_a_generic_rival(tmp_path):
    from bot import engine

    rng = random.Random(1)
    data = {"departments": []}
    assert engine.fill("{rival} copied it.", data, rng, rival=None) == "A rival university copied it."
    assert engine.fill("{rival} copied it.", data, rng, rival="Lake Hubris") == "Lake Hubris copied it."
    assert engine.fill("{rival} copied it.", data, rng) == "A rival university copied it."

    db, game = new_game(tmp_path, seed=5)
    game.open_round("welcome")
    game.register_or_pitch("#TaukTechU\nAlone at last.", 1, "P1", 200)
    for i in range(30):
        game.file_policy(f"#TaukTechU Lectures are now given by robots, phase {i}.", 1, "P1", 300 + i)
    report = asyncio.run(game.close())
    assert "None" not in report.commentary + "".join(report.school_reports.values())


def test_closing_bell_always_links_the_retort(monkeypatch):
    from bot.main import RankBot

    posts, order = [], []

    async def post(key, text):
        posts.append((key, text))
        order.append("post")

    async def update_site():
        order.append("site")

    fake_bot = SimpleNamespace(post=post, update_site=update_site)
    report = SimpleNamespace(day=1, commentary="Markets rose.", ticker="TTU 100", table="table", school_reports={})

    monkeypatch.setattr(config, "SITE_REPO", "markcmarino/how-rank-is-your-college")
    monkeypatch.setattr(config, "SITE_GITHUB_TOKEN", "")   # the link doesn't depend on this publish succeeding
    asyncio.run(RankBot.publish(fake_bot, report))
    assert posts[-1][0] == "exchange"
    assert "https://markcmarino.github.io/how-rank-is-your-college/" in posts[-1][1]
    assert order[-2:] == ["site", "post"]            # posted after the paper has been updated

    posts.clear()
    monkeypatch.setattr(config, "SITE_REPO", "")
    asyncio.run(RankBot.publish(fake_bot, report))
    assert len(posts) == 3 and not any("Retort" in text for _, text in posts)


def test_publish_is_one_commit(monkeypatch):
    calls = []

    def fake_api(method, path, body=None):
        calls.append((method, path))
        return {"object": {"sha": "head"}, "tree": {"sha": "base"}, "sha": "new"}
    monkeypatch.setattr(site, "_api", fake_api)
    monkeypatch.setattr(site.config, "SITE_GITHUB_TOKEN", "token")
    monkeypatch.setattr(site.config, "SITE_REPO", "someone/somerepo")
    url = site.publish({"index.html": "a", "university/x.html": "b"})
    assert url == "https://someone.github.io/somerepo/"
    assert [c for c in calls if c[0] != "GET"] == [("POST", "/git/trees"), ("POST", "/git/commits"),
                                                   ("PATCH", "/git/refs/heads/" + site.config.SITE_BRANCH)]


def test_character_named_like_a_ticker_stays_with_their_university(tmp_path):
    db, game = new_game(tmp_path)
    game.open_round("welcome")
    game.register_or_pitch("#TaukTechU\nA pitch.", 1, "Ana", 1)
    cloud = game.register_or_pitch("#UniversityoftheCloud\nA pitch.", 2, "Ben", 2)
    assert cloud.school["code"] == "UC" and "Name:" in cloud.message
    filed = game.file_diary("#Uc #dean #TaukTechU\nDear diary.", 1, "Ana", 3)
    assert filed.ok and filed.school["code"] == "TTU"
    assert db.diaries(filed.school["id"])[0]["character"] == "Uc"
    assert game.file_policy("#UC Dreams are tuition.", 2, "Ben", 4).school["code"] == "UC"   # a ticker alone still works


def test_late_posts_count_for_the_round_they_were_posted_in(tmp_path):
    db, game = new_game(tmp_path)
    game.open_round("welcome")
    db.set("round_opened_welcome", "2026-11-09T08:00:00+00:00")
    game.open_round("midterms")
    db.set("round_opened_midterms", "2026-11-13T08:00:00+00:00")
    game.register_or_pitch("#TaukTechU\nA pitch.", 1, "Ana", 1, datetime(2026, 11, 10, tzinfo=timezone.utc))
    assert game.file_diary("#Ellen #groundskeeper #TaukTechU\nLate entry.", 1, "Ana", 2,
                           datetime(2026, 11, 12, 23, 59, tzinfo=timezone.utc)).ok
    assert db.diaries()[0]["round"] == "welcome"
    row = next(csv.DictReader(io.StringIO(game.participation_csv())))
    assert row["Round 1: Welcome Week"] == "2" and row["Last post (UTC)"].startswith("2026-11-12T23:59")


class FakeMessage:
    def __init__(self, id, content, channel):
        self.id, self.content, self.channel = id, content, channel
        self.author = SimpleNamespace(bot=False, id=1, display_name="Ana")
        self.guild = True
        self.created_at = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.reactions, self.replies = [], []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def reply(self, text, mention_author=False):
        self.replies.append(text)


class FakeChannel:
    def __init__(self, id, name):
        self.id, self.name, self.messages = id, name, []

    async def history(self, after, oldest_first, limit):
        for message in self.messages:
            if message.id > after.id:
                yield message


def test_catch_up_files_missed_posts_once_and_skips_old_ones(tmp_path):
    db, game = new_game(tmp_path)
    game.open_round("welcome")
    posted = []

    async def post(key, text):
        posted.append(text)

    pitches = FakeChannel(10, config.CHANNELS["fair"])

    async def active_threads():
        return []
    guild = SimpleNamespace(text_channels=[pitches], active_threads=active_threads)
    bot = SimpleNamespace(db=db, game=game, post=post, home_guild=lambda: guild)
    cog = Posts(bot)
    old = FakeMessage(5, "#OldTestSchool\nFrom before the game.", pitches)
    pitches.messages = [old]
    asyncio.run(cog.catch_up())                     # first look: note the position, file nothing old
    assert db.schools() == [] and old.reactions == []
    db.set(f"seen_{pitches.id}", 6)
    missed = FakeMessage(7, "#TaukTechU\nPosted while the bot was away.", pitches)
    typo = FakeMessage(8, "", pitches)
    pitches.messages = [old, missed, typo]
    asyncio.run(cog.catch_up())
    asyncio.run(cog.catch_up())                     # running it again changes nothing
    assert [s["hashtag"] for s in db.schools()] == ["TaukTechU"]
    assert len(missed.reactions) == 1 and len(missed.replies) == 1 and len(posted) == 1
    assert int(db.get(f"seen_{pitches.id}")) == 7


def test_backup_is_a_working_copy(tmp_path):
    db, game = new_game(tmp_path)
    game.register_or_pitch("#TaukTechU\nA pitch.", 1, "Ana", 1)
    db.backup_to(tmp_path / "copy.db")
    assert Database(tmp_path / "copy.db").find_school("TaukTechU")["name"] == "Tauk Tech U"


def test_due_round(tmp_path):
    from datetime import date
    db, game = new_game(tmp_path)
    assert game.due_round(date(2026, 11, 8)) is None
    assert game.due_round(date(2026, 11, 9))["key"] == "welcome"
    game.open_round("welcome")
    assert game.due_round(date(2026, 11, 12)) is None
    assert game.due_round(date(2026, 11, 18))["key"] == "finals"


def test_posts_count_in_proportion_to_team_size(tmp_path):
    data, rng = load_data(), random.Random(0)
    schools = make_schools(3, data, rng)
    weights = team_weights(schools, {1: 8, 2: 2, 3: 2}, data["tuning"])   # average team is 4
    assert weights == {1: 0.5, 2: 2.0, 3: 2.0}
    assert 8 * weights[1] == 2 * weights[2]                    # eight posts from eight players = two from two
    assert team_weights(schools, {1: 40, 2: 1, 3: 1}, data["tuning"])[2] == 4.0   # capped by max_weight
    assert set(team_weights(schools, None, data["tuning"]).values()) == {1.0}
    # The same policy moves a small team further than a big one
    ai = AIResults(policies={1: Interpretation({"bureaucracy": 10}, "x"), 2: Interpretation({"bureaucracy": 10}, "y")})
    before = {s.id: s.stats["bureaucracy"] for s in schools}
    result = run_day(schools, [NewPolicy(1, 1, 1, "A", None), NewPolicy(2, 2, 1, "B", None)], [], {}, data,
                     random.Random(1), ai, team_sizes={1: 8, 2: 2, 3: 2})
    assert result.stats[2]["bureaucracy"] - before[2] > 3 * (result.stats[1]["bureaucracy"] - before[1])

    # Team size is Discord accounts with a character there, once each however many characters they play
    db, game = new_game(tmp_path, seed=2)
    game.open_round("welcome")
    game.register_or_pitch("#TaukTechU\nA fine institution.", 1, "Rob", 10)
    game.register_or_pitch("#LakeHubris\nAnother.", 5, "Solo", 11)
    for i, (user, name) in enumerate([(1, "Ada"), (1, "Bea"), (1, "Cy"), (2, "Dot"), (3, "Ed")]):
        assert game.file_character(f"#{name} #student #TaukTechU\nHere.", user, f"P{user}", 20 + i).ok
    sizes = game.team_sizes()
    assert sizes[db.find_school("TaukTechU")["id"]] == 3       # Rob's three characters still count as one player
    assert sizes[db.find_school("LakeHubris")["id"]] == 1      # no characters yet: whoever has posted
