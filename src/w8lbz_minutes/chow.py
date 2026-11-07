"""Chow list: who brings the snack on each meeting night. The app is the source of truth.

State lives in chow.json in the data directory; every change is appended to chow-log.jsonl.

- Nights: date -> member, plus status: scheduled (default), provided, missed, covered (someone else
  brought it, e.g. a "pizza bomb" delivered by a member who wasn't there; not a miss), or none
  (no chow that night, e.g. a holiday).
- Rotation: the same order every round; new members go to the bottom. Members waiting to be added
  (`pending`) aren't scheduled until a leader adds them.
- Constraints: weeks of the month a member can't do, and date ranges they're away.
- Swaps: a member asks another to trade nights; the other approves or declines. Leaders can swap or
  assign directly. Changes made on a night with a draft meeting are added to its minutes on Submit.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import secrets
import time
from pathlib import Path

from . import auth
from .club import DATA, Club

log = logging.getLogger("w8lbz.chow")
STATUSES = ("scheduled", "provided", "missed", "covered", "none")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _path() -> Path:
    return DATA / "chow.json"


def load() -> dict:
    p = _path()
    s = json.loads(p.read_text()) if p.exists() else {}
    for k, v in (("nights", {}), ("order", []), ("pending", []), ("constraints", {}), ("swaps", [])):
        s.setdefault(k, v)
    return s


def save(s: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1, sort_keys=True))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def history(limit: int = 500) -> list[dict]:
    p = DATA / "chow-log.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()][::-1][:limit]


def _log(action: str, by: str, **details) -> dict:
    e = {"id": secrets.token_hex(5), "at": int(time.time()), "action": action, "by": by, **details}
    p = DATA / "chow-log.jsonl"
    with p.open("a") as f:
        f.write(json.dumps(e) + "\n")
    os.chmod(p, 0o600)
    return e


def night(s: dict, date: str) -> dict:
    return s["nights"].setdefault(date, {"member": None, "status": "scheduled"})


def upcoming(s: dict, today: dt.date | None = None, n: int = 12) -> list[tuple[str, dict]]:
    today = (today or dt.date.today()).isoformat()
    return [(d, x) for d, x in sorted(s["nights"].items()) if d >= today][:n]


def past(s: dict, today: dt.date | None = None, n: int = 20) -> list[tuple[str, dict]]:
    today = (today or dt.date.today()).isoformat()
    return [(d, x) for d, x in sorted(s["nights"].items(), reverse=True) if d < today][:n]


def describe(club: Club, date: str, x: dict) -> str:
    """One line for the minutes' Upcoming Chow section."""
    day = dt.date.fromisoformat(date).strftime("%b %-d")
    if x.get("status") == "none":
        return f"{day}: no chow{f' ({x['note']})' if x.get('note') else ''}"
    return f"{day}: {club.name(x['member'])}" if x.get("member") else f"{day}: (open)"


# ---------------- rotation ----------------

def eligible(club: Club, s: dict, mid: str, date: dt.date) -> bool:
    m = club.members.get(mid)
    if not m or m.status.lower() in ("inactive", "silent key"):
        return False
    c = s["constraints"].get(mid) or {}
    if (date.day - 1) // 7 + 1 in (c.get("not_weeks") or []):
        return False
    return not any(a <= date.isoformat() <= b for a, b in c.get("away") or [])


def meeting_nights(club: Club, start: dt.date, until: dt.date) -> list[dt.date]:
    wd = WEEKDAYS.index(str(club.info.get("meeting_day", "Thursday")).lower())
    d = start + dt.timedelta(days=(wd - start.weekday()) % 7)
    out = []
    while d <= until:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def next_up(club: Club, s: dict) -> str | None:
    """Who the rotation continues with: set by a leader (swaps can make the last night misleading),
    else the member after whoever has the last assigned night."""
    order = [m for m in s["order"] if m in club.members]
    if s.get("next") in order:
        return s["next"]
    assigned = [x["member"] for _, x in sorted(s["nights"].items()) if x.get("member") and x.get("status") != "none"]
    if assigned and assigned[-1] in order:
        return order[(order.index(assigned[-1]) + 1) % len(order)]
    return order[0] if order else None


def generate(club: Club, s: dict, until: dt.date, by: str, today: dt.date | None = None) -> list[str]:
    """Fill empty meeting nights up to `until`, continuing the rotation from next_up().

    A member who can't do a night (constraint) keeps their turn and gets the next night they can do.
    Returns the dates filled.
    """
    order = [m for m in s["order"] if m in club.members]
    if not order:
        return []
    today = today or dt.date.today()
    assigned = [d for d, x in sorted(s["nights"].items()) if x.get("member") and x.get("status") != "none"]
    start = max(today, dt.date.fromisoformat(assigned[-1]) + dt.timedelta(days=1)) if assigned else today
    i = order.index(next_up(club, s))
    waiting: list[str] = []  # skipped by a constraint, first in line for the next night they can do
    filled = []
    for d in meeting_nights(club, start, until):
        x = s["nights"].get(d.isoformat())
        if x and (x.get("member") or x.get("status") == "none"):
            continue
        pick = next((w for w in waiting if eligible(club, s, w, d)), None)
        if pick:
            waiting.remove(pick)
        for _ in range(len(order)):
            if pick:
                break
            cand, i = order[i], (i + 1) % len(order)
            if eligible(club, s, cand, d):
                pick = cand
            elif club.members.get(cand) and club.members[cand].status.lower() not in ("inactive", "silent key"):
                waiting.append(cand)
        if not pick:
            continue
        s["nights"][d.isoformat()] = {"member": pick, "status": "scheduled"}
        filled.append(d.isoformat())
    if filled:
        s["next"] = order[i] if not waiting else waiting[0]  # whoever's turn comes next
        _log("generate", by, dates=filled)
    return filled


# ---------------- changes by leaders ----------------

def assign(club: Club, s: dict, date: str, mid: str | None, by: str, url: str = "") -> None:
    x = night(s, date)
    old = x.get("member")
    x.update(member=mid or None, status="scheduled")
    x.pop("note", None)
    e = _log("assign", by, date=date, old=old, new=mid)
    _tell(club, [old, mid], f"Chow night changed: {_day(date)}",
          f"{club.name(by)} changed chow for {_day(date)}: {club.name(old) if old else '(open)'} -> "
          f"{club.name(mid) if mid else '(open)'}.", url, e)


def set_none(s: dict, date: str, note: str, by: str) -> None:
    x = night(s, date)
    old = x.get("member")
    s["nights"][date] = {"member": None, "status": "none", "note": note.strip()[:80]}
    _log("no_chow", by, date=date, old=old, note=note.strip()[:80])


def swap(club: Club, s: dict, a: str, b: str, by: str, url: str = "", request: str | None = None) -> dict:
    """Trade the members of two nights. Both members, and the Secretary, are emailed."""
    xa, xb = night(s, a), night(s, b)
    if not (xa.get("member") and xb.get("member")):
        raise ValueError("Both nights need someone assigned to swap them.")
    ma, mb = xa["member"], xb["member"]
    xa["member"], xb["member"] = mb, ma
    e = _log("swap", by, dates=[a, b], members=[ma, mb], request=request)
    _tell(club, [ma, mb], f"Chow swap: {club.name(ma)} and {club.name(mb)}",
          f"{club.name(ma)} now brings chow on {_day(b)}, and {club.name(mb)} on {_day(a)}."
          + (f" (Arranged by {club.name(by)}.)" if by not in (ma, mb) else ""), url, e)
    return e


def record(club: Club, s: dict, date: str, status: str, by: str, covered_by: str | None = None, note: str = "") -> None:
    """On meeting night: did the scheduled member provide chow? (missed counts toward bylaws VII.F)."""
    if status not in ("provided", "missed", "covered", "scheduled"):
        raise ValueError("Unknown status")
    x = night(s, date)
    x["status"] = status
    x["covered_by"] = covered_by if status == "covered" else None
    x["note"] = note.strip()[:80] if status in ("provided", "covered") else ""  # what they brought
    _log("record", by, date=date, member=x.get("member"), status=status, covered_by=x["covered_by"], note=x["note"])


def set_order(s: dict, order: list[str], by: str) -> None:
    s["order"] = list(dict.fromkeys(order))
    s["pending"] = [p for p in s["pending"] if p not in s["order"]]
    _log("order", by, order=s["order"])


def set_constraints(s: dict, mid: str, not_weeks: list[int], away: list[list[str]], note: str, by: str) -> None:
    c = {"not_weeks": sorted({w for w in not_weeks if 1 <= w <= 5}),
         "away": [[a, b] for a, b in away if a and b and a <= b], "note": note.strip()[:120]}
    if any(c.values()):
        s["constraints"][mid] = c
    else:
        s["constraints"].pop(mid, None)
    _log("constraints", by, member=mid, **c)


# ---------------- swap requests between members ----------------

def request_swap(club: Club, s: dict, requester: str, mine: str, theirs: str, url: str = "") -> dict:
    xa, xb = s["nights"].get(mine) or {}, s["nights"].get(theirs) or {}
    if xa.get("member") != requester:
        raise ValueError("You can only offer one of your own chow nights.")
    other = xb.get("member")
    if not other or other == requester:
        raise ValueError("Pick someone else's night.")
    if min(mine, theirs) < dt.date.today().isoformat():
        raise ValueError("Only upcoming nights can be swapped.")
    if any(r["status"] == "pending" and {r["mine"], r["theirs"]} & {mine, theirs} for r in s["swaps"]):
        raise ValueError("One of those nights already has a swap waiting for an answer.")
    r = {"id": secrets.token_hex(5), "at": int(time.time()), "requester": requester, "with": other,
         "mine": mine, "theirs": theirs, "status": "pending"}
    s["swaps"].append(r)
    e = _log("swap_request", requester, request=r["id"], dates=[mine, theirs], members=[requester, other])
    _tell(club, [other], f"Chow swap request from {club.name(requester)}",
          f"{club.name(requester)} asks to swap chow nights: you would bring chow on {_day(mine)} "
          f"instead of {_day(theirs)}, and they would take {_day(theirs)}.\n\nApprove or decline on the Chow page.",
          url, e, secretary=False)
    return r


def decide_swap(club: Club, s: dict, rid: str, by: str, approve: bool, url: str = "") -> dict:
    r = next((x for x in s["swaps"] if x["id"] == rid), None)
    if not r or r["status"] != "pending":
        raise ValueError("That request has already been answered.")
    if by == r["requester"] and not approve:
        r["status"] = "cancelled"
    elif by != r["with"]:
        raise ValueError("Only the member asked can answer this request.")
    elif not approve:
        r["status"] = "declined"
    else:
        xa, xb = s["nights"].get(r["mine"]) or {}, s["nights"].get(r["theirs"]) or {}
        if xa.get("member") != r["requester"] or xb.get("member") != r["with"]:
            r["status"] = "stale"
            raise ValueError("Those nights have changed since the request; ask again.")
        r["status"] = "approved"
        swap(club, s, r["mine"], r["theirs"], by, url, request=rid)
    r["decided_at"] = int(time.time())
    if r["status"] in ("declined", "cancelled"):
        e = _log("swap_" + r["status"], by, request=rid)
        if r["status"] == "declined":
            _tell(club, [r["requester"]], "Chow swap declined",
                  f"{club.name(r['with'])} declined swapping {_day(r['mine'])} for {_day(r['theirs'])}.",
                  url, e, secretary=False)
    return r


# ---------------- one-time import of the Secretary's spreadsheet ----------------

def match_name(club: Club, text: str) -> str | None:
    """'Doe, Jane', 'Jane Doe', a misspelled 'Do' or 'Jayne Dough' -> member id (spelling drift allowed)."""
    import difflib
    t = " ".join(str(text).replace(",", " , ").split())
    if not t:
        return None
    if "," in t:
        last, first = [x.strip() for x in t.split(",", 1)]
    else:
        parts = t.split()
        first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", parts[0])
    people = list(club.members.values())
    lasts = {m.last.lower() for m in people}
    hit = difflib.get_close_matches(last.lower(), lasts, n=1, cutoff=0.75)
    cands = [m for m in people if hit and m.last.lower() == hit[0]]
    if len(cands) > 1 and first:
        cands = [m for m in cands if m.first.lower().startswith(first.lower()[:3])]
    return cands[0].id if len(cands) == 1 else None


def import_xlsx(club: Club, path: Path, order: list[str], by: str, year: int) -> tuple[dict, list[str]]:
    """Dated rows (name in column A, date in B or C) become nights; blank-name dates become no-chow nights.

    `order` is the rotation as names. Returns (state, problems) without saving, so it can be checked first.
    """
    import openpyxl
    s = {"nights": {}, "order": [], "pending": [], "constraints": {}, "swaps": []}
    problems = []
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    for row in ws.iter_rows(min_row=2, max_col=3):
        name, dates = row[0].value, [c.value for c in row[1:3]]
        date = next((d for d in dates if isinstance(d, dt.datetime)), None)
        if date is None and any(isinstance(d, str) and d.strip() for d in dates):
            date = next((_parse_day(d, year) for d in dates if isinstance(d, str) and _parse_day(d, year)), None)
        if date is None:
            continue
        day = date.date() if isinstance(date, dt.datetime) else date
        wd = WEEKDAYS.index(str(club.info.get("meeting_day", "Thursday")).lower())
        if day.weekday() != wd:  # a typo'd date: use the nearest meeting night
            fixed = day + dt.timedelta(days=(wd - day.weekday() + 3) % 7 - 3)
            problems.append(f"Row {row[0].row}: {day:%a %b %-d} isn't a meeting night; used {fixed:%a %b %-d}")
            day = fixed
        d = day.isoformat()
        if not name or not str(name).strip():
            s["nights"][d] = {"member": None, "status": "none", "note": holiday(day) or ""}
            continue
        mid = match_name(club, name)
        if not mid:
            problems.append(f"Row {row[0].row}: no member matches {name!r}")
            continue
        s["nights"][d] = {"member": mid, "status": "scheduled"}
    for n in order:
        mid = match_name(club, n)
        if mid:
            s["order"].append(mid)
        else:
            problems.append(f"Rotation: no member matches {n!r}")
    s["order"] = list(dict.fromkeys(s["order"]))
    active = [m.id for m in club.members.values() if m.status.lower() not in ("inactive", "silent key")]
    s["pending"] = [m for m in active if m not in s["order"]]
    return s, problems


def holiday(d: dt.date) -> str | None:
    """Holidays that fall on a meeting night and usually mean no chow."""
    if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:
        return "Thanksgiving"
    return {(12, 24): "Christmas Eve", (12, 25): "Christmas", (12, 31): "New Year's Eve", (1, 1): "New Year's Day",
            (7, 4): "Independence Day"}.get((d.month, d.day))


def _parse_day(text: str, year: int) -> dt.date | None:
    for fmt in ("%d-%b", "%d %b", "%b %d"):
        try:
            return dt.datetime.strptime(f"{text.strip()} {year}", f"{fmt} %Y").date()
        except ValueError:
            pass
    return None


# ---------------- minutes and email ----------------

def tonight_line(club: Club, date: str, x: dict | None) -> str | None:
    """The minutes' line on whether tonight's chow was brought (and what), once it's been recorded."""
    if not x or not x.get("member"):
        return None
    what = f" ({x['note']})" if x.get("note") else ""
    if x.get("status") == "provided":
        return f"Chow tonight provided by {club.name(x['member'])}{what}."
    if x.get("status") == "covered" and x.get("covered_by"):
        return f"Chow tonight provided by {club.name(x['covered_by'])} for {club.name(x['member'])}{what}."
    if x.get("status") == "missed":
        return f"Chow tonight: {club.name(x['member'])} did not provide chow."
    return None


def meeting_notes(s_log: list[dict], club: Club, date: str) -> list[str]:
    """Schedule changes made on a meeting's date (swaps, reassignments, no-chow nights), oldest first."""
    out = []
    for e in reversed(s_log):
        if dt.date.fromtimestamp(e["at"]).isoformat() != date:
            continue
        if e["action"] == "swap":
            a, b = e["dates"]
            ma, mb = e["members"]
            out.append(f"Chow swap: {club.name(ma)} now has {_day(b)} and {club.name(mb)} has {_day(a)}.")
        elif e["action"] == "assign":
            out.append(f"Chow for {_day(e['date'])} changed to {club.name(e['new']) if e['new'] else '(open)'}.")
        elif e["action"] == "no_chow":
            out.append(f"No chow on {_day(e['date'])}{f' ({e['note']})' if e.get('note') else ''}.")
    return out


def minutes_section(club: Club, s: dict, s_log: list[dict], date: str, n: int = 4) -> list[str]:
    """The minutes' Upcoming Chow section: tonight's chow, changes made tonight, then the next few nights."""
    tonight = tonight_line(club, date, s["nights"].get(date))
    later = upcoming(s, dt.date.fromisoformat(date) + dt.timedelta(days=1), n=n)
    return ([tonight] if tonight else []) + meeting_notes(s_log, club, date) + [describe(club, d, x) for d, x in later]


def _day(date: str) -> str:
    return dt.date.fromisoformat(date).strftime("%A, %B %-d")


def _tell(club: Club, members: list[str | None], subject: str, text: str, url: str, e: dict,
          secretary: bool = True) -> None:
    ids = [m for m in dict.fromkeys(members) if m]
    if secretary:
        ids += [x for x in club.secretaries if x not in ids]
    to = [club.members[m].email for m in ids if m in club.members and club.members[m].email]
    if not to:
        return
    try:
        auth.send_email(to, subject, f"{text}\n\nThe chow schedule: {url}/chow\n\n73,\nW8LBZ Minutes",
                        only_to=club.email_only_to())
    except Exception:
        log.exception("couldn't send %r (chow change %s)", subject, e["id"])
