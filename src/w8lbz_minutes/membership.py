"""Adding a new member: a row on the roster sheet, a "Joined" row on its Membership Log tab, and the app
updated at once (the nightly sync then reads the same values back). Guests who've come often enough to be
invited are offered as a starting point.

Only cell values are written, into the first empty row of each tab; rows are never inserted.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

from . import auth, chow, profile
from .club import ROSTER_CACHE, Club
from .roster import Sheet, SheetError

log = logging.getLogger("w8lbz.membership")
CLASSES = ("Technician", "General", "Amateur Extra")
LOG_TAB = "Membership Log"


def ready_guests(guests: list[dict], invite_after: int) -> list[dict]:
    """Guests who aren't members yet and have visited at least invite_after times, most visits first."""
    return [g for g in guests if not g.get("member") and len(g["visits"]) >= invite_after]


def split_name(name: str) -> tuple[str, str]:
    first, _, last = name.strip().rpartition(" ")
    return (first, last) if first else (last, "")


def clean(form: dict) -> dict:
    f = {k: (form.get(k) or "").strip() for k in ("first", "last", "callsign", "email", "phone", "address",
                                                    "license_class", "joined")}
    f["callsign"] = f["callsign"].upper()
    f["address"] = "\n".join(line.strip() for line in f["address"].splitlines() if line.strip())
    if not f["first"] or not f["last"]:
        raise ValueError("First and last name are both needed.")
    # Membership needs an amateur license (no associate members in the bylaws yet).
    if not f["callsign"] or not f["license_class"]:
        raise ValueError("A callsign and license class are needed: members must be licensed.")
    if not re.fullmatch(r"[A-Z0-9]{3,7}", f["callsign"]):
        raise ValueError(f"{f['callsign']} doesn't look like a callsign.")
    if f["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
        raise ValueError(f"{f['email']} doesn't look like an email address.")
    if f["license_class"] not in CLASSES:
        raise ValueError("Unknown license class.")
    try:
        f["joined"] = dt.date.fromisoformat(f["joined"]).isoformat() if f["joined"] else dt.date.today().isoformat()
    except ValueError:
        raise ValueError("The joined date isn't a date.")
    return f


def add_member(club: Club, form: dict, by: str, sheet: Sheet | None = None, url: str = "") -> str:
    """Add a member to the roster sheet and the app. Returns their id. Raises ValueError or SheetError."""
    f = clean(form)
    name = f"{f['first']} {f['last']}"
    for m in club.members.values():
        if f["callsign"] and m.callsign == f["callsign"]:
            raise ValueError(f"{f['callsign']} is already on the roster ({m.name}).")
        if not f["callsign"] and m.name.lower() == name.lower():
            raise ValueError(f"{name} is already on the roster.")
    sheet = sheet or Sheet()
    sheet.add_row({"callsign": f["callsign"], "full_name": name, "email": f["email"], "phone": f["phone"],
                   "address": f["address"], "class": f["license_class"], "status": "Active"},
                  optional=("phone", "address", "class"))
    try:
        sheet.add_row({"callsign": f["callsign"], "full_name": name, "date": f["joined"], "event": "Joined",
                       "note": f"Added in the app by {club.name(by)}"}, tab=LOG_TAB, optional=("note", "callsign"))
    except SheetError as e:  # the roster row is the part that matters
        log.warning("new member %s: Membership Log not written: %s", name, e)

    mid = f["callsign"].lower() or re.sub(r"[^a-z]+", "-", name.lower()).strip("-")
    rows = json.loads(ROSTER_CACHE.read_text()) if ROSTER_CACHE.exists() else []
    rows.append({"id": mid, "first": f["first"], "last": f["last"], "callsign": f["callsign"] or None,
                 "email": f["email"] or None, "role": None, "officer": False, "board": False,
                 "license_class": f["license_class"] or None, "aliases": [], "minutes_editor": False,
                 "status": "Active", "phone": f["phone"] or None, "address": f["address"] or None,
                 "birthday": None, "share": [], "member_since": f["joined"],
                 "events": [{"date": f["joined"], "event": "Joined", "note": None}]})
    ROSTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROSTER_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1))
    tmp.chmod(0o600)
    tmp.replace(ROSTER_CACHE)
    club._load(rows)

    # New members join the chow rotation at the end of the current round (an officer can move or remove them).
    s = chow.load()
    if mid not in s["order"]:
        chow.add_to_rotation(club, s, mid, by)
        chow.save(s)

    # Who added them: in Recent changes (here), the Membership Log note (sheet) and the Secretary's email.
    profile.log_added(mid, by, {k: f[k] for k in ("callsign", "email", "phone", "address", "license_class", "joined") if f[k]})
    log.info("new member %s (%s) added by %s", name, mid, by)
    to = [club.members[x].email for x in club.secretaries if x != by and club.members[x].email]
    if to:
        try:
            auth.send_email(to, f"New member: {name}",
                            f"{club.name(by)} added {name}{f' ({f['callsign']})' if f['callsign'] else ''} to the roster, "
                            f"joined {f['joined']}. The roster sheet and its Membership Log have a new row.\n\n"
                            f"{url}/members/{mid}\n\n73,\nW8LBZ Minutes", only_to=club.email_only_to())
        except Exception:
            log.exception("couldn't email the Secretary about new member %s", mid)
    return mid
