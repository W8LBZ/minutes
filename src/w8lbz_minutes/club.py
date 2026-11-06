"""Club config and people.

People come only from the roster Google Sheet (synced to data/roster.json by
`w8lbz-minutes roster`). club.yaml (local only, never in git) holds app settings.
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


CALLSIGN = re.compile(r"^[A-Z]{1,2}\d[A-Z]{1,3}$", re.I)


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
    minutes_editor: bool = False  # may lead meetings and edit minutes (officers always may)
    status: str = "Active"
    aliases: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # from the Membership Log tab
    member_since: str | None = None
    phone: str | None = None
    address: str | None = None
    birthday: str | None = None  # MM-DD
    share: list[str] = field(default_factory=list)  # fields shown to all members (officers see everything)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()


class Club:
    def __init__(self, path: Path | None = None, roster: list[dict] | None = None):
        path = path or Path(os.environ.get("W8LBZ_CONFIG", ROOT / "club.yaml"))
        cfg = yaml.safe_load(path.read_text()) or {}
        self.info = cfg.get("club", {})
        self.links = cfg.get("links", [])
        self.auth = cfg.get("auth") or {}
        self.email = cfg.get("email") or {}
        self.redact = [_n(x) for x in (cfg.get("privacy") or {}).get("never_record", [])]

        if roster is None and "members" in cfg:  # inline members (tests, example config)
            roster = [{"id": k, **(v or {})} for k, v in cfg["members"].items()]
        if roster is None and ROSTER_CACHE.exists():
            roster = json.loads(ROSTER_CACHE.read_text())
        known = {f.name for f in fields(Member)}
        self.members: dict[str, Member] = {}
        for d in roster or []:
            self.members[d["id"]] = Member(**{k: v for k, v in d.items() if k in known})
        self._auto_short_names()
        # A former callsign (e.g. before a vanity change) listed in aliases maps to the member.
        self.former_ids = {a.lower(): m.id for m in self.members.values()
                           for a in m.aliases if CALLSIGN.match(a)}
        for m in self.members.values():  # callsign aliases aren't name spellings
            m.aliases = [a for a in m.aliases if not CALLSIGN.match(a)]

    def canonical(self, mid: str) -> str:
        """Current id for a member id that may be an old callsign."""
        return self.former_ids.get(mid, mid)

    def _auto_short_names(self) -> None:
        """'Chris D' / 'Chris K' style names when a first name is shared."""
        by_first: dict[str, list[Member]] = {}
        for m in self.members.values():
            by_first.setdefault(m.first.lower(), []).append(m)
        for group in by_first.values():
            for m in group:
                if not m.short and len(group) > 1 and m.last:
                    m.short = f"{m.first} {m.last[0]}"

    def email_only_to(self) -> set[str] | None:
        """Test mode: if club.yaml has email.only_to (callsigns or addresses), mail goes only to them."""
        only = self.email.get("only_to")
        if only is None:
            return None
        out = set()
        for x in only:
            m = self.members.get(str(x).lower())
            addr = m.email if m else str(x)
            if addr and "@" in addr:
                out.add(addr.strip().lower())
        return out

    # ---- permissions ----
    def can_lead(self, mid: str) -> bool:
        """Officers and members ticked minutes_editor may lead a meeting and edit minutes."""
        m = self.members.get(mid)
        return bool(m and (m.officer or m.minutes_editor))

    can_edit = can_lead

    def can_see(self, viewer: str | None, mid: str, fld: str) -> bool:
        """Contact details: officers and the member always; other members only what was shared."""
        v, m = self.members.get(viewer or ""), self.members.get(mid)
        return bool(m and v and (v.officer or v.id == m.id or fld in m.share))

    @property
    def secretaries(self) -> list[str]:
        """Members whose title includes Secretary (they keep the roster, bylaws IV.C)."""
        return [m.id for m in self.members.values() if m.role and "secretary" in m.role.lower()]

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
            pats.append((rf"{m.first}(?:'?s)?\s+{m.last}", m.id))
            pats.append((rf"{m.first}(?:'s)?\s+{m.last[0]}\b\.?", m.id))  # "Chris D", "Chris's K"
            for a in m.aliases:
                pats.append((rf"{a}\b", m.id))
        for first, ids in firsts.items():
            if len(ids) == 1:
                pats.append((rf"{first}(?:'?s)?\b", ids[0]))  # "Mike", "Mikes", "Mike's"
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
