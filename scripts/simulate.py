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
    game = Game(db, rng=random.Random(seed))
    data = load_data()
    if not curse:
        for table in ("curse_of_prestige", "underdog"):
            data["tuning"][table]["base_chance"] = 0
            data["tuning"][table]["chance_per_lead" if table == "curse_of_prestige" else "chance_per_deficit"] = 0
    game.data_override = data
    game.open_round("welcome")
    tags = []
    for i, name in enumerate(NAMES[:n_schools]):
        tag = name.replace(" ", "").replace("&", "")
        game.register_or_pitch(f"#{tag}\nA fine institution.", 1000 + i, f"Player {i}", 10_000 + i)
        tags.append(tag)

    gaps = []
    for day in range(1, days + 1):
        msg = 20_000 + day * 1000
        for i, tag in enumerate(tags):
            if rng.random() < 0.35:
                game.file_policy(f"#{tag} {rng.choice(TITLES)}.", 1000 + i, f"Player {i}", msg + i)
            if rng.random() < 0.5:
                game.file_diary(f"#Pat #{rng.choice(['student', 'professor'])} #{tag}\nDear diary, today the "
                                f"robots took attendance and I was marked absent.", 1000 + i, f"Player {i}",
                                msg + 500 + i)
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
