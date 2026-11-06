"""Members' own profile edits: written to the roster sheet, logged, and the Secretary told.

Every change is appended to profile-changes.jsonl (readable only by the app) with the
old and new values, so an officer can undo it. The roster cache and the running app
are updated at once; the daily sync then reads the same values back from the sheet.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time

from . import auth
from .club import DATA, ROSTER_CACHE, Club
from .roster import EDITABLE, Sheet

log = logging.getLogger("w8lbz.profile")
LABELS = {"email": "Email", "phone": "Phone", "address": "Address", "birthday": "Birthday", "share": "Shared with members"}


def log_path():
    return DATA / "profile-changes.jsonl"


def as_cell(fld: str, value) -> str:
    return ", ".join(value) if fld == "share" else (value or "")


def history(limit: int = 200) -> list[dict]:
    p = log_path()
    if not p.exists():
        return []
    entries = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    undone = {e["undoes"] for e in entries if e.get("undoes")}
    for e in entries:
        e["undone"] = e["id"] in undone
    return entries[::-1][:limit]


def _append(entry: dict) -> None:
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    os.chmod(p, 0o600)


def _apply_locally(club: Club, mid: str, new: dict[str, str]) -> None:
    """Update the running app and the roster cache so the change shows before the next sync."""
    m = club.members[mid]
    for fld, v in new.items():
        setattr(m, fld, [x for x in v.split(", ") if x] if fld == "share" else (v or None))
    if ROSTER_CACHE.exists():
        rows = json.loads(ROSTER_CACHE.read_text())
        for r in rows:
            if r["id"] == mid:
                r.update({f: getattr(m, f) for f in new})
        tmp = ROSTER_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1))
        tmp.chmod(0o600)
        tmp.replace(ROSTER_CACHE)


def change(club: Club, mid: str, new: dict[str, str], by: str, sheet: Sheet | None = None,
           url: str = "", undoes: str | None = None) -> dict | None:
    """Write a member's changed fields (field -> cell text) to the sheet, log them, tell the Secretary.

    Returns the log entry, or None if nothing changed. Raises roster.SheetError if the
    sheet can't be written; then nothing is changed anywhere.
    """
    m = club.members[mid]
    new = {f: v for f, v in new.items() if f in EDITABLE and v != as_cell(f, getattr(m, f))}
    if not new:
        return None
    old = (sheet or Sheet()).update_member(m.callsign, m.name, new)
    _apply_locally(club, mid, new)
    entry = {"id": secrets.token_hex(6), "at": int(time.time()), "member": mid, "by": by,
             "old": old, "new": new, "undoes": undoes}
    _append(entry)
    log.info("profile change %s for %s by %s: %s", entry["id"], mid, by, ", ".join(new))
    _notify(club, entry, url)
    return entry


def undo(club: Club, change_id: str, by: str, sheet: Sheet | None = None, url: str = "") -> dict:
    """Put back the old values of a change, unless the member has changed those fields again since."""
    e = next((x for x in history(10_000) if x["id"] == change_id), None)
    if not e or e["undone"] or e.get("undoes"):
        raise ValueError("That change can't be undone.")
    m = club.members[e["member"]]
    if any(as_cell(f, getattr(m, f)) != v for f, v in e["new"].items()):
        raise ValueError("Those details have been changed again since; edit them on the roster sheet instead.")
    return change(club, e["member"], e["old"], by, sheet, url, undoes=change_id)


def _notify(club: Club, e: dict, url: str) -> None:
    """Tell the Secretary, and the member whose details changed (old and new addresses, if the email changed)."""
    who, by = club.name(e["member"]), club.name(e["by"])

    def show(v):
        return (v or "(blank)").replace("\n", " / ")
    what = "\n".join(f"  {LABELS[f]}: {show(e['old'].get(f))}  ->  {show(v)}" for f, v in e["new"].items())
    action = f"{by} undid an earlier change to {who}'s roster details" if e.get("undoes") else (
        f"{who} updated their roster details" if e["by"] == e["member"] else f"{by} updated {who}'s roster details")
    secretaries = [club.members[s].email for s in club.secretaries if s != e["by"] and club.members[s].email]
    _send(club, secretaries, f"Roster update: {who}",
          f"{action}. The roster sheet has been updated.\n\n{what}\n\n"
          f"If this looks wrong, any officer can undo it here: {url}/roster/changes\n\n73,\nW8LBZ Minutes", e)

    m = club.members[e["member"]]
    member_to = [a for a in dict.fromkeys([m.email, e["old"].get("email")]) if a]  # both, after an email change
    you = "You" if e["by"] == e["member"] else by
    _send(club, member_to, "Your W8LBZ roster details were updated",
          f"Hi {m.first},\n\n{you} updated your details on the club roster:\n\n{what}\n\n"
          f"You can see and change them on your profile: {url}/profile\n"
          f"If you didn't expect this, reply to this email or tell an officer.\n\n73,\nW8LBZ Minutes", e)


def _send(club: Club, to: list[str], subject: str, body: str, e: dict) -> None:
    if not to:
        return
    try:
        auth.send_email(to, subject, body, only_to=club.email_only_to())
    except Exception:
        log.exception("couldn't send %r about change %s", subject, e["id"])
