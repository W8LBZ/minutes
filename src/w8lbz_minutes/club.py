"""Club config and people.

People come from the roster Google Sheet (synced to data/roster.json by `w8lbz-minutes roster`).
club.yaml (local only, never in git) holds app settings plus temporary per-member
`overrides` for things the sheet has no column for yet (short_name, aliases, minutes_role).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from functools import cached_property
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("W8LBZ_ROOT", Path(__file__).resolve().parents[2]))
DATA = Path(os.environ.get("W8LBZ_DATA", ROOT / "data"))
MEETINGS = DATA / "meetings"
ROSTER_CACHE = DATA / "roster.json"


def _n(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


@dataclass
class Member:
    id: str
    first: str
    last: str
    short: str | None = None
    callsign: str | None = None
    email: str | None = None
    role: str | None = None  # officer title(s)
    officer: bool = False
    board: bool = False
    license_class: str | None = None
    minutes_role: str | None = None  # leader | editor
    status: str = "active"
    aliases: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()


class Club:
    def __init__(self, path: Path | None = None, roster: list[dict] | None = None):
        path = path or Path(os.environ.get("W8LBZ_CONFIG", ROOT / "club.yaml"))
        cfg = yaml.safe_load(path.read_text()) or {}
        self.info = cfg.get("club", {})
        self.links = cfg.get("links", [])
        self.redact = [_n(x) for x in (cfg.get("privacy") or {}).get("never_record", [])]

        if roster is None and "members" in cfg:  # inline members (tests, example config)
            roster = [{"id": k, **(v or {})} for k, v in cfg["members"].items()]
        if roster is None and ROSTER_CACHE.exists():
            roster = json.loads(ROSTER_CACHE.read_text())
        known = {f.name for f in fields(Member)}
        self.members: dict[str, Member] = {}
        for d in roster or []:
            d = {**d, **((cfg.get("overrides") or {}).get(d["id"]) or {})}
            self.members[d["id"]] = Member(**{k: v for k, v in d.items() if k in known})
        self._auto_short_names()

    def _auto_short_names(self) -> None:
        """'Chris D' / 'Chris K' style names when a first name is shared."""
        by_first: dict[str, list[Member]] = {}
        for m in self.members.values():
            by_first.setdefault(m.first.lower(), []).append(m)
        for group in by_first.values():
            for m in group:
                if not m.short and len(group) > 1 and m.last:
                    m.short = f"{m.first} {m.last[0]}"

    # ---- permissions ----
    def can_lead(self, mid: str) -> bool:
        m = self.members.get(mid)
        return bool(m and (m.officer or m.minutes_role == "leader"))

    def can_edit(self, mid: str) -> bool:
        m = self.members.get(mid)
        return bool(m and (self.can_lead(mid) or m.minutes_role == "editor"))

    @property
    def leaders(self) -> list[str]:
        return [mid for mid in self.members if self.can_lead(mid)]

    # ---- privacy ----
    def is_redacted(self, text: str) -> bool:
        t = _n(text)
        return any(r and r in t for r in self.redact)

    # ---- names ----
    def name(self, mid: str | None) -> str:
        m = self.members.get(mid or "")
        return m.name if m else (mid or "").title()

    def short(self, mid: str) -> str:
        m = self.members.get(mid)
        return (m.short or m.first or m.last) if m else mid.title()

    def resolve_surname(self, word: str) -> str | None:
        """Map an attendance-list surname (with spelling drift) to a member id."""
        w = word.lower()
        for m in self.members.values():
            if w == m.last.lower() or w in (a.lower() for a in m.aliases):
                return m.id
        return None

    @cached_property
    def _speaker_patterns(self) -> list[tuple[re.Pattern, str]]:
        """Patterns for 'who is this report about', most specific first."""
        pats: list[tuple[str, str]] = []
        firsts: dict[str, list[str]] = {}
        for m in self.members.values():
            if not m.first:
                continue
            firsts.setdefault(m.first.lower(), []).append(m.id)
            pats.append((rf"{m.first}\s+{m.last}", m.id))
            pats.append((rf"{m.first}(?:'s)?\s+{m.last[0]}\b\.?", m.id))  # "Chris D", "Chris's K"
            for a in m.aliases:
                pats.append((rf"{a}\b", m.id))
        for first, ids in firsts.items():
            if len(ids) == 1:
                pats.append((rf"{first}\b", ids[0]))
        return [(re.compile(rf"^\s*{p}", re.I), mid) for p, mid in pats]

    def speaker_of(self, text: str, present: list[str] | None = None) -> str | None:
        """Guess which member a report is about from its first words.

        An ambiguous first name ("Jim") is settled by who was present, if only one was.
        """
        t = text.replace("’", "'")
        for pat, mid in self._speaker_patterns:
            if pat.match(t):
                return mid
        word = re.match(r"\s*([A-Za-z]+?)(?:'?s)?\b", t)
        if present and word:
            ids = [m.id for m in self.members.values()
                   if m.first.lower() == word.group(1).lower() and m.id in present]
            if len(ids) == 1:
                return ids[0]
        return None
