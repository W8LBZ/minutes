"""Club config and roster (club.yaml for now; Google Sheet sync later)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("W8LBZ_ROOT", Path(__file__).resolve().parents[2]))
DATA = Path(os.environ.get("W8LBZ_DATA", ROOT / "data"))
MEETINGS = DATA / "meetings"


def _n(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


@dataclass
class Member:
    id: str
    first: str
    last: str
    short: str | None = None
    callsign: str | None = None
    role: str | None = None
    status: str = "active"
    aliases: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()


class Club:
    """Local club config (club.yaml, never in git). Roster entries here are a stopgap until the
    Google Sheet sync (FR-35a); the sheet will be the only source of truth for people."""

    def __init__(self, path: Path = Path(os.environ.get("W8LBZ_CONFIG", ROOT / "club.yaml"))):
        cfg = yaml.safe_load(path.read_text())
        self.info = cfg.get("club", {})
        self.links = cfg.get("links", [])
        self.leaders = cfg.get("leaders", [])
        self.editors = cfg.get("editors", [])
        self.redact = [_n(x) for x in (cfg.get("privacy") or {}).get("never_record", [])]
        self.members = {mid: Member(id=mid, **(v or {})) for mid, v in cfg.get("members", {}).items()}

    def is_redacted(self, text: str) -> bool:
        t = _n(text)
        return any(r and r in t for r in self.redact)

    def name(self, mid: str | None) -> str:
        m = self.members.get(mid or "")
        return m.name if m else (mid or "")

    def short(self, mid: str) -> str:
        m = self.members.get(mid)
        return (m.short or m.first or m.last) if m else mid

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
