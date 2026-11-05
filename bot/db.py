"""SQLite storage: universities, the Policy Register, characters, diaries, participation, votes and prices."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parsing import squash

SCHEMA = """
CREATE TABLE IF NOT EXISTS game (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    hashtag TEXT NOT NULL,                 -- as first written, e.g. TaukTechU
    tag_key TEXT NOT NULL UNIQUE,          -- squashed hashtag, for matching
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,             -- ticker symbol, e.g. TTU
    location TEXT, specialties TEXT, reputation TEXT, colors TEXT, mascot TEXT, motto TEXT,
    pitch TEXT,
    section TEXT,                          -- class section (10am, 11am, 1pm); empty for guests
    created_at TEXT
);
-- Who has posted for which university (a player can post for more than one)
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER NOT NULL,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    user_name TEXT,
    PRIMARY KEY (user_id, school_id)
);
CREATE TABLE IF NOT EXISTS stats (
    school_id INTEGER PRIMARY KEY REFERENCES schools(id),
    prestige REAL, endowment REAL, enrollment REAL, satisfaction REAL,
    morale REAL, bureaucracy REAL, lawsuits REAL, chaos REAL
);
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    number INTEGER NOT NULL,               -- shown as CODE-number, e.g. TTU-3
    kind TEXT NOT NULL DEFAULT 'Policy',   -- Policy, Amendment, Extreme Measure, Graduation Speech
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    domain TEXT,
    round TEXT,
    status TEXT NOT NULL DEFAULT 'Active', -- Active, Struck Down
    author_id INTEGER, author_name TEXT,
    message_id INTEGER UNIQUE,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS policy_log (
    id INTEGER PRIMARY KEY,
    policy_id INTEGER NOT NULL REFERENCES policies(id),
    day INTEGER NOT NULL,
    entry TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    name TEXT NOT NULL, role TEXT,
    text TEXT,
    author_id INTEGER, author_name TEXT,
    message_id INTEGER UNIQUE,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS diaries (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    character TEXT, role TEXT,
    text TEXT NOT NULL,
    round TEXT,
    author_id INTEGER, author_name TEXT,
    message_id INTEGER UNIQUE,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);
-- Every filed post, for participation reports
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL, user_name TEXT,
    school_id INTEGER,
    kind TEXT NOT NULL,                    -- pitch, character, policy, diary
    round TEXT,
    words INTEGER,
    message_id INTEGER UNIQUE,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS votes (
    user_id INTEGER PRIMARY KEY,
    user_name TEXT,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    school_id INTEGER,
    kind TEXT,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    day INTEGER NOT NULL,
    school_id INTEGER NOT NULL,
    score REAL, price REAL, rank INTEGER,
    stats_json TEXT,
    PRIMARY KEY (day, school_id)
);
"""

STAT_NAMES = ["prestige", "endowment", "enrollment", "satisfaction",
              "morale", "bureaucracy", "lawsuits", "chaos"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        # A game started before class sections existed gets the new column; its data is untouched
        if "section" not in [row["name"] for row in self.conn.execute("PRAGMA table_info(schools)")]:
            self.conn.execute("ALTER TABLE schools ADD COLUMN section TEXT")
        self.conn.commit()

    def _run(self, sql: str, args=()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur

    # ---- game settings -------------------------------------------------
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM game WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value) -> None:
        self._run("INSERT INTO game(key, value) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    @property
    def day(self) -> int:
        return int(self.get("day", "0"))

    # ---- universities --------------------------------------------------
    def add_school(self, hashtag: str, name: str, code: str, stats: dict, **profile) -> int:
        fields = {k: profile.get(k) for k in ("location", "specialties", "reputation", "colors", "mascot", "motto")}
        cur = self._run(
            "INSERT INTO schools(hashtag, tag_key, name, code, location, specialties, reputation, colors, mascot, "
            "motto, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hashtag, squash(hashtag), name, code, *fields.values(), now()))
        self._run(f"INSERT INTO stats(school_id, {', '.join(STAT_NAMES)}) "
                  f"VALUES(?, {', '.join('?' * len(STAT_NAMES))})",
                  (cur.lastrowid, *[stats[s] for s in STAT_NAMES]))
        return cur.lastrowid

    def schools(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM schools ORDER BY name").fetchall()

    def school(self, school_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM schools WHERE id = ?", (school_id,)).fetchone()

    def find_school(self, text: str, tickers: bool = True) -> sqlite3.Row | None:
        """Match by hashtag, ticker or full name, ignoring case, spaces and a leading #."""
        key = squash(text)
        if not key:
            return None
        for row in self.schools():
            if key in (row["tag_key"], squash(row["name"])) or (tickers and key == squash(row["code"])):
                return row
        return None

    def update_school(self, school_id: int, **fields) -> None:
        if "hashtag" in fields:
            fields["tag_key"] = squash(fields["hashtag"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE schools SET {sets} WHERE id = ?", (*fields.values(), school_id))

    def add_member(self, user_id: int, school_id: int, user_name: str) -> None:
        self._run("INSERT INTO members(user_id, school_id, user_name) VALUES(?, ?, ?) "
                  "ON CONFLICT(user_id, school_id) DO UPDATE SET user_name = excluded.user_name",
                  (user_id, school_id, user_name))

    def schools_of(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT s.* FROM schools s JOIN members m ON m.school_id = s.id "
                                 "WHERE m.user_id = ?", (user_id,)).fetchall()

    # ---- stats ---------------------------------------------------------
    def all_stats(self) -> dict[int, dict]:
        rows = self.conn.execute("SELECT * FROM stats").fetchall()
        return {r["school_id"]: {s: r[s] for s in STAT_NAMES} for r in rows}

    def save_stats(self, stats_by_school: dict[int, dict]) -> None:
        sets = ", ".join(f"{s} = ?" for s in STAT_NAMES)
        self.conn.executemany(f"UPDATE stats SET {sets} WHERE school_id = ?",
                              [(*[st[s] for s in STAT_NAMES], sid) for sid, st in stats_by_school.items()])
        self.conn.commit()

    # ---- the Policy Register -------------------------------------------
    def add_policy(self, school_id: int, kind: str, title: str, text: str, domain: str | None, round_key: str | None,
                   author_id: int, author_name: str, message_id: int | None = None) -> sqlite3.Row:
        number = self.conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM policies WHERE school_id = ?",
                                   (school_id,)).fetchone()[0]
        cur = self._run(
            "INSERT INTO policies(school_id, number, kind, title, text, domain, round, author_id, author_name, "
            "message_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (school_id, number, kind, title, text, domain, round_key, author_id, author_name, message_id, now()))
        return self.policy(cur.lastrowid)

    def policy(self, policy_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM policies WHERE id = ?", (policy_id,)).fetchone()

    def policy_by_number(self, school_id: int, number: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM policies WHERE school_id = ? AND number = ?",
                                 (school_id, number)).fetchone()

    def policies(self, school_id: int | None = None, status: str | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM policies WHERE 1 = 1", []
        if school_id is not None:
            sql += " AND school_id = ?"
            args.append(school_id)
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        return self.conn.execute(sql + " ORDER BY school_id, number", args).fetchall()

    def unprocessed_policies(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM policies WHERE processed = 0 ORDER BY id").fetchall()

    def set_policy_status(self, policy_id: int, status: str) -> None:
        self._run("UPDATE policies SET status = ? WHERE id = ?", (status, policy_id))

    def log_policy(self, policy_id: int, day: int, entry: str) -> None:
        self._run("INSERT INTO policy_log(policy_id, day, entry) VALUES(?, ?, ?)", (policy_id, day, entry))

    def policy_log(self, policy_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM policy_log WHERE policy_id = ? ORDER BY day, id",
                                 (policy_id,)).fetchall()

    # ---- characters and diaries ------------------------------------------
    def add_character(self, school_id: int, name: str, role: str, text: str, author_id: int, author_name: str,
                      message_id: int | None = None) -> None:
        self._run("INSERT INTO characters(school_id, name, role, text, author_id, author_name, message_id, "
                  "created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                  (school_id, name, role, text, author_id, author_name, message_id, now()))

    def characters(self, school_id: int | None = None) -> list[sqlite3.Row]:
        if school_id is None:
            return self.conn.execute("SELECT * FROM characters ORDER BY id").fetchall()
        return self.conn.execute("SELECT * FROM characters WHERE school_id = ? ORDER BY id", (school_id,)).fetchall()

    def add_diary(self, school_id: int, character: str, role: str, text: str, round_key: str | None,
                  author_id: int, author_name: str, message_id: int | None = None) -> None:
        self._run("INSERT INTO diaries(school_id, character, role, text, round, author_id, author_name, "
                  "message_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (school_id, character, role, text, round_key, author_id, author_name, message_id, now()))

    def diaries(self, school_id: int | None = None, unprocessed_only: bool = False) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM diaries WHERE 1 = 1", []
        if school_id is not None:
            sql += " AND school_id = ?"
            args.append(school_id)
        if unprocessed_only:
            sql += " AND processed = 0"
        return self.conn.execute(sql + " ORDER BY id", args).fetchall()

    def mark_processed(self, table: str, ids: list[int]) -> None:
        assert table in {"policies", "diaries"}
        self.conn.executemany(f"UPDATE {table} SET processed = 1 WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    def backup_to(self, path: Path | str) -> None:
        """Writes a safe copy of the database, even while the game is running."""
        target = sqlite3.connect(path)
        try:
            self.conn.backup(target)
        finally:
            target.close()

    def already_filed(self, message_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM posts WHERE message_id = ?", (message_id,)).fetchone() is not None

    # ---- participation -------------------------------------------------
    def add_post(self, user_id: int, user_name: str, school_id: int | None, kind: str, round_key: str | None,
                 words: int, message_id: int | None, posted_at: str | None = None) -> None:
        self._run("INSERT OR IGNORE INTO posts(user_id, user_name, school_id, kind, round, words, message_id, "
                  "created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                  (user_id, user_name, school_id, kind, round_key, words, message_id, posted_at or now()))

    def participation(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT p.user_id, MAX(p.user_name) AS user_name, "
            "s.name AS university, p.kind, p.round, COUNT(*) AS posts, "
            "SUM(p.words) AS words, MIN(p.created_at) AS first_post, MAX(p.created_at) AS last_post "
            "FROM posts p LEFT JOIN schools s ON s.id = p.school_id "
            "GROUP BY p.user_id, p.school_id, p.kind, p.round ORDER BY user_name").fetchall()

    def school_post_counts(self) -> list[sqlite3.Row]:
        """Every university with its section and its number of filed posts, most posts first."""
        return self.conn.execute("SELECT s.id, s.name, s.code, s.section, COUNT(p.id) AS posts FROM schools s "
                                 "LEFT JOIN posts p ON p.school_id = s.id GROUP BY s.id "
                                 "ORDER BY posts DESC, s.name").fetchall()

    # ---- votes ---------------------------------------------------------
    def cast_vote(self, user_id: int, user_name: str, school_id: int) -> None:
        self._run("INSERT INTO votes(user_id, user_name, school_id, created_at) VALUES(?, ?, ?, ?) "
                  "ON CONFLICT(user_id) DO UPDATE SET school_id = excluded.school_id, "
                  "user_name = excluded.user_name, created_at = excluded.created_at",
                  (user_id, user_name, school_id, now()))

    def vote_tally(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT s.id, s.name, s.code, COUNT(v.user_id) AS votes FROM schools s "
                                 "LEFT JOIN votes v ON v.school_id = s.id GROUP BY s.id "
                                 "ORDER BY votes DESC, s.name").fetchall()

    def clear_votes(self) -> None:
        self._run("DELETE FROM votes")

    # ---- events and market history ---------------------------------------
    def add_event(self, day: int, school_id: int | None, kind: str, text: str) -> None:
        self._run("INSERT INTO events(day, school_id, kind, text) VALUES(?, ?, ?, ?)", (day, school_id, kind, text))

    def events(self, day: int, school_id: int | None = None) -> list[sqlite3.Row]:
        if school_id is None:
            return self.conn.execute("SELECT * FROM events WHERE day = ? ORDER BY id", (day,)).fetchall()
        return self.conn.execute("SELECT * FROM events WHERE day = ? AND school_id = ? ORDER BY id",
                                 (day, school_id)).fetchall()

    def school_events(self, school_id: int) -> list[sqlite3.Row]:
        """Everything that has happened to one university, newest first."""
        return self.conn.execute("SELECT * FROM events WHERE school_id = ? ORDER BY day DESC, id DESC",
                                 (school_id,)).fetchall()

    def save_snapshot(self, day: int, rows: list[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO snapshots(day, school_id, score, price, rank, stats_json) "
            "VALUES(:day, :school_id, :score, :price, :rank, :stats_json)", [{**r, "day": day} for r in rows])
        self.conn.commit()

    def price_history(self) -> dict[int, list[tuple[int, float]]]:
        """Each university's (day, price) points, oldest first."""
        history: dict[int, list[tuple[int, float]]] = {}
        for r in self.conn.execute("SELECT school_id, day, price FROM snapshots ORDER BY day").fetchall():
            history.setdefault(r["school_id"], []).append((r["day"], r["price"]))
        return history

    def snapshot(self, day: int) -> dict[int, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM snapshots WHERE day = ?", (day,)).fetchall()
        return {r["school_id"]: r for r in rows}
