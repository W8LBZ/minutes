"""A meeting's minutes: Markdown file with YAML front matter.

The front matter holds structured data (date, attendance, guests, status).
The body holds one `## Section` per agenda section, each item a bullet.
Community report bullets may carry an invisible `<!-- member: id -->` tag.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SECTIONS = [
    "Bills and Communications",
    "Financial Report",
    "Community Reports",
    "Old Business",
    "New Business",
    "Winners",
    "Upcoming Chow",
    "Upcoming Events",
]

MEMBER_TAG = re.compile(r"\s*<!--\s*member:\s*([\w-]+)\s*-->")


@dataclass
class Item:
    text: str
    member: str | None = None  # roster id, community reports only


@dataclass
class Meeting:
    date: dt.date
    status: str = "draft"  # draft | imported | published
    version: int = 1
    leader: str | None = None
    source: str | None = None  # original file name, if imported
    note: str | None = None  # e.g. import warnings for the reviewer
    in_person: list[str] = field(default_factory=list)
    remote: list[str] = field(default_factory=list)
    guests: list[dict] = field(default_factory=list)  # {name, callsign}
    visitors: int = 0  # guests counted but not named (e.g. family, minors)
    sections: dict[str, list[Item]] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.date.isoformat()

    @property
    def attendance(self) -> int:
        return len(self.in_person) + len(self.remote)

    def items(self, section: str) -> list[Item]:
        return self.sections.get(section, [])

    # ---- serialization ----
    def to_markdown(self) -> str:
        fm = {
            "date": self.date,
            "status": self.status,
            "version": self.version,
            "leader": self.leader,
            "source": self.source,
            "note": self.note,
            "attendance": {"in_person": self.in_person, "remote": self.remote},
            "guests": self.guests,
            "visitors": self.visitors,
        }
        fm = {k: v for k, v in fm.items() if v not in (None, [], {}, 0)}
        out = ["---", yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip(), "---", ""]
        for name in SECTIONS:
            out.append(f"## {name}")
            for it in self.items(name):
                tag = f" <!-- member: {it.member} -->" if it.member else ""
                out.append(f"- {it.text}{tag}")
            out.append("")
        return "\n".join(out)

    @classmethod
    def from_markdown(cls, text: str) -> "Meeting":
        _, fm_text, body = text.split("---", 2)
        fm = yaml.safe_load(fm_text) or {}
        att = fm.get("attendance") or {}
        m = cls(
            date=fm["date"],
            status=fm.get("status", "draft"),
            version=fm.get("version", 1),
            leader=fm.get("leader"),
            source=fm.get("source"),
            note=fm.get("note"),
            in_person=att.get("in_person") or [],
            remote=att.get("remote") or [],
            guests=fm.get("guests") or [],
            visitors=fm.get("visitors", 0),
        )
        current = None
        for line in body.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                m.sections.setdefault(current, [])
            elif current and line.startswith("- "):
                text = line[2:]
                tag = MEMBER_TAG.search(text)
                member = tag.group(1) if tag else None
                text = MEMBER_TAG.sub("", text).strip()
                m.sections[current].append(Item(text, member))
            elif current and line.strip() and m.sections[current]:
                # continuation line of the previous bullet
                m.sections[current][-1].text += " " + line.strip()
        return m

    def save(self, root: Path) -> Path:
        d = root / self.slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / "minutes.md"
        p.write_text(self.to_markdown())
        return p

    @classmethod
    def load(cls, path: Path) -> "Meeting":
        return cls.from_markdown(path.read_text())
