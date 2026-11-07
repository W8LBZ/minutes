"""Leader console: start a meeting, keep its live state, and save it as draft minutes.

A draft lives in the archive like any meeting (status "draft"). The console's own
working state (report queue, who has the floor) sits beside it in console.json.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import logging
import shutil
import time

from . import ai, auth, business, chow
from .club import DATA
from .meeting import SECTIONS, Item, Meeting
from .store import Archive

log = logging.getLogger("w8lbz.console")
CARRY_FORWARD = ("Upcoming Events",)  # copied from the previous meeting as a starting point (business is tracked)


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def start(archive: Archive, date: dt.date, leader: str | None) -> Meeting:
    if date.isoformat() in archive.by_slug:
        return archive.by_slug[date.isoformat()]
    m = Meeting(date=date, status="draft", leader=leader)
    prev = previous(archive, date)
    for sec in SECTIONS:
        m.sections[sec] = []
    if prev:
        m.sections["Upcoming Events"] = [Item(i.text) for i in prev.items("Upcoming Events")]
    # Old Business: every tracked item still open (business.py).
    m.sections.update(business_sections(archive, m.slug))
    # The next few chow nights after tonight, from the chow schedule.
    later = [(d, x) for d, x in chow.upcoming(chow.load(), date + dt.timedelta(days=1), n=4)]
    m.sections["Upcoming Chow"] = [Item(chow.describe(archive.club, d, x)) for d, x in later]
    m.save(archive.root)
    archive.reload()
    return archive.by_slug[m.slug]


def business_state(archive: Archive) -> dict:
    s = business.load()
    if not s["seeded"]:
        business.seed(s, archive.meetings)
        business.save(s)
    return s


def business_sections(archive: Archive, slug: str, s: dict | None = None) -> dict[str, list[Item]]:
    s = s or business_state(archive)
    return {k: [Item(t) for t in v] for k, v in business.sections(s, archive.club, slug, _since(archive, slug)).items()}


def _since(archive: Archive, slug: str) -> str | None:
    prev = previous(archive, dt.date.fromisoformat(slug))
    return prev.slug if prev else None


def business_items(archive: Archive, slug: str, s: dict | None = None) -> dict:
    """The console's Old and New Business: tracked items as of this meeting."""
    s = s or business_state(archive)
    since = _since(archive, slug)
    old, new = business.for_meeting(s, slug, since)
    return {"old": [business.view(archive.club, x, slug, since) for x in old],
            "new": [business.view(archive.club, x, slug, since) for x in new],
            "notes": [{**n, "name": archive.club.name(n["by"])} for n in business.notes_for(s, slug)]}


def sync_business(archive: Archive, slug: str, s: dict) -> None:
    """After a business item changes, rewrite that draft's Old and New Business (the live view reads them)."""
    m = archive.by_slug.get(slug)
    if m and m.status == "draft":
        m.sections.update(business_sections(archive, slug, s))
        m.save(archive.root)


# ---------------- AI "ask about" prompts for Community Reports (ai.ask_about) ----------------
REPORTS_BACK = 4


def report_histories(archive: Archive) -> dict[str, list[tuple[str, str]]]:
    """Each active member's last few community reports from submitted minutes, oldest first."""
    out: dict[str, list[tuple[str, str]]] = {}
    for mt in archive.meetings:  # newest first
        if mt.status == "draft":
            continue
        for it in mt.items("Community Reports"):
            m = archive.club.members.get(it.member or "")
            if m and m.status.lower() not in ("inactive", "silent key") and len(out.setdefault(m.id, [])) < REPORTS_BACK:
                out[m.id].append((mt.slug, it.text))
    return {mid: r[::-1] for mid, r in out.items()}


def refresh_ask_about(archive: Archive) -> int:
    """Ask the AI what's worth following up for every member; saved for the console. Returns members covered."""
    hist = report_histories(archive)
    prompts = ai.ask_about(archive.club, hist)
    data = {"at": int(time.time()), "model": archive.club.ai.get("model"),
            "members": {mid: {"prompts": p, "upto": hist[mid][-1][0]} for mid, p in prompts.items()}}
    path = DATA / "ask-about.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.chmod(0o600)
    tmp.replace(path)
    return len(prompts)


def ask_about_for(history: dict[str, list]) -> dict[str, list[str]]:
    """Saved prompts that are still current: made after the member's latest report shown in the console."""
    p = DATA / "ask-about.json"
    if not p.exists():
        return {}
    members = json.loads(p.read_text()).get("members", {})
    return {mid: e["prompts"] for mid, e in members.items()
            if history.get(mid) and e.get("upto") == history[mid][0][0]}


def previous(archive: Archive, date: dt.date) -> Meeting | None:
    return next((m for m in archive.meetings if m.date < date and m.status != "draft"), None)


def state_path(archive: Archive, slug: str):
    return archive.root / slug / "console.json"


def load_state(archive: Archive, slug: str) -> dict:
    p = state_path(archive, slug)
    return json.loads(p.read_text()) if p.exists() else {"done": [], "skipped": [], "current": None}


def context(archive: Archive, m: Meeting) -> dict:
    """Everything the console page needs, as JSON-able data."""
    club = archive.club
    members = sorted(
        (x for x in club.members.values() if x.status.lower() not in ("silent key", "inactive")),
        key=lambda x: (x.last, x.first))
    history = {}
    for x in members:
        past = [(mt.date.isoformat(), it.text) for mt in archive.meetings if mt.date < m.date
                for it in mt.items("Community Reports") if it.member == x.id][:3]
        history[x.id] = past
    guests = {}
    past = []  # earlier guests who aren't members, most recent first (for the quick-pick buttons)
    for g in archive.guests():
        if not g.get("member") and g["visits"][-1][0] < m.date:
            past.append({"name": g["name"], "callsign": g["callsign"], "visits": len(g["visits"]),
                         "last": g["visits"][-1][0].isoformat()})
        info = {"name": g["name"], "callsign": g["callsign"], "visits": len(g["visits"]),
                "last": g["visits"][-1][0].isoformat(), "member": g.get("member")}
        guests[_key(g["name"])] = info
        if g["callsign"]:
            guests[_key(g["callsign"])] = info
    return {
        "meeting": {
            "slug": m.slug, "date": m.slug, "status": m.status, "leader": m.leader,
            "in_person": m.in_person, "remote": m.remote, "guests": m.guests, "visitors": m.visitors,
            "sections": {s: [{"text": i.text, "member": i.member} for i in m.items(s)] for s in SECTIONS},
        },
        "state": load_state(archive, m.slug),
        "members": [{"id": x.id, "name": x.name, "short": club.short(x.id), "callsign": x.callsign}
                    for x in members],
        "history": history,
        "guest_history": guests,
        "past_guests": sorted(past, key=lambda g: (g["last"], g["visits"]), reverse=True),
        "sections": SECTIONS,
        "invite_after": int(club.info.get("invite_after_visits", 3)),
        "email": {"roster": len(recipients(archive)), "only_to": club.email.get("only_to")},
        "chow": chow_tonight(archive, m),
        "business": business_items(archive, m.slug),
        "ask_about": ask_about_for(history),
    }


def apply(archive: Archive, slug: str, data: dict) -> Meeting:
    """Save the console's full meeting state (last write wins)."""
    m = archive.by_slug[slug]
    if m.status == "published":
        raise ValueError("Minutes already submitted")
    d = data["meeting"]
    m.leader = d.get("leader") or m.leader
    m.in_person = list(dict.fromkeys(d.get("in_person", [])))
    m.remote = [x for x in dict.fromkeys(d.get("remote", [])) if x not in m.in_person]
    m.guests = [{k: v for k, v in g.items() if k in ("name", "callsign", "notes") and v}
                for g in d.get("guests", []) if g.get("name", "").strip()]
    m.guests = [g for g in m.guests if not archive.club.is_redacted(g["name"])]
    m.visitors = max(0, int(d.get("visitors") or 0))
    m.sections = {s: [Item(i["text"].strip(), i.get("member") or None)
                      for i in d.get("sections", {}).get(s, []) if i.get("text", "").strip()]
                  for s in SECTIONS}
    m.sections.update(business_sections(archive, slug))  # tracked: never from the browser
    m.save(archive.root)
    state_path(archive, slug).write_text(json.dumps(data.get("state") or {}))
    archive.reload()
    return archive.by_slug[slug]


def submit(archive: Archive, slug: str) -> Meeting:
    m = archive.by_slug[slug]
    # Upcoming Chow comes from the chow schedule as it stands now: tonight's chow, tonight's changes, what's next.
    m.sections["Upcoming Chow"] = [Item(t) for t in chow.minutes_section(archive.club, chow.load(), chow.history(), slug)]
    m.sections.update(business_sections(archive, slug))
    m.status = "published"
    m.save(archive.root)
    archive.reload()
    return archive.by_slug[slug]


def discard(archive: Archive, slug: str) -> None:
    """Delete a draft (e.g. a practice run). Submitted minutes can't be discarded."""
    m = archive.by_slug[slug]
    if m.status != "draft":
        raise ValueError("Only drafts can be discarded")
    shutil.rmtree(archive.root / slug)
    s = business.load()
    business.forget_meeting(s, slug)
    business.save(s)
    archive.reload()


def recipients(archive: Archive) -> list[str]:
    """Roster addresses that get the minutes: everyone with an email who isn't Inactive or a Silent Key."""
    return sorted({m.email.strip() for m in archive.club.members.values()
                   if m.email and m.status.lower() not in ("inactive", "silent key")}, key=str.lower)


def email_status(archive: Archive, slug: str) -> dict | None:
    p = archive.root / slug / "emailed.json"
    return json.loads(p.read_text()) if p.exists() else None


def email_minutes(archive: Archive, slug: str, make_pdf, url: str) -> dict:
    """Email submitted minutes (PDF from make_pdf() attached) to the roster, once.

    Test mode (email.only_to) applies. The outcome, or the error, is kept in emailed.json.
    """
    if (done := email_status(archive, slug)) and not done.get("error"):
        return done
    m = archive.by_slug[slug]
    club = archive.club
    to = recipients(archive)
    leader = club.members.get(m.leader or "")
    date = m.date.strftime("%B %-d, %Y")
    body = (f"Here are the minutes of the {club.info.get('callsign', '')} meeting of {date}"
            f"{f', led by {leader.name}' if leader else ''}. The PDF is attached.\n\n"
            f"Read them online, along with past minutes: {url}\n\n"
            f"Replies go to {leader.first if leader and leader.email else 'the club'}.\n\n73,\n{club.info.get('callsign', '')}")
    try:
        pdf = make_pdf()
        sent = auth.send_email(to, f"{club.info.get('callsign', '')} meeting minutes, {date}", body,
                               attachments=[(pdf[0], pdf[1], "application/pdf")], only_to=club.email_only_to(),
                               reply_to=leader.email if leader and leader.email else None)
        status = {"at": int(time.time()), "sent": sent, "roster": len(to), "test_mode": club.email_only_to() is not None}
    except Exception as e:
        log.exception("emailing the minutes of %s failed", slug)
        status = {"at": int(time.time()), "error": str(e)}
    (archive.root / slug / "emailed.json").write_text(json.dumps(status))
    return status


def chow_tonight(archive: Archive, m: Meeting) -> dict:
    """Tonight's chow for the console panel, and the members who could have covered it."""
    s = chow.load()
    x = s["nights"].get(m.slug) or {}
    nxt = chow.upcoming(s, m.date + dt.timedelta(days=1), n=1)
    club = archive.club
    return {"date": m.slug, "member": x.get("member"), "name": club.name(x["member"]) if x.get("member") else None,
            "status": x.get("status", "scheduled") if x else None, "covered_by": x.get("covered_by"),
            "note": x.get("note", ""), "next": chow.describe(club, *nxt[0]) if nxt else None,
            "section": chow.minutes_section(club, s, chow.history(), m.slug)}
