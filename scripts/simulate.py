"""Plays a fake season offline (no Discord, no AI) so you can tune data/tuning.json.

    python -m scripts.simulate                 # 25 schools, 25 days
    python -m scripts.simulate --schools 10 --days 20 --seed 3 --no-curse

Prints the final standings, the gap between first place and the median each day, and a sample report.
"""

import argparse
import asyncio
import random
import statistics
import tempfile
from pathlib import Path

from bot.db import Database
from bot.engine import load_data
from bot.game import Game
from bot import engine

NAMES = ["Grand Prairie Polytechnic", "Saint Algorithm College", "Upper Marlboro Tech", "Halcyon State",
         "The Institute of Vibes", "Northeast Southwestern", "Bayou Digital University", "Crestfall A&M",
         "Pemberton College of Prompts", "Lake Hubris University", "Ivy Adjacent College", "Ironwood Online",
         "Mesa Verde Institute", "Quillmont University", "Second Chance State", "Tidewater Tech",
         "University of the Cloud", "Velvet Hills College", "Westbrook Polytechnic", "Xanadu Community College",
         "Yarrow Valley University", "Zenith Institute", "Old Main University", "Fernhill College",
         "Dunmore Institute of Synergy"]
TITLES = ["Robots attend all lectures", "Mandatory AI roommates", "Chatbot tenure track",
          "Water fountains become charging stations", "Essays graded by vibes", "The Library is now a GPU farm",
          "Free AI for training data", "Human-only quiet hours", "Deans replaced by dashboards",
          "Mascot elected by algorithm", "Syllabi written by the students' phones", "Office hours via hologram"]


async def season(n_schools: int, days: int, seed: int, curse: bool) -> None:
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp()) / "sim.db"
    db = Database(tmp)
    db.set("mode", "tables")
    game = Game(db, rng=random.Random(seed))
    data = load_data()
    if not curse:
        data["tuning"]["curse_of_prestige"]["chance_per_lead"] = 0
        data["tuning"]["curse_of_prestige"]["base_chance"] = 0
        data["tuning"]["underdog"]["chance_per_deficit"] = 0
        data["tuning"]["underdog"]["base_chance"] = 0
        engine.load_data = lambda: data   # patch for this run only
        import bot.game as game_module
        game_module.load_data = lambda: data
    domains = list(data["domains"]["domains"])
    for i, name in enumerate(NAMES[:n_schools]):
        sid = db.add_school(dict(name=name, code="".join(w[0] for w in name.split())[:4].upper() + str(i),
                                 location="Somewhere", specialties="AI", reputation="Rising", colors="Blue",
                                 mascot="Owl", motto=None), game.new_school_stats())
        db.join(1000 + i, sid)

    gaps = []
    for day in range(1, days + 1):
        for s in db.schools():
            if rng.random() < 0.35:
                db.add_policy(s["id"], rng.choice(TITLES), "Policy text.", "", "", rng.choice(domains),
                              "welcome", 1)
            if rng.random() < 0.5:
                db.add_diary(s["id"], 1, "Pat", rng.choice(["student", "professor"]), "Dear diary, today...", 0)
        report = await game.close()
        game.commit(report)
        scores = [r["score"] for r in report.result.market]
        gaps.append(max(scores) - statistics.median(scores))

    final = db.snapshot(db.day)
    print(f"Season: {n_schools} schools, {days} days, seed {seed}, curse {'on' if curse else 'off'}\n")
    for s in sorted(db.schools(), key=lambda s: final[s["id"]]["rank"]):
        r = final[s["id"]]
        print(f"{r['rank']:>2}. {s['name']:<32} ${r['price']:>7.2f}  score {r['score']:.1f}")
    print("\nLead of first place over the median, by day:")
    print(" ".join(f"{g:.1f}" for g in gaps))
    print(f"Average lead: {statistics.mean(gaps):.1f}   Final lead: {gaps[-1]:.1f}")
    print("\nSample closing commentary:\n" + report.commentary)
    print("\nSample school report:\n" + next(iter(report.school_reports.values())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schools", type=int, default=25)
    parser.add_argument("--days", type=int, default=25)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--no-curse", action="store_true")
    args = parser.parse_args()
    asyncio.run(season(args.schools, args.days, args.seed, curse=not args.no_curse))


if __name__ == "__main__":
    main()
