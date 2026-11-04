"""Reading players' posts: hashtags, university names, policy kinds and domains. No Discord code here."""

from __future__ import annotations

import difflib
import re

TAG = re.compile(r"#([A-Za-z0-9_][\w\-]*)")
FIELD = re.compile(r"^\s*\**(name|mascot|colors?|location|motto|specialt(?:y|ies)|reputation)\**\s*:\s*(.+)$",
                   re.IGNORECASE)

# Hashtags a player can add to say what kind of policy post this is (otherwise the current round decides)
KIND_TAGS = {
    "policy": "Policy",
    "amendment": "Amendment", "patch": "Amendment",
    "extrememeasure": "Extreme Measure", "extreme": "Extreme Measure",
    "speech": "Graduation Speech", "graduation": "Graduation Speech", "graduationspeech": "Graduation Speech",
}
KINDS = ["Policy", "Amendment", "Extreme Measure", "Graduation Speech"]


def squash(text: str) -> str:
    return "".join(ch for ch in (text or "").lower().lstrip("#") if ch.isalnum())


def leading_tags(content: str) -> tuple[list[str], str]:
    """The hashtags at the start of a post, and the rest of the post.

    Tags may sit on their own line(s) ("#Ellen #groundskeeper #TaukTechU" then the entry), or
    begin the first line of text ("#TaukTechU Our new policy is...").
    """
    lines = content.strip().split("\n")
    tags, start = [], 0
    for i, line in enumerate(lines):
        found = TAG.findall(line)
        leftover = TAG.sub("", line).strip(" ,·|@")
        if found and not leftover:
            tags += found
            start = i + 1
        else:
            break
    if not tags and lines:
        match = re.match(r"^\s*((?:[@#][\w\-]+[\s,·|]*)+)(.*)$", lines[0])
        if match:
            tags = re.findall(r"[@#]([\w\-]+)", match.group(1))
            lines[0] = match.group(2)
            start = 0
    body = "\n".join(lines[start:]).strip()
    return tags, body


# Small words players often leave lowercase inside a hashtag (#UniversityoftheCloud). Only split off after
# these nouns, so words like Grand, Island or Breathe stay whole.
SMALL_WORDS = ("of", "the", "for", "and", "at", "in", "on")
NAME_NOUNS = re.compile(r"^(University|Universidad|Institute|Institution|College|School|Academy|Polytechnic|"
                        r"Seminary|Conservatory|Center|Centre|Campus)((?:of|the|for|and|at|in|on)+)$")


def split_camel(tag: str) -> str:
    """TaukTechU -> Tauk Tech U; grand_prairie_poly -> Grand Prairie Poly; UniversityoftheCloud -> University
    of the Cloud."""
    tag = tag.replace("_", " ").replace("-", " ")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", tag)
    words = []
    for w in spaced.split():
        glued = NAME_NOUNS.match(w)
        if glued:
            words += [glued.group(1)] + re.findall("|".join(SMALL_WORDS), glued.group(2))
        else:
            words.append(w)
    return " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def ticker_for(tag: str, taken: set[str]) -> str:
    """A 2 to 5 letter stock symbol from a hashtag: capitals first (TaukTechU -> TTU), else the first letters."""
    caps = "".join(ch for ch in tag if ch.isupper())
    letters = "".join(ch for ch in tag if ch.isalpha()).upper()
    base = caps if 2 <= len(caps) <= 5 else letters[:4]
    base = (base or "UNIV")[:5]
    if base not in taken:
        return base
    for extra in letters[len(base):] + "XYZQ":
        candidate = (base[:4] + extra)[:5]
        if candidate not in taken:
            return candidate
    n = 2
    while f"{base[:3]}{n}" in taken:
        n += 1
    return f"{base[:3]}{n}"


def profile_fields(text: str) -> dict:
    """Picks up optional lines like "Mascot: Owls" or "Colors: teal and rust" from a pitch."""
    out = {}
    for line in text.split("\n"):
        match = FIELD.match(line)
        if match:
            key = match.group(1).lower()
            key = {"color": "colors", "specialty": "specialties"}.get(key, key)
            out[key] = match.group(2).strip()
    return out


def pitch_text(text: str) -> str:
    """A pitch without its Name:, Mascot: and similar lines, which are shown separately."""
    lines = [line for line in (text or "").split("\n") if not FIELD.match(line)]
    return "\n".join(lines).strip()


def policy_kind(tags: list[str]) -> str | None:
    for tag in tags:
        kind = KIND_TAGS.get(squash(tag))
        if kind:
            return kind
    return None


def round_tag(tags: list[str], rounds: list[dict]) -> dict | None:
    """A catch-up tag naming a round: #round1, #welcomeweek, #midterms, #finals, #epilogue, #graduation..."""
    aliases = {}
    for i, r in enumerate(rounds, start=1):
        names = {squash(r["key"]), squash(r["name"]), f"round{i}"}
        names |= {squash(w) for w in r["name"].replace(":", " ").split()
                  if len(w) > 4 and squash(w) not in ("round", "rounds")}
        names |= {squash(part) for part in r["name"].split(":")}
        for n in names:
            aliases.setdefault(n, r)
    aliases.setdefault("epilogue", rounds[-1] if rounds else None)
    for tag in tags:
        found = aliases.get(squash(tag))
        if found:
            return found
    return None


def classify(text: str, domains: dict) -> str | None:
    """Guesses a policy's domain from its keywords. None if nothing matches."""
    lowered = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    best, best_hits = None, 0
    for name, domain in domains.items():
        hits = sum(lowered.count(f" {k} ") for k in domain.get("keywords", []))
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def title_for(text: str, limit: int = 70) -> str:
    """A short label for a policy: its first sentence, trimmed."""
    flat = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]
    if len(first) <= limit:
        return first.rstrip(" .;:")
    return first[:limit].rsplit(" ", 1)[0] + "..."


def did_you_mean(tag: str, known: list[str], cutoff: float = 0.6) -> str | None:
    """known: the hashtags (as written) of registered universities."""
    by_key = {squash(k): k for k in known}
    match = difflib.get_close_matches(squash(tag), list(by_key), n=1, cutoff=cutoff)
    return by_key[match[0]] if match else None
