"""Tracked business items: the fix for follow-ups that get dropped.

Every Old/New Business line is an item with an optional owner and due date. An item stays in Old
Business every week until it's marked Done; it then appears once more, as done, in that night's
minutes. The minutes' Old and New Business sections are written from here:

  New Business  items opened at this meeting
  Old Business  items opened earlier that are still open (or were closed at this meeting)

An item can also be held for a later meeting ("on the agenda for Jan 7"): it stays out of the
minutes until that night. State is in business.json, each change in the item's own history.
The first use imports the last submitted minutes' Old and New Business, so nothing is lost.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import time

from .club import DATA, Club

MAX_TEXT = 600


def _path():
    return DATA / "business.json"


def load() -> dict:
    p = _path()
    s = json.loads(p.read_text()) if p.exists() else {}
    s.setdefault("items", [])
    s.setdefault("seeded", False)
    return s


def save(s: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def seed(s: dict, meetings: list, by: str | None = None) -> int:
    """Once: the last submitted minutes' Old + New Business become open items. Returns how many."""
    if s["seeded"]:
        return 0
    s["seeded"] = True
    last = next((m for m in meetings if m.status != "draft"), None)  # meetings are newest first
    if not last:
        return 0
    done = [m for m in meetings if m.status != "draft"]

    def norm(t: str) -> str:
        return " ".join(t.lower().split())

    def business_lines(m) -> set[str]:
        return {norm(i.text) for i in m.items("Old Business") + m.items("New Business")}
    for i in last.items("Old Business") + last.items("New Business"):
        # When it first came up: walk back while each earlier meeting still has the same line.
        opened = last.slug
        for m in done[done.index(last) + 1:]:
            if norm(i.text) not in business_lines(m):
                break
            opened = m.slug
        add(s, i.text, by, opened=opened, note="carried over from the minutes")
    return len(s["items"])


def get(s: dict, iid: str) -> dict:
    x = next((i for i in s["items"] if i["id"] == iid), None)
    if not x:
        raise ValueError("No such business item.")
    return x


def _date(v: str | None) -> str | None:
    if not v:
        return None
    try:
        return dt.date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{v} isn't a date.")


def _note(x: dict, by: str | None, what: str) -> None:
    x["history"].append({"at": int(time.time()), "by": by, "what": what})


def add(s: dict, text: str, by: str | None, owner: str | None = None, due: str | None = None,
        agenda: str | None = None, opened: str | None = None, note: str = "added") -> dict:
    text = " ".join(text.split())[:MAX_TEXT]
    if not text:
        raise ValueError("The item needs some text.")
    x = {"id": secrets.token_hex(5), "text": text, "owner": owner or None, "due": _date(due),
         "agenda": _date(agenda), "opened": _date(opened) or dt.date.today().isoformat(),
         "status": "open", "closed": None, "history": []}
    _note(x, by, note)
    s["items"].append(x)
    return x


def edit(s: dict, iid: str, by: str, **fields) -> dict:
    """Change text, owner, due or agenda (None/"" clears owner and dates)."""
    x = get(s, iid)
    changes = []
    for k, v in fields.items():
        if k == "text":
            v = " ".join((v or "").split())[:MAX_TEXT]
            if not v:
                raise ValueError("The item needs some text.")
        elif k in ("due", "agenda"):
            v = _date(v)
        elif k == "owner":
            v = v or None
        else:
            continue
        if x[k] != v:
            changes.append(k)
            x[k] = v
    if changes:
        _note(x, by, "changed " + ", ".join(changes))
    return x


def close(s: dict, iid: str, by: str, date: str | None = None) -> dict:
    x = get(s, iid)
    if x["status"] != "done":
        x["status"], x["closed"] = "done", _date(date) or dt.date.today().isoformat()
        _note(x, by, "marked done")
    return x


def reopen(s: dict, iid: str, by: str) -> dict:
    x = get(s, iid)
    if x["status"] == "done":
        x["status"], x["closed"] = "open", None
        _note(x, by, "reopened")
    return x


def remove(s: dict, iid: str, date: str) -> None:
    """Delete an item added by mistake: only at the meeting that opened it."""
    x = get(s, iid)
    if x["opened"] != date:
        raise ValueError("Only an item added at this meeting can be deleted; mark it done instead.")
    s["items"].remove(x)


def forget_meeting(s: dict, date: str) -> int:
    """A meeting deleted (practice run, test): drop the items it added and reopen the ones it closed."""
    before = len(s["items"])
    s["items"] = [x for x in s["items"] if x["opened"] != date]
    for x in s["items"]:
        if x["closed"] == date:
            x["status"], x["closed"] = "open", None
            _note(x, None, "reopened: the meeting that closed it was deleted")
    return before - len(s["items"])


# ---------------- what goes in a meeting ----------------

def for_meeting(s: dict, date: str, since: str | None = None) -> tuple[list[dict], list[dict]]:
    """(old, new) business items for the meeting on `date`. `since` is the previous meeting's date:
    items marked done between meetings show as done at this one."""
    def closed_here(x):
        c = x["closed"]
        return bool(c) and (since < c <= date if since else c == date)
    old = [x for x in s["items"] if x["opened"] < date and (
        (x["status"] == "open" and (not x["agenda"] or x["agenda"] <= date)) or closed_here(x))]
    new = [x for x in s["items"] if x["opened"] == date]
    key = lambda x: (x["opened"], s["items"].index(x))  # noqa: E731
    return sorted(old, key=key), sorted(new, key=key)


def line(club: Club, x: dict, date: str) -> str:
    """One bullet for the minutes: the text, who has it and by when, and Done if closed tonight."""
    meta = [club.short(x["owner"]) if x["owner"] else None,
            f"due {dt.date.fromisoformat(x['due']).strftime('%b %-d')}" if x["due"] else None]
    meta = [m for m in meta if m]
    out = x["text"] + (f" ({', '.join(meta)})" if meta and x["status"] == "open" else "")
    if x["closed"] and x["closed"] <= date:
        out += " Done."
    return out


def sections(s: dict, club: Club, date: str, since: str | None = None) -> dict[str, list[str]]:
    old, new = for_meeting(s, date, since)
    return {"Old Business": [line(club, x, date) for x in old], "New Business": [line(club, x, date) for x in new]}


def view(club: Club, x: dict, today: str) -> dict:
    """An item for the console and the Business page."""
    return {**x, "owner_name": club.name(x["owner"]) if x["owner"] else None,
            "overdue": bool(x["status"] == "open" and x["due"] and x["due"] < today)}
