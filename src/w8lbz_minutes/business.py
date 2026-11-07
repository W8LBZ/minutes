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

import contextlib
import datetime as dt
import fcntl
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
    s.setdefault("suggestions", [])  # from the AI (ai.py); pending until a leader accepts or dismisses
    s.setdefault("notes", [])        # members' notes for an upcoming meeting (can't make it, news to pass on)
    return s


def save(s: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


@contextlib.contextmanager
def locked():
    """Held around load-change-save, by the web app and the daily reminders job alike (they're separate processes)."""
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "business.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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


def _note(x: dict, by: str | None, what: str, **detail) -> None:
    x["history"].append({"at": int(time.time()), "by": by, "what": what, **detail})


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


def edit(s: dict, iid: str, by: str, meeting: str | None = None, **fields) -> dict:
    """Change text, owner, due or agenda (None/"" clears owner and dates). Each change keeps the old
    and new value in the item's history, with the meeting it was made at (if any)."""
    x = get(s, iid)
    changes = {}
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
            changes[k] = [x[k], v]
            x[k] = v
    if changes:
        _note(x, by, "changed " + ", ".join(changes), changes=changes, **({"meeting": meeting} if meeting else {}))
    return x


MAX_COMMENT = 1000


def comment(s: dict, iid: str, by: str, text: str) -> dict:
    """Any member can add a comment to an open item (an update, a question); it's shown with the item."""
    x = get(s, iid)
    text = text.strip()[:MAX_COMMENT]
    if not text:
        raise ValueError("The comment is empty.")
    c = {"id": secrets.token_hex(4), "at": int(time.time()), "by": by, "text": text}
    x.setdefault("comments", []).append(c)
    return c


def delete_comment(s: dict, iid: str, cid: str, by: str, leader: bool) -> None:
    x = get(s, iid)
    c = next((c for c in x.get("comments", []) if c["id"] == cid), None)
    if not c or not (leader or c["by"] == by):
        raise ValueError("You can only delete your own comments.")
    x["comments"].remove(c)


# ---------------- notes for an upcoming meeting ----------------

def add_note(s: dict, by: str, text: str, meeting: str) -> dict:
    """A member's note for a meeting: e.g. they can't make it, and here's their news."""
    text = text.strip()[:MAX_COMMENT]
    if not text:
        raise ValueError("The note is empty.")
    n = {"id": secrets.token_hex(4), "at": int(time.time()), "by": by, "text": text,
         "meeting": _date(meeting), "status": "pending"}
    s["notes"].append(n)
    return n


def note_status(s: dict, nid: str, status: str, by: str, leader: bool) -> dict:
    """pending -> read (added to the minutes) or dismissed; the author can withdraw a pending note."""
    n = next((n for n in s["notes"] if n["id"] == nid), None)
    if not n:
        raise ValueError("No such note.")
    if status == "withdrawn":
        if n["by"] != by or n["status"] != "pending":
            raise ValueError("Only your own note, before the meeting uses it.")
        s["notes"].remove(n)
        return n
    if not leader:
        raise ValueError("Only the meeting's leader can do that.")
    n["status"], n["handled_by"] = status, by
    return n


def notes_for(s: dict, meeting: str) -> list[dict]:
    """Pending notes for this meeting, and any left over from earlier ones."""
    return [n for n in s["notes"] if n["status"] == "pending" and n["meeting"] <= meeting]


def close(s: dict, iid: str, by: str, date: str | None = None) -> dict:
    x = get(s, iid)
    if x["status"] != "done":
        x["status"], x["closed"] = "done", _date(date) or dt.date.today().isoformat()
        _note(x, by, "marked done", **({"meeting": date} if date else {}))
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


# ---------------- AI suggestions: never applied until a person accepts them ----------------

def add_suggestions(s: dict, meeting: str, found: list[dict], model: str) -> int:
    """Store suggestions for a meeting, replacing that meeting's earlier pending ones."""
    s["suggestions"] = [x for x in s["suggestions"] if not (x["meeting"] == meeting and x["status"] == "pending")]
    for f in found:
        s["suggestions"].append({"id": secrets.token_hex(5), "meeting": meeting, "status": "pending",
                                 "model": model, "at": int(time.time()), **f})
    return len(found)


def accept_suggestion(s: dict, sid: str, by: str, text: str | None = None, owner: str | None = None,
                      due: str | None = None) -> dict:
    """The leader's (possibly edited) version of a suggestion becomes a tracked item, or updates one."""
    g = next((x for x in s["suggestions"] if x["id"] == sid and x["status"] == "pending"), None)
    if not g:
        raise ValueError("That suggestion was already handled.")
    text = g["text"] if text is None else text
    owner = g["owner"] if owner is None else owner
    due = g["due"] if due is None else due
    if g["kind"] == "update":
        x = edit(s, g["item"], by, owner=owner, due=due)
        _note(x, by, "owner/due from an AI suggestion, accepted")
    else:
        x = add(s, text, by, owner=owner, due=due, opened=g["meeting"], note="added from an AI suggestion")
    g["status"], g["result"] = "accepted", x["id"]
    return x


def dismiss_suggestion(s: dict, sid: str, by: str) -> None:
    g = next((x for x in s["suggestions"] if x["id"] == sid and x["status"] == "pending"), None)
    if not g:
        raise ValueError("That suggestion was already handled.")
    g["status"], g["by"] = "dismissed", by


QUIET_WEEKS = 6


def quiet(x: dict, today: str) -> bool:
    """Open, and nothing has changed for QUIET_WEEKS weeks: worth asking about."""
    last = max([h["at"] for h in x["history"]] + [c["at"] for c in x.get("comments", [])], default=0)
    return x["status"] == "open" and (dt.date.fromisoformat(today) - dt.date.fromtimestamp(last)).days >= 7 * QUIET_WEEKS


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


def view(club: Club, x: dict, today: str, since: str | None = None) -> dict:
    """An item for the console and the Business page. `since`: the previous meeting, for "new comments"."""
    cutoff = dt.datetime.fromisoformat(since).timestamp() if since else 0  # from that meeting's day on
    return {**x, "new_comments": [{**c, "name": club.short(c["by"])} for c in x.get("comments", []) if c["at"] >= cutoff],
            "owner_name": club.name(x["owner"]) if x["owner"] else None,
            "overdue": bool(x["status"] == "open" and x["due"] and x["due"] < today), "quiet": quiet(x, today)}


# ---------------- reminders (the daily job: `w8lbz-minutes reminders`) ----------------

def due_reminders(s: dict, today: dt.date, days_before: int = 3) -> dict[str, list[tuple[dict, str]]]:
    """Owner -> [(item, "soon" | "overdue")] not yet reminded. Each item gets at most one "soon"
    reminder (within days_before of its due date) and one "overdue" reminder (the day after)."""
    out: dict[str, list[tuple[dict, str]]] = {}
    for x in s["items"]:
        if x["status"] != "open" or not x["owner"] or not x["due"]:
            continue
        due = dt.date.fromisoformat(x["due"])
        sent = x.setdefault("reminded", {})
        if due < today and sent.get("overdue") != x["due"]:
            kind = "overdue"
        elif today <= due <= today + dt.timedelta(days=days_before) and sent.get("soon") != x["due"]:
            kind = "soon"
        else:
            continue
        out.setdefault(x["owner"], []).append((x, kind))
    return out


def reminder_email(club: Club, mid: str, items: list[tuple[dict, str]], today: dt.date, url: str) -> tuple[str, str]:
    m = club.members[mid]

    def when(x, kind):
        due = dt.date.fromisoformat(x["due"])
        if kind == "overdue":
            return f"was due {due.strftime('%A, %B %-d')}"
        days = (due - today).days
        return f"due {due.strftime('%A, %B %-d')}" + (" (today)" if days == 0 else " (tomorrow)" if days == 1 else "")
    late = any(k == "overdue" for _, k in items)
    lines = "\n".join(f"- {x['text']}\n  {when(x, k)}" for x, k in items)
    subject = f"{club.info.get('callsign', 'W8LBZ')} club business: " + ("past due" if late else "coming due")
    body = (f"Hi {m.first},\n\nA reminder about club business you're looking after:\n\n{lines}\n\n"
            f"If it's finished, mark it done (or change the date) here: {url}/business\n"
            f"Or just bring it up at the next meeting.\n\n73,\n{club.info.get('callsign', 'W8LBZ')} Minutes")
    return subject, body


def mark_reminded(items: list[tuple[dict, str]]) -> None:
    for x, kind in items:
        x.setdefault("reminded", {})[kind] = x["due"]
