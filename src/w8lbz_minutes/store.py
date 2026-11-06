"""Archive access: loads meetings from disk; full-text search, stats, guest tracking."""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from .club import MEETINGS, Club
from .meeting import Meeting


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


class Archive:
    def __init__(self, root: Path = MEETINGS, club: Club | None = None):
        self.root = root
        self.club = club or Club()
        self.reload()

    def reload(self) -> None:
        paths = sorted(self.root.glob("*/minutes.md"), reverse=True)
        self.meetings: list[Meeting] = [self._canonicalize(Meeting.load(p)) for p in paths]
        self.by_slug = {m.slug: m for m in self.meetings}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("create virtual table docs using fts5(slug unindexed, section unindexed, member unindexed, text, tokenize='porter')")
        rows = [
            (m.slug, sec, it.member or "", it.text)
            for m in self.meetings for sec, items in m.sections.items() for it in items
        ]
        rows += [(m.slug, "Guests", "", f"{g['name']} {g.get('callsign', '')} {g.get('notes', '')}")
                 for m in self.meetings for g in m.guests]
        self.db.executemany("insert into docs values (?,?,?,?)", rows)

    def _canonicalize(self, m: Meeting) -> Meeting:
        """Map ids stored under a member's old callsign to their current one."""
        c = self.club.canonical
        m.in_person = [c(x) for x in m.in_person]
        m.remote = [c(x) for x in m.remote]
        for items in m.sections.values():
            for it in items:
                if it.member:
                    it.member = c(it.member)
        return m

    def search(self, q: str, limit: int = 100) -> list[dict]:
        terms = re.findall(r"\w+", q)
        if not terms:
            return []
        fts = " ".join(f'"{t}"*' for t in terms)
        cur = self.db.execute(
            "select slug, section, member, snippet(docs, 3, '<mark>', '</mark>', ' … ', 24) "
            "from docs where docs match ? order by slug desc limit ?", (fts, limit))
        return [dict(slug=s, section=sec, member=mem, snippet=snip) for s, sec, mem, snip in cur]

    def member_history(self, mid: str) -> dict:
        present = [(m, "in person" if mid in m.in_person else "online")
                   for m in self.meetings if mid in m.in_person or mid in m.remote]
        reports = [(m, it) for m in self.meetings for it in m.items("Community Reports") if it.member == mid]
        return {"present": present, "reports": reports}

    def stats(self) -> dict:
        rows = [{"meeting": m, "in_person": len(m.in_person), "remote": len(m.remote),
                 "guests": len(m.guests) + m.visitors, "total": m.attendance + len(m.guests) + m.visitors}
                for m in self.meetings]
        per_member = defaultdict(lambda: {"in_person": 0, "remote": 0, "last": None})
        for m in self.meetings:
            for mid in m.in_person:
                per_member[mid]["in_person"] += 1
            for mid in m.remote:
                per_member[mid]["remote"] += 1
            for mid in m.in_person + m.remote:
                if per_member[mid]["last"] is None:
                    per_member[mid]["last"] = m.date  # meetings are newest first
        n = len(self.meetings) or 1
        members = sorted(
            ({"id": k, "name": self.club.name(k), **v, "total": v["in_person"] + v["remote"],
              "rate": (v["in_person"] + v["remote"]) / n} for k, v in per_member.items()),
            key=lambda r: -r["total"])
        avg = sum(r["total"] for r in rows) / n
        return {"rows": rows, "members": members, "avg": avg, "count": len(self.meetings)}

    def guests(self) -> list[dict]:
        """Group guest visits by callsign, else by normalized name. Flag guests who later became members."""
        groups: dict[str, dict] = {}
        callsign_of = {_norm(g["name"]): g["callsign"]
                       for m in self.meetings for g in m.guests if g.get("callsign")}
        for m in sorted(self.meetings, key=lambda m: m.date):
            for g in m.guests:
                nk = _norm(g["name"])
                key = g.get("callsign") or callsign_of.get(nk) or nk
                grp = groups.setdefault(key, {"name": g["name"], "callsign": None, "visits": []})
                grp["callsign"] = grp["callsign"] or g.get("callsign")
                grp["visits"].append((m.date, g.get("notes", "")))
        for grp in groups.values():
            grp["member"] = self._member_for_guest(grp)
            if grp["member"]:
                first_member = min((m.date for m in self.meetings
                                    if grp["member"] in m.in_person + m.remote), default=None)
                grp["joined"] = first_member
        return sorted(groups.values(), key=lambda g: (-len(g["visits"]), g["name"]))

    def _member_for_guest(self, grp: dict) -> str | None:
        for m in self.club.members.values():
            if grp["callsign"] and m.callsign == grp["callsign"]:
                return m.id
            lasts = [m.last] + m.aliases
            if any(_norm(f"{m.first}{l}") == _norm(grp["name"]) for l in lasts):
                return m.id
        return None
