"""SQLite storage: schools, the Policy Register, diaries, stats and the daily market history."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS game (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- ticker symbol, e.g. GRPU
    location TEXT, specialties TEXT, reputation TEXT,
    colors TEXT, mascot TEXT, motto TEXT,
    pitch TEXT,
    channel_id INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS stats (
    school_id INTEGER PRIMARY KEY REFERENCES schools(id),
    prestige REAL, endowment REAL, enrollment REAL, satisfaction REAL,
    morale REAL, bureaucracy REAL, lawsuits REAL, chaos REAL
);
-- The Policy Register. An amendment is a new row whose parent_id points at the old version.
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    number INTEGER NOT NULL,          -- shown as CODE-number, e.g. GRPU-3
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    pros TEXT, cons TEXT,
    domain TEXT NOT NULL,
    round TEXT,
    status TEXT NOT NULL DEFAULT 'Active',  -- Active, Amended, Repealed, Struck Down, Ignored
    parent_id INTEGER REFERENCES policies(id),
    author_id INTEGER,
    processed INTEGER NOT NULL DEFAULT 0,   -- 1 once a market close has priced it in
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS policy_log (
    id INTEGER PRIMARY KEY,
    policy_id INTEGER NOT NULL REFERENCES policies(id),
    day INTEGER NOT NULL,
    entry TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diaries (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    author_id INTEGER,
    character TEXT, role TEXT,
    text TEXT NOT NULL,
    message_id INTEGER,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    round TEXT,
    text TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
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
        self.conn.commit()

    # ---- game settings -------------------------------------------------
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM game WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value) -> None:
        self.conn.execute("INSERT INTO game(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        self.conn.commit()

    @property
    def day(self) -> int:
        return int(self.get("day", "0"))

    # ---- schools -------------------------------------------------------
    def add_school(self, fields: dict, stats: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO schools(name, code, location, specialties, reputation, colors, mascot, motto, created_at) "
            "VALUES(:name, :code, :location, :specialties, :reputation, :colors, :mascot, :motto, :created_at)",
            {**fields, "created_at": now()})
        school_id = cur.lastrowid
        self.conn.execute(
            f"INSERT INTO stats(school_id, {', '.join(STAT_NAMES)}) VALUES(?, {', '.join('?' * len(STAT_NAMES))})",
            (school_id, *[stats[s] for s in STAT_NAMES]))
        self.conn.commit()
        return school_id

    def schools(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM schools ORDER BY name").fetchall()

    def school(self, school_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM schools WHERE id = ?", (school_id,)).fetchone()

    def find_school(self, text: str) -> sqlite3.Row | None:
        """Match a school by name or ticker code, ignoring case, spaces and leading #."""
        key = _squash(text)
        for row in self.schools():
            if key in (_squash(row["name"]), _squash(row["code"])):
                return row
        return None

    def update_school(self, school_id: int, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE schools SET {sets} WHERE id = ?", (*fields.values(), school_id))
        self.conn.commit()

    def join(self, user_id: int, school_id: int) -> None:
        self.conn.execute("INSERT INTO members(user_id, school_id) VALUES(?, ?) "
                          "ON CONFLICT(user_id) DO UPDATE SET school_id = excluded.school_id",
                          (user_id, school_id))
        self.conn.commit()

    def school_of(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT s.* FROM schools s JOIN members m ON m.school_id = s.id WHERE m.user_id = ?",
            (user_id,)).fetchone()

    def members(self, school_id: int) -> list[int]:
        rows = self.conn.execute("SELECT user_id FROM members WHERE school_id = ?", (school_id,))
        return [r["user_id"] for r in rows]

    # ---- stats ---------------------------------------------------------
    def all_stats(self) -> dict[int, dict]:
        rows = self.conn.execute("SELECT * FROM stats").fetchall()
        return {r["school_id"]: {s: r[s] for s in STAT_NAMES} for r in rows}

    def save_stats(self, stats_by_school: dict[int, dict]) -> None:
        for school_id, stats in stats_by_school.items():
            sets = ", ".join(f"{s} = ?" for s in STAT_NAMES)
            self.conn.execute(f"UPDATE stats SET {sets} WHERE school_id = ?",
                              (*[stats[s] for s in STAT_NAMES], school_id))
        self.conn.commit()

    # ---- policies ------------------------------------------------------
    def add_policy(self, school_id: int, title: str, text: str, pros: str, cons: str,
                   domain: str, round_key: str, author_id: int, parent_id: int | None = None) -> sqlite3.Row:
        number = self.conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM policies WHERE school_id = ?",
                                   (school_id,)).fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO policies(school_id, number, title, text, pros, cons, domain, round, author_id, parent_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (school_id, number, title, text, pros, cons, domain, round_key, author_id, parent_id, now()))
        self.conn.commit()
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

    def count_new_policies(self, school_id: int, round_key: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM policies WHERE school_id = ? AND round = ? AND parent_id IS NULL",
            (school_id, round_key)).fetchone()[0]

    def set_policy_status(self, policy_id: int, status: str) -> None:
        self.conn.execute("UPDATE policies SET status = ? WHERE id = ?", (status, policy_id))
        self.conn.commit()

    def log_policy(self, policy_id: int, day: int, entry: str) -> None:
        self.conn.execute("INSERT INTO policy_log(policy_id, day, entry) VALUES(?, ?, ?)", (policy_id, day, entry))
        self.conn.commit()

    def policy_log(self, policy_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM policy_log WHERE policy_id = ? ORDER BY day, id",
                                 (policy_id,)).fetchall()

    # ---- diaries and challenge responses --------------------------------
    def add_diary(self, school_id: int, author_id: int, character: str, role: str, text: str, message_id: int) -> None:
        self.conn.execute(
            "INSERT INTO diaries(school_id, author_id, character, role, text, message_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)", (school_id, author_id, character, role, text, message_id, now()))
        self.conn.commit()

    def diaries(self, school_id: int | None = None, unprocessed_only: bool = False) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM diaries WHERE 1 = 1", []
        if school_id is not None:
            sql += " AND school_id = ?"
            args.append(school_id)
        if unprocessed_only:
            sql += " AND processed = 0"
        return self.conn.execute(sql + " ORDER BY id", args).fetchall()

    def add_response(self, school_id: int, round_key: str, text: str) -> None:
        self.conn.execute("INSERT INTO responses(school_id, round, text, created_at) VALUES(?, ?, ?, ?)",
                          (school_id, round_key, text, now()))
        self.conn.commit()

    def responses(self, unprocessed_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM responses" + (" WHERE processed = 0" if unprocessed_only else "")
        return self.conn.execute(sql + " ORDER BY id").fetchall()

    def mark_processed(self, table: str, ids: list[int]) -> None:
        assert table in {"policies", "diaries", "responses"}
        self.conn.executemany(f"UPDATE {table} SET processed = 1 WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    # ---- events and market history ---------------------------------------
    def add_event(self, day: int, school_id: int | None, kind: str, text: str) -> None:
        self.conn.execute("INSERT INTO events(day, school_id, kind, text) VALUES(?, ?, ?, ?)",
                          (day, school_id, kind, text))
        self.conn.commit()

    def events(self, day: int, school_id: int | None = None) -> list[sqlite3.Row]:
        if school_id is None:
            return self.conn.execute("SELECT * FROM events WHERE day = ? ORDER BY id", (day,)).fetchall()
        return self.conn.execute("SELECT * FROM events WHERE day = ? AND school_id = ? ORDER BY id",
                                 (day, school_id)).fetchall()

    def save_snapshot(self, day: int, rows: list[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO snapshots(day, school_id, score, price, rank, stats_json) "
            "VALUES(:day, :school_id, :score, :price, :rank, :stats_json)",
            [{**r, "day": day} for r in rows])
        self.conn.commit()

    def snapshot(self, day: int) -> dict[int, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM snapshots WHERE day = ?", (day,)).fetchall()
        return {r["school_id"]: r for r in rows}


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower().lstrip("#") if ch.isalnum())
