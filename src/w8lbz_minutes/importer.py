"""Import historical minutes (PDF, or corrected .txt) into the Markdown archive.

The old minutes use a fixed set of headings, so this is a plain parser. No LLM.
Imported meetings get status "imported" until someone reviews them.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path

import pypdf

from .club import MEETINGS, Club
from .meeting import Item, Meeting

HEADINGS = {
    "Members Present": None,
    "Guests": None,
    "Bills and Communications": "Bills and Communications",
    "Financial Report": "Financial Report",
    "Committee Reports": "Community Reports",
    "Old Business": "Old Business",
    "New Business": "New Business",
    "The Winners": "Winners",
    "Upcoming Chow Dates": "Upcoming Chow",
    "Upcoming Events": "Upcoming Events",
}
HEAD_RE = re.compile(r"^(%s):\s*(.*)$" % "|".join(map(re.escape, HEADINGS)))
DATE_RE = re.compile(r"Date:?\s*(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})")
ATTEND_RE = re.compile(r"([A-Z][A-Za-z']+)\s*_+\s*([TtXx])?")
CALLSIGN_RE = re.compile(r"\b([A-Z]{1,3}\d{1,2}[A-Z]{1,4}|W[A-Z]{3}\d{3})\b")  # ham, or GMRS like WRXS650
NAME_RE = re.compile(r"^([A-Z][\w'.-]*(?:\s+[A-Z][a-z][\w'.-]*)*)")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def pdf_text(path: Path) -> str:
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)


def paragraphs(lines: list[str]) -> list[str]:
    """Blank lines separate paragraphs; wrapped lines are joined."""
    out, cur = [], []
    for ln in lines + [""]:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            out.append(re.sub(r"\s+", " ", " ".join(cur)).replace(" ,", ","))
            cur = []
    return out


def parse(text: str, club: Club) -> Meeting:
    text = text.replace("’", "'").replace(" ", " ")
    d = DATE_RE.search(text)
    if not d:
        raise ValueError("no date found")
    date = dt.date(int(d.group(3)), MONTHS[d.group(2)[:3].lower()], int(d.group(1)))
    m = Meeting(date=date, status="imported")

    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        h = HEAD_RE.match(line.strip())
        if h:
            current = h.group(1)
            blocks[current] = [h.group(2)] if h.group(2).strip() else []
        elif current:
            blocks[current].append(line)

    # Attendance: stop at the Teams link / legend.
    att = []
    for ln in blocks.get("Members Present", []):
        if re.match(r"\s*(https?://|T=Teams)", ln):
            break
        att.append(ln)
    for surname, mark in ATTEND_RE.findall(" ".join(att)):
        mid = club.resolve_surname(surname) or surname.lower()
        if mark.lower() == "x":
            m.in_person.append(mid)
        elif mark.lower() == "t":
            m.remote.append(mid)

    for ln in blocks.get("Guests", []):  # one guest per line
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or ln.startswith("T=Teams"):
            continue
        cs = CALLSIGN_RE.search(ln)
        nm = NAME_RE.match(ln)
        name = nm.group(1) if nm else ln
        notes = ln[len(name):]
        if cs:
            notes = notes.replace(cs.group(1), "")
        g = {"name": name}
        if cs:
            g["callsign"] = cs.group(1)
        if notes.strip(" ,-\u2013"):
            g["notes"] = notes.strip(" ,-\u2013")
        m.guests.append(g)
    m.guests = [g for g in m.guests if not club.is_redacted(g["name"])]

    for head, section in HEADINGS.items():
        if not section:
            continue
        paras = paragraphs(blocks.get(head, []))
        if section == "Financial Report":
            leftover = re.sub(r"Checking|Emergency Fund|Maintenance Fund|Cash|Beverage Fund|Savings|[\s$:\-\u2013]", "", " ".join(paras))
            if not leftover:
                paras = []  # the empty template, not real figures
        if section == "Upcoming Chow":
            paras = [p for p in paras if not re.fullmatch(r"see attached( chow)? list", p, re.I)]
        items = []
        for p in paras:
            if club.is_redacted(p):
                continue
            items.append(Item(p, club.speaker_of(p, m.in_person + m.remote) if section == "Community Reports" else None))
        m.sections[section] = items
    return m


FILE_DATE_RE = re.compile(r"^(\d{1,2})-([a-z]+)-(\d{2})-minutes")


def file_date(name: str) -> dt.date | None:
    f = FILE_DATE_RE.match(name.lower())
    if f and f.group(2)[:3] in MONTHS:
        return dt.date(2000 + int(f.group(3)), MONTHS[f.group(2)[:3]], int(f.group(1)))
    return None


def _fix_date(m: Meeting, name: str) -> None:
    """The Date line is sometimes left over from last week's copy; trust the file name."""
    fd = file_date(name)
    if fd and fd != m.date:
        m.note = f"Date line in the original said {m.date:%-d %b %Y}; using the file name date."
        m.date = fd


def import_archive(src: Path, club: Club | None = None, dest: Path = MEETINGS) -> list[Meeting]:
    club = club or Club()
    done = []
    for f in sorted(src.glob("*.pdf")):
        text = pdf_text(f)
        m = parse(text, club)
        m.source = f.name
        _fix_date(m, f.name)
        m.save(dest)
        if not club.is_redacted(text):  # never serve an original that contains a never-record name
            shutil.copy2(f, dest / m.slug / "original.pdf")
        done.append(m)
    # Corrected text versions take precedence over the PDF of the same date.
    for f in sorted(src.glob("*CORRECTED*.txt")):
        m = parse(f.read_text(), club)
        m.source = f.name
        _fix_date(m, f.name)
        m.note = "Corrected version (from the Corrected minutes email); images not included."
        m.save(dest)
    return done
