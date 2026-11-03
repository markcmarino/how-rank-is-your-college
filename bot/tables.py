"""The lookup tables: flavor text and policy effects that Mark and Rob edit in Google Sheets.

Where the bot gets them, in order:
1. The Google Sheet named by TABLES_SHEET_ID (shared as "Anyone with the link can view"),
   fetched at startup, at every closing bell, and with /admin tables.
2. The last good copy of each tab it fetched (data/sheet_cache/), if the Sheet can't be reached.
3. The starter copies in data/tables/, which ship with the code.

Each tab is checked on its own: if one tab is broken (a renamed column, say), only that tab falls back.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import logging
import urllib.request
from datetime import datetime

from . import config

log = logging.getLogger(__name__)

STATS = ["prestige", "endowment", "enrollment", "satisfaction", "morale", "bureaucracy", "lawsuits", "chaos"]
STAT_HEADERS = [s.title() for s in STATS]

# Tab file name -> (Sheet tab title, Sheet tab id ("gid"), required columns)
TABS = {
    "policy_domains": ("Policy Domains", 1001, ["Domain", "Keywords"] + STAT_HEADERS),
    "policy_consequences": ("Policy Consequences", 1002, ["Domain", "Round", "Text"]),
    "curse_of_prestige": ("Curse of Prestige", 1003, ["Text"] + STAT_HEADERS + ["Rival Stat", "Rival Amount"]),
    "underdog_luck": ("Underdog Luck", 1004, ["Text"] + STAT_HEADERS + ["Rival Stat", "Rival Amount"]),
    "diary_leaks": ("Diary Leaks", 1005, ["Text", "Stat", "Low", "High"]),
    "symptoms": ("Symptoms", 1006, ["Condition", "Text"]),
    "departments": ("Departments", 1007, ["Department"]),
    "market_commentary": ("Market Commentary", 1008, ["Kind", "Text"]),
    "rounds": ("Rounds", 1009, ["Key", "Name", "Opens", "Policy Kind", "Administrators", "Characters"]),
}
LOCAL_DIR = config.DATA_DIR / "tables"
CACHE_DIR = config.DATA_DIR / "sheet_cache"

_rows: dict[str, list[dict]] | None = None
_status: dict[str, str] = {}
_loaded_at: str | None = None


# ---- reading ---------------------------------------------------------------

def _parse(text: str, required: list[str]) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in headers]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    rows = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if any(row.get(c) for c in required):
            rows.append(row)
    if not rows:
        raise ValueError("no rows")
    return rows


def _read_local(name: str) -> list[dict]:
    _, _, required = TABS[name]
    for folder, label in ((CACHE_DIR, "last good Sheet copy"), (LOCAL_DIR, "starter copy")):
        path = folder / f"{name}.csv"
        if path.exists():
            try:
                rows = _parse(path.read_text(encoding="utf-8"), required)
                _status[name] = label
                return rows
            except ValueError as e:
                log.warning("%s (%s) unusable: %s", path, label, e)
    raise FileNotFoundError(f"No usable copy of the {TABS[name][0]} table")


def _fetch(name: str) -> str:
    _, gid, _ = TABS[name]
    url = f"https://docs.google.com/spreadsheets/d/{config.TABLES_SHEET_ID}/export?format=csv&gid={gid}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        text = resp.read().decode("utf-8")
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise ValueError("got a web page instead of CSV; is the Sheet shared as 'Anyone with the link can view'?")
    return text


def refresh() -> dict[str, str]:
    """Re-reads every tab from the Google Sheet, falling back tab by tab. Returns where each tab came from."""
    global _rows, _loaded_at
    rows = {}
    for name, (title, _, required) in TABS.items():
        if config.TABLES_SHEET_ID:
            try:
                text = _fetch(name)
                rows[name] = _parse(text, required)
                CACHE_DIR.mkdir(exist_ok=True)
                (CACHE_DIR / f"{name}.csv").write_text(text, encoding="utf-8")
                _status[name] = "Google Sheet"
                continue
            except Exception as e:   # network trouble, bad sharing, renamed column...
                log.warning("Sheet tab '%s' unusable (%s); falling back", title, e)
                _status[name] = f"fallback ({e})"
        rows[name] = _read_local(name)
        if config.TABLES_SHEET_ID and not _status[name].startswith("fallback"):
            _status[name] = f"fallback: {_status[name]}"
    _rows = rows
    _loaded_at = datetime.now().strftime("%b %d %I:%M %p")
    return dict(_status)


def status() -> tuple[str | None, dict[str, str]]:
    return _loaded_at, dict(_status)


def rows() -> dict[str, list[dict]]:
    global _rows
    if _rows is None:   # first use: local copies only; refresh() pulls the Sheet
        _rows = {name: _read_local(name) for name in TABS}
    return _rows


# ---- turning rows into game data ----------------------------------------------

def _num(value: str) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def _effects(row: dict) -> dict:
    return {s: _num(row.get(s.title(), "")) for s in STATS if _num(row.get(s.title(), "")) != 0}


def _event(row: dict) -> dict:
    out = {"text": row["Text"], "effects": _effects(row)}
    rival = row.get("Rival Stat", "").strip().lower()
    if rival in STATS and _num(row.get("Rival Amount", "")):
        out["rival_effects"] = {rival: _num(row["Rival Amount"])}
    return out


CONDITIONS = {"low morale": "low_morale", "high bureaucracy": "high_bureaucracy", "high lawsuits": "high_lawsuits",
              "high chaos": "high_chaos", "low satisfaction": "low_satisfaction"}


def game_data() -> dict:
    """Everything the engine needs, as plain Python. A fresh copy each call, so callers may modify it."""
    r = rows()
    domains = {row["Domain"]: {"effects": _effects(row),
                               "keywords": [k.strip().lower() for k in row["Keywords"].split(",") if k.strip()]}
               for row in r["policy_domains"]}
    symptoms: dict[str, list[str]] = {}
    for row in r["symptoms"]:
        key = CONDITIONS.get(row["Condition"].lower())
        if key:
            symptoms.setdefault(key, []).append(row["Text"])
    commentary: dict[str, list[str]] = {}
    for row in r["market_commentary"]:
        commentary.setdefault(row["Kind"].lower().replace(" ", "_"), []).append(row["Text"])
    leaks = []
    for row in r["diary_leaks"]:
        stat = row["Stat"].strip().lower()
        leaks.append({"text": row["Text"], "stat": stat if stat in STATS else "satisfaction",
                      "low": _num(row["Low"]), "high": _num(row["High"])})
    rounds = [{"key": row["Key"].lower(), "name": row["Name"], "opens": row["Opens"],
               "policy_kind": row["Policy Kind"] or "Policy", "institutional": row["Administrators"],
               "character": row["Characters"]} for row in r["rounds"]]
    data = {
        "tuning": json.loads((config.DATA_DIR / "tuning.json").read_text(encoding="utf-8")),
        "domains": domains,
        "consequences": [{"domain": row["Domain"], "round": row["Round"] or "Any", "text": row["Text"]}
                         for row in r["policy_consequences"]],
        "hubris": [_event(row) for row in r["curse_of_prestige"]],
        "underdog": [_event(row) for row in r["underdog_luck"]],
        "diary_leaks": leaks,
        "symptoms": symptoms,
        "departments": [row["Department"] for row in r["departments"]],
        "commentary": commentary,
        "rounds": rounds,
    }
    return copy.deepcopy(data)
