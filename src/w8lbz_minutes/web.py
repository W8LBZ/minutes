"""Web UI: archive, minutes view and PDF, search, member history, stats, guests, leader console, login."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
from importlib.metadata import metadata, requires, version
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import ai, business, chow, console, membership, profile
from . import auth as authmod
from .auth import Auth, _safe_next
from .club import DATA, PREVIEW
from .roster import SHAREABLE, SheetError
from .meeting import SECTIONS
from .store import Archive

HERE = Path(__file__).parent
app = FastAPI(title="W8LBZ Minutes")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
archive = Archive()
authn = Auth(archive.club)

# Show the app's own log lines (emails sent or withheld, rate limits) alongside uvicorn's.
_log = logging.getLogger("w8lbz")
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False

COOKIE = "w8lbz_session"
CHALLENGE_COOKIE = "w8lbz_pk"
PUBLIC_PATHS = ("/login", "/auth/passkey/login/", "/static/", "/favicon.ico")
URL_RE = re.compile(r"(https?://[^\s<]+[^\s<.,)])")


def linkify(text: str) -> Markup:
    return Markup(URL_RE.sub(r'<a href="\1">\1</a>', str(escape(text))))


def by_last_name(ids):
    c = archive.club
    return sorted(ids, key=lambda i: (c.members[i].last, c.members[i].first) if i in c.members else (i, ""))


DATES = {"list": "%b %-d, %Y", "document": "%B %-d, %Y", **(archive.club.info.get("date_formats") or {})}
templates.env.filters["linkify"] = linkify
templates.env.filters["longdate"] = lambda d: d.strftime(DATES["document"])
templates.env.filters["listdate"] = lambda d: d.strftime(DATES["list"])
templates.env.filters["by_last_name"] = by_last_name
templates.env.filters["clock"] = lambda t: dt.datetime.fromtimestamp(t).strftime("%-I:%M %p")
def monthday(md: str | None) -> str:
    """'07-04' -> 'July 4'. Anything else (e.g. a full date typed into the sheet) is shown as is."""
    try:
        return dt.date(2000, int(md[:2]), int(md[3:5])).strftime("%B %-d") if md and len(md) == 5 else (md or "")
    except ValueError:
        return md


templates.env.filters["monthday"] = monthday
templates.env.filters["tsfull"] = lambda t: (dt.datetime.fromtimestamp(t).strftime(DATES["list"] + ", %-I:%M %p")
                                             .replace("AM", "am").replace("PM", "pm")) if t else ""
templates.env.filters["ts"] = lambda t: dt.datetime.fromtimestamp(t).strftime(DATES["list"]) if t else "never"
templates.env.globals.update(club=archive.club, SECTIONS=SECTIONS, VERSION=version("w8lbz-minutes"), PREVIEW=PREVIEW)


# ---------------- login gate ----------------

@app.middleware("http")
async def require_login(request: Request, call_next):
    archive.club.refresh()  # pick up a roster sync without a restart
    token = request.cookies.get(COOKIE)
    real = authn.member_for(token)
    request.state.real_member = real
    request.state.admin_until = authn.admin_until(token) if real else None
    # "View as": an admin in admin mode sees the app exactly as another member does, read-only.
    va = authn.view_as(token) if request.state.admin_until else None
    request.state.viewing_as = va if va in archive.club.members and va != real else None
    request.state.member = request.state.viewing_as or real
    path = request.url.path
    if request.state.viewing_as:
        request.state.admin_until = None  # their permissions, not the admin's
        if path.startswith(("/account", "/profile/email", "/logout", "/auth/")) or (
                request.method not in ("GET", "HEAD") and not path.startswith("/admin/")):
            return HTMLResponse("You're viewing the app as another member, which is read-only. "
                                "Stop viewing as them (banner at the top) to make changes.", status_code=403)
    if request.state.member or path.startswith(PUBLIC_PATHS):
        return await call_next(request)
    if request.method == "GET" and not path.startswith("/api/"):
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    return JSONResponse({"detail": "Please sign in"}, status_code=401)


def me(request: Request) -> str:
    return request.state.member


def real_me(request: Request) -> str:
    """The signed-in member, even while viewing the app as someone else."""
    return request.state.real_member


def admin_mode(request: Request) -> bool:
    return bool(getattr(request.state, "admin_until", None))


def privileged(request: Request) -> bool:
    """Officers, and admins while admin mode is on: see all contact details, the change log, undo."""
    m = archive.club.members.get(getattr(request.state, "member", None) or "")
    return bool(m and (m.officer or admin_mode(request)))


def leader(request: Request) -> str:
    if not (archive.club.can_lead(request.state.member) or admin_mode(request)):
        raise HTTPException(403, "Only officers and minutes editors can lead a meeting.")
    return request.state.member


def officer(request: Request) -> str:
    if not privileged(request):
        raise HTTPException(403, "Only officers can do that.")
    return request.state.member


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    mid = getattr(request.state, "member", None)
    return templates.TemplateResponse(request, name, {
        "club": archive.club,
        "me": archive.club.members.get(mid) if mid else None,
        "can_lead": (archive.club.can_lead(mid) or admin_mode(request)) if mid else False,
        "is_admin": archive.club.is_admin(mid), "admin_until": getattr(request.state, "admin_until", None),
        "viewing_as": getattr(request.state, "viewing_as", None),
        "rp_id": authn.rp_id, **ctx})


def is_https(request: Request) -> bool:
    # Behind `tailscale serve` the app itself sees plain HTTP; the passkey host is always HTTPS.
    return request.url.scheme == "https" or request.url.hostname == authn.rp_id


def base_url(request: Request) -> str:
    """Where this member reached us (LAN address or the HTTPS tailnet name), for links in emails."""
    host = request.headers.get("host", request.url.netloc)
    return f"{'https' if is_https(request) else 'http'}://{host}"


def start_session(request: Request, response: Response, member: str) -> Response:
    token = authn.new_session(member, request.headers.get("user-agent", ""))
    response.set_cookie(COOKIE, token, max_age=authn.session_days * 86400, httponly=True, samesite="lax",
                        secure=is_https(request))
    return response


def get_meeting(slug: str):
    m = archive.by_slug.get(slug)
    if not m:
        raise HTTPException(404, "No minutes for that date")
    return m


# ---------------- login & account ----------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", sent: int = 0, error: str = ""):
    if request.state.member:
        return RedirectResponse(_safe_next(next), status_code=303)
    return page(request, "login.html", next=_safe_next(next), sent=sent, error=error)


@app.post("/login/email")
def login_email(request: Request, email: str = Form(...), next: str = Form("/")):
    authn.send_link(email, next, base_url=base_url(request))
    return RedirectResponse(f"/login?sent=1&next={quote(_safe_next(next))}", status_code=303)


@app.get("/login/link")
def login_link(request: Request, t: str = ""):
    used = authn.use_link(t)
    if not used:
        return RedirectResponse("/login?error=link", status_code=303)
    member, next_url = used
    # Offer a passkey right away to members who don't have one (only possible over HTTPS on the passkey host).
    if not authn.passkeys(member) and request.url.hostname == authn.rp_id:
        next_url = f"/account?welcome=1&next={quote(next_url)}"
    return start_session(request, RedirectResponse(next_url, status_code=303), member)


@app.post("/logout")
def logout(request: Request):
    authn.end_session(request.cookies.get(COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, welcome: int = 0, next: str = "/", mid: str = Depends(me)):
    return page(request, "account.html", passkeys=authn.passkeys(mid), sessions=authn.sessions(mid),
                welcome=welcome, next=_safe_next(next), passkey_host=request.url.hostname == authn.rp_id)


# ---------------- tracked business items ----------------


def can_lead_now(request: Request) -> bool:
    return archive.club.can_lead(request.state.member) or admin_mode(request)


def business_change(request: Request, fn, meeting: str = "", back: str = "/business"):
    """Run fn(state) under the lock, save, and refresh that meeting's draft minutes. JSON for the console."""
    with business.locked():
        s = console.business_state(archive)
        try:
            fn(s)
        except ValueError as e:
            if request.headers.get("accept", "").startswith("application/json"):
                return JSONResponse({"error": str(e)}, status_code=409)
            path, _, frag = back.partition("#")
            return RedirectResponse(f"{path}?error=" + quote(str(e)) + (f"#{frag}" if frag else ""), status_code=303)
        business.save(s)
        if meeting:
            console.sync_business(archive, meeting, s)
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(console.business_items(archive, meeting, s) if meeting else {"ok": True})
    return RedirectResponse(back, status_code=303)


def _may_edit_item(request: Request, s: dict, iid: str) -> None:
    """Leaders change any item; a member can update the ones they own."""
    if not (can_lead_now(request) or business.get(s, iid)["owner"] == request.state.member):
        raise ValueError("Only a leader or the item's owner can change it.")


@app.get("/business", response_class=HTMLResponse)
def business_page(request: Request, error: str = "", note: str = "", mid: str = Depends(me)):
    s = console.business_state(archive)
    today = dt.date.today().isoformat()
    items = [business.view(archive.club, x, today) for x in s["items"]]
    open_ = sorted((x for x in items if x["status"] == "open"), key=lambda x: (x["due"] or "9999", x["opened"]))
    done = sorted((x for x in items if x["status"] == "done"), key=lambda x: x["closed"], reverse=True)[:50]
    members = sorted((m for m in archive.club.members.values() if m.status.lower() not in ("inactive", "silent key")),
                     key=lambda m: (m.last, m.first))
    leader_ = can_lead_now(request)
    pending = [g for g in s["suggestions"] if g["status"] == "pending"] if leader_ else []
    submitted = [m for m in archive.meetings if m.status != "draft"][:6]
    my_notes = [n for n in s["notes"] if n["by"] == mid and n["status"] == "pending"]
    all_notes = [n for n in s["notes"] if n["status"] == "pending"] if leader_ else []
    return page(request, "business.html", open_items=open_, done=done, error=error, note=note, leader=leader_,
                my_notes=my_notes, all_notes=all_notes, next_meetings=upcoming_meetings(),
                suggestions=pending, ai_on=ai.configured(archive.club) and leader_, submitted=submitted,
                by_id={x["id"]: x for x in items},
                members=members, today=today, fmt=lambda d: dt.date.fromisoformat(d).strftime("%b %-d, %Y"))


def run_followups(slug: str) -> str:
    """Ask the AI for follow-ups from a meeting's minutes and store them as pending suggestions."""
    m = archive.by_slug[slug]
    with business.locked():
        s = console.business_state(archive)
        open_items = [x for x in s["items"] if x["status"] == "open"]
    found = ai.suggest_followups(archive.club, m, open_items)  # outside the lock: it takes a few seconds
    with business.locked():
        s = console.business_state(archive)
        n = business.add_suggestions(s, slug, found, archive.club.ai.get("model", ""))
        business.save(s)
    _log.info("AI suggested %d follow-ups for %s", n, slug)
    return f"{n} suggestion{'s' if n != 1 else ''} from the {m.date:%B %-d} minutes." if n else \
        f"No follow-ups found in the {m.date:%B %-d} minutes."


def followups_after_submit(slug: str) -> None:
    if ai.configured(archive.club):
        try:
            run_followups(slug)
        except Exception:
            _log.exception("AI follow-ups for %s failed", slug)


@app.post("/business/suggest")
def business_suggest(request: Request, meeting: str = Form(...), mid: str = Depends(leader)):
    if not ai.configured(archive.club):
        raise HTTPException(404)
    get_meeting(meeting)
    try:
        msg = run_followups(meeting)
    except ai.AIError as e:
        return RedirectResponse("/business?error=" + quote(str(e)), status_code=303)
    return RedirectResponse("/business?note=" + quote(msg) + "#suggestions", status_code=303)


@app.post("/business/suggestions/{sid}/accept")
def suggestion_accept(request: Request, sid: str, text: str = Form(""), owner: str = Form(""), due: str = Form(""),
                      mid: str = Depends(leader)):
    if owner and owner not in archive.club.members:
        raise HTTPException(404)
    return business_change(request, lambda s: business.accept_suggestion(s, sid, mid, text or None, owner, due),
                           back="/business#suggestions")


@app.post("/business/suggestions/{sid}/dismiss")
def suggestion_dismiss(request: Request, sid: str, mid: str = Depends(leader)):
    return business_change(request, lambda s: business.dismiss_suggestion(s, sid, mid), back="/business#suggestions")


@app.post("/business/add")
def business_add(request: Request, text: str = Form(...), owner: str = Form(""), due: str = Form(""),
                 agenda: str = Form(""), meeting: str = Form(""), mid: str = Depends(me)):
    if not can_lead_now(request):
        raise HTTPException(403, "Only leaders can add business items.")
    return business_change(request, lambda s: business.add(s, text, mid, owner if owner in archive.club.members else None,
                                                           due, agenda, opened=meeting or None), meeting)


@app.post("/business/{iid}/edit")
async def business_edit(request: Request, iid: str, mid: str = Depends(me)):
    form = await request.form()
    allowed = ("text", "owner", "due", "agenda") if can_lead_now(request) else ("text", "due")  # owners: text and due
    fields = {k: form.get(k) for k in allowed if k in form}
    if fields.get("owner") and fields["owner"] not in archive.club.members:
        raise HTTPException(404)
    def run(s):
        _may_edit_item(request, s, iid)
        business.edit(s, iid, mid, meeting=form.get("meeting") or None, **fields)
    return business_change(request, run, form.get("meeting", ""))


@app.post("/business/{iid}/comment")
def business_comment(request: Request, iid: str, text: str = Form(...), mid: str = Depends(me)):
    """Any member can comment on an item: an update, a question, "I can help with this"."""
    return business_change(request, lambda s: business.comment(s, iid, mid, text), back=f"/business#i{iid}")


@app.post("/business/{iid}/comments/{cid}/delete")
def business_comment_delete(request: Request, iid: str, cid: str, mid: str = Depends(me)):
    return business_change(request, lambda s: business.delete_comment(s, iid, cid, mid, can_lead_now(request)),
                           back=f"/business#i{iid}")


def upcoming_meetings(n: int = 4) -> list[dt.date]:
    today = dt.date.today()
    return chow.meeting_nights(archive.club, today, today + dt.timedelta(days=7 * n))[:n]


@app.post("/business/notes")
def business_note_add(request: Request, text: str = Form(...), meeting: str = Form(...), mid: str = Depends(me)):
    if meeting not in {d.isoformat() for d in upcoming_meetings()}:
        raise HTTPException(400, "Pick one of the next meetings.")
    return business_change(request, lambda s: business.add_note(s, mid, text, meeting), back="/business#notes")


@app.post("/business/notes/{nid}/{status}")
def business_note_status(request: Request, nid: str, status: str, meeting: str = Form(""), mid: str = Depends(me)):
    if status not in ("read", "dismissed", "withdrawn"):
        raise HTTPException(404)
    return business_change(request, lambda s: business.note_status(s, nid, status, mid, can_lead_now(request)),
                           meeting, back="/business#notes")


@app.post("/business/{iid}/done")
def business_done(request: Request, iid: str, done: int = Form(1), meeting: str = Form(""), mid: str = Depends(me)):
    def run(s):
        _may_edit_item(request, s, iid)
        business.close(s, iid, mid, meeting or None) if done else business.reopen(s, iid, mid)
    return business_change(request, run, meeting)


@app.post("/business/{iid}/delete")
def business_delete(request: Request, iid: str, meeting: str = Form(...), mid: str = Depends(leader)):
    return business_change(request, lambda s: business.remove(s, iid, meeting), meeting)


# ---------------- chow list ----------------
_chow_lock = threading.Lock()


def can_edit_chow(request: Request) -> bool:
    """Changing the schedule: officers (it's the Secretary's job day to day) and admins in admin mode.
    Minutes editors see the member view; they record chow on meeting night from the console."""
    return privileged(request)


def chow_change(request: Request, fn, back: str = "/chow"):
    """Run fn(state) under the lock and save. ValueError -> shown on the Chow page."""
    with _chow_lock:
        s = chow.load()
        try:
            res = fn(s)
        except ValueError as e:
            if request.headers.get("accept", "").startswith("application/json"):
                return JSONResponse({"error": str(e)}, status_code=409)
            return RedirectResponse(f"{back}{'&' if '?' in back else '?'}error=" + quote(str(e)), status_code=303)
        chow.save(s)
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"ok": True, **(res if isinstance(res, dict) else {})})
    return RedirectResponse(back, status_code=303)


def chow_leader(request: Request) -> str:
    if not can_edit_chow(request):
        raise HTTPException(403, "Only leaders can change the chow schedule.")
    return request.state.member


@app.get("/chow", response_class=HTMLResponse)
@app.get("/chow/{tab}", response_class=HTMLResponse)
def chow_page(request: Request, tab: str = "schedule", error: str = "", mid: str = Depends(me)):
    s, club = chow.load(), archive.club
    leader = can_edit_chow(request)
    if tab not in ("schedule", "rotation", "history") or (tab != "schedule" and not leader):
        raise HTTPException(404)
    members = sorted((m for m in club.members.values() if m.status.lower() not in ("inactive", "silent key")),
                     key=lambda m: (m.last, m.first))
    today = dt.date.today()
    return page(request, "chow.html", s=s, error=error, leader=leader, tab=tab, members=members,
                upcoming=chow.upcoming(s, n=16), past=chow.past(s, n=16) if leader else [],
                mine=[d for d, x in chow.upcoming(s, n=60) if x.get("member") == mid and x.get("status") != "none"],
                asked=[r for r in s["swaps"] if r["status"] == "pending" and mid in (r["with"], r["requester"])],
                next_up=chow.next_up(club, s), today=today.isoformat(),
                default_until=(today + dt.timedelta(days=180)).isoformat(),
                log=chow.history(30) if leader else [], fmt=lambda d: dt.date.fromisoformat(d).strftime("%a %b %-d"))


@app.post("/chow/request")
def chow_request(request: Request, mine: str = Form(...), theirs: str = Form(...), mid: str = Depends(me)):
    return chow_change(request, lambda s: chow.request_swap(archive.club, s, mid, mine, theirs, base_url(request)))


@app.post("/chow/requests/{rid}/answer")
def chow_answer(request: Request, rid: str, approve: int = Form(0), mid: str = Depends(me)):
    return chow_change(request, lambda s: chow.decide_swap(archive.club, s, rid, mid, bool(approve), base_url(request)))


@app.post("/chow/assign")
def chow_assign(request: Request, date: str = Form(...), member: str = Form(""), mid: str = Depends(chow_leader)):
    dt.date.fromisoformat(date)
    return chow_change(request, lambda s: chow.assign(archive.club, s, date, member or None, mid, base_url(request)))


@app.post("/chow/none")
def chow_none(request: Request, date: str = Form(...), note: str = Form(""), mid: str = Depends(chow_leader)):
    dt.date.fromisoformat(date)
    return chow_change(request, lambda s: chow.set_none(s, date, note, mid))


@app.post("/chow/swap")
def chow_swap(request: Request, a: str = Form(...), b: str = Form(...), mid: str = Depends(chow_leader)):
    return chow_change(request, lambda s: chow.swap(archive.club, s, a, b, mid, base_url(request)))


@app.post("/chow/record")
def chow_record(request: Request, date: str = Form(...), status: str = Form(...), covered_by: str = Form(""),
                note: str = Form(""), next: str = Form("/chow/history"), mid: str = Depends(leader)):
    def run(s):
        chow.record(archive.club, s, date, status, mid, covered_by or None, note)
        return {"section": chow.minutes_section(archive.club, s, chow.history(), date)}  # for the console
    return chow_change(request, run, back=_safe_next(next))


@app.post("/chow/generate")
def chow_generate(request: Request, until: str = Form(...), next_member: str = Form(""), mid: str = Depends(chow_leader)):
    def run(s):
        if next_member:
            s["next"] = next_member
        if not chow.generate(archive.club, s, dt.date.fromisoformat(until), mid):
            raise ValueError("No open meeting nights to fill before that date.")
    return chow_change(request, run, back="/chow/rotation")


@app.post("/chow/order")
def chow_order(request: Request, member: str = Form(...), op: str = Form(...), mid: str = Depends(chow_leader)):
    """Rotation order: move a member up or down, add a waiting member at the bottom, or take one out."""
    def run(s):
        order = list(s["order"])
        if op == "add" and member in archive.club.members and member not in order:
            order.append(member)
        elif op == "remove" and member in order:
            order.remove(member)
            s["pending"].append(member)
        elif op in ("up", "down") and member in order:
            i = order.index(member)
            j = i - 1 if op == "up" else i + 1
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
        chow.set_order(s, order, mid)
    return chow_change(request, run, back="/chow/rotation")


@app.post("/chow/constraints")
async def chow_constraints(request: Request, mid: str = Depends(chow_leader)):
    form = await request.form()
    who = form.get("member", "")
    if who not in archive.club.members:
        raise HTTPException(404)
    weeks = [int(w) for w in form.getlist("not_weeks") if w.isdigit()]
    away = [[form.get("away_from", ""), form.get("away_to", "")]] if form.get("away_from") else []
    return chow_change(request, lambda s: chow.set_constraints(s, who, weeks, away, form.get("note", ""), mid),
                       back="/chow/rotation")


# ---------------- admin mode ----------------
ADMIN_MINUTES = 60


def _admin_log(request: Request, **entry) -> None:
    entry = {"at": int(dt.datetime.now().timestamp()), "member": request.state.real_member,
             "ip": request.client.host if request.client else None, **entry}
    p = DATA / "admin-log.jsonl"
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    p.chmod(0o600)


def _admin(mid: str) -> str:
    if not archive.club.is_admin(mid):
        raise HTTPException(403, "You aren't listed as an admin.")
    return mid


def _admin_on(request: Request, mid: str, how: str) -> None:
    until = authn.set_admin(request.cookies.get(COOKIE), ADMIN_MINUTES)
    _admin_log(request, on=True, until=until, confirmed_by=how)
    _log.info("admin mode on for %s (confirmed by %s)", mid, how)


@app.post("/admin/mode")
def admin_mode_switch(request: Request, on: int = Form(0), next: str = Form("/"), mid: str = Depends(real_me)):
    """Admins turn admin mode off at once; turning it on first asks them to confirm it's really them."""
    _admin(mid)
    if on:
        return RedirectResponse("/admin/confirm?next=" + quote(_safe_next(next)), status_code=303)
    until = authn.set_admin(request.cookies.get(COOKIE), 0)
    _admin_log(request, on=False, until=until)
    _log.info("admin mode off for %s", mid)
    return RedirectResponse(_safe_next(next), status_code=303)


@app.get("/admin/confirm", response_class=HTMLResponse)
def admin_confirm(request: Request, next: str = "/", sent: int = 0, error: str = "", mid: str = Depends(real_me)):
    """Step-up check before admin mode: a passkey where we can, else a one-time link emailed to the admin."""
    _admin(mid)
    passkey = request.url.hostname == authn.rp_id and bool(authn.passkeys(mid))
    return page(request, "admin_confirm.html", next=_safe_next(next), passkey=passkey, sent=sent, error=error,
                email=archive.club.members[mid].email)


@app.post("/admin/confirm/options")
def admin_confirm_options(mid: str = Depends(real_me)):
    _admin(mid)
    cid, options = authn.step_up_options(mid)
    response = Response(options, media_type="application/json")
    response.set_cookie(CHALLENGE_COOKIE, cid, max_age=300, httponly=True, samesite="strict", secure=True)
    return response


@app.post("/admin/confirm/verify")
async def admin_confirm_verify(request: Request, mid: str = Depends(real_me)):
    _admin(mid)
    body = await request.json()
    try:
        authn.authenticate(request.cookies.get(CHALLENGE_COOKIE), body["credential"], kind="step-up", member=mid)
    except Exception as e:
        raise HTTPException(400, str(e))
    _admin_on(request, mid, "passkey")
    return {"ok": True, "next": _safe_next(body.get("next", "/"))}


@app.post("/admin/confirm/email")
def admin_confirm_email(request: Request, next: str = Form("/"), mid: str = Depends(real_me)):
    _admin(mid)
    m = archive.club.members[mid]
    if not m.email:
        raise HTTPException(400, "There's no email address for you on the roster.")
    url = f"{base_url(request)}/admin/confirm/link?t={authn.step_up_link(mid)}&next={quote(_safe_next(next))}"
    # Only ever to the admin themself, so test mode (email.only_to) doesn't apply.
    authmod.send_email(m.email, "Turn on admin mode", f"Hi {m.first},\n\nSomeone signed in as you asked to turn on admin mode "
               f"in W8LBZ Minutes. If that was you, open this link in the same browser within 5 minutes:\n\n{url}\n\n"
               f"If it wasn't you, don't open it, and sign out your other sessions on your profile page.\n\n73,\nW8LBZ")
    _admin_log(request, step_up_email=True)
    return RedirectResponse("/admin/confirm?sent=1&next=" + quote(_safe_next(next)), status_code=303)


@app.get("/admin/confirm/link")
def admin_confirm_link(request: Request, t: str = "", next: str = "/", mid: str = Depends(real_me)):
    _admin(mid)
    if not authn.use_step_up_link(t, mid):
        return RedirectResponse("/admin/confirm?error=" + quote("That link has expired or was already used.")
                                + "&next=" + quote(_safe_next(next)), status_code=303)
    _admin_on(request, mid, "email")
    return RedirectResponse(_safe_next(next), status_code=303)


@app.post("/admin/view-as")
def admin_view_as(request: Request, member: str = Form(""), next: str = Form("/"), mid: str = Depends(real_me)):
    """Start (member=id) or stop (member empty) viewing the app as another member. Admin mode only; logged."""
    if not authn.admin_until(request.cookies.get(COOKIE)):
        raise HTTPException(403, "Turn on admin mode first.")
    if member and (member not in archive.club.members or member == mid):
        raise HTTPException(404)
    authn.set_view_as(request.cookies.get(COOKIE), member or None)
    _admin_log(request, view_as=member or None)
    _log.info("%s %s", mid, f"viewing as {member}" if member else "stopped viewing as another member")
    return RedirectResponse(_safe_next(next), status_code=303)


# ---------------- profile (own contact details and sharing) ----------------

def clean_address(text: str) -> str:
    """Keep the member's line breaks (the sheet stores addresses on several lines); tidy spaces and blank lines."""
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)[:200]


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, saved: int = 0, email_sent: str = "", error: str = "", mid: str = Depends(me)):
    return page(request, "profile.html", m=archive.club.members[mid], shareable=SHAREABLE,
                saved=saved, email_sent=email_sent, error=error)


@app.post("/profile")
async def profile_save(request: Request, mid: str = Depends(me)):
    form = await request.form()
    m = archive.club.members[mid]
    address = clean_address(form.get("address", ""))
    if address == clean_address(m.address or ""):  # untouched: don't rewrite the sheet over spacing
        address = m.address or ""
    try:
        bm, bd = int(form.get("bmonth") or 0), int(form.get("bday") or 0)
        birthday = f"{bm:02d}-{bd:02d}" if bm and bd and dt.date(2000, bm, bd) else ""
    except ValueError:
        return RedirectResponse("/profile?error=" + quote("That birthday isn't a real date."), status_code=303)
    new = {"phone": form.get("phone", "").strip()[:40], "address": address, "birthday": birthday,
           "share": ", ".join(f for f in SHAREABLE if f in form.getlist("share"))}
    try:
        profile.change(archive.club, mid, new, by=mid, url=base_url(request))
    except SheetError as e:
        return RedirectResponse("/profile?error=" + quote(str(e)), status_code=303)
    email = form.get("email", "").strip()
    if email and email.lower() != (m.email or "").lower():
        err = authn.start_email_change(mid, email, base_url(request))
        if err:
            return RedirectResponse("/profile?saved=1&error=" + quote(err), status_code=303)
        return RedirectResponse("/profile?saved=1&email_sent=" + quote(email), status_code=303)
    return RedirectResponse("/profile?saved=1", status_code=303)


@app.get("/profile/email")
def profile_email_confirm(request: Request, t: str = "", mid: str = Depends(me)):
    got = authn.confirm_email_change(t)
    if not got or got[0] != mid:
        return RedirectResponse("/profile?error=" + quote("That confirmation link is invalid or expired."), status_code=303)
    try:
        profile.change(archive.club, mid, {"email": got[1]}, by=mid, url=base_url(request))
    except SheetError as e:
        return RedirectResponse("/profile?error=" + quote(str(e)), status_code=303)
    return RedirectResponse("/profile?saved=1", status_code=303)


def roster_keeper(request: Request) -> str:
    """Adding members: the offices in roster_keepers (Secretary and Treasurer by default), or admin mode."""
    if not (archive.club.keeps_roster(request.state.member) or admin_mode(request)):
        raise HTTPException(403, "Only the Secretary or Treasurer can add members.")
    return request.state.member


@app.get("/roster/add", response_class=HTMLResponse)
def roster_add_form(request: Request, guest: str = "", error: str = "", mid: str = Depends(roster_keeper)):
    ready = membership.ready_guests(archive.guests(), int(archive.club.info.get("invite_after_visits", 3)))
    g = next((x for x in ready if x["name"] == guest), None)
    first, last = membership.split_name(g["name"]) if g else ("", "")
    f = {"first": first, "last": last, "callsign": (g or {}).get("callsign") or ""}
    return page(request, "roster_add.html", ready=ready, guest=g, f=f, error=error, classes=membership.CLASSES,
                today=dt.date.today().isoformat(), invite_after=archive.club.info.get("invite_after_visits", 3))


@app.post("/roster/add", response_class=HTMLResponse)
async def roster_add(request: Request, mid: str = Depends(roster_keeper)):
    form = dict(await request.form())
    try:
        new = membership.add_member(archive.club, form, mid, url=base_url(request))
    except (ValueError, SheetError) as e:
        ready = membership.ready_guests(archive.guests(), int(archive.club.info.get("invite_after_visits", 3)))
        return page(request, "roster_add.html", ready=ready, guest=None, f=form, error=str(e),
                    classes=membership.CLASSES, today=dt.date.today().isoformat(),
                    invite_after=archive.club.info.get("invite_after_visits", 3))
    return RedirectResponse(f"/members/{new}?added=1", status_code=303)


@app.get("/roster/changes", response_class=HTMLResponse)
def roster_changes(request: Request, error: str = "", mid: str = Depends(officer)):
    return page(request, "changes.html", changes=profile.history(), labels=profile.LABELS, error=error)


@app.post("/roster/changes/{cid}/undo")
def roster_change_undo(request: Request, cid: str, mid: str = Depends(officer)):
    try:
        profile.undo(archive.club, cid, by=mid, url=base_url(request))
    except (ValueError, SheetError) as e:
        return RedirectResponse("/roster/changes?error=" + quote(str(e)), status_code=303)
    return RedirectResponse("/roster/changes", status_code=303)


@app.post("/account/passkeys/{pid}/rename")
def rename_passkey(pid: str, label: str = Form(""), mid: str = Depends(me)):
    authn.rename_passkey(mid, pid, label)
    return RedirectResponse("/account", status_code=303)


@app.post("/account/passkeys/{pid}/remove")
def remove_passkey(pid: str, mid: str = Depends(me)):
    authn.remove_passkey(mid, pid)
    return RedirectResponse("/account", status_code=303)


@app.post("/account/sessions/end-all")
def end_all_sessions(mid: str = Depends(me)):
    authn.end_all_sessions(mid)
    return RedirectResponse("/login", status_code=303)


@app.post("/auth/passkey/register/options")
def passkey_register_options(request: Request, mid: str = Depends(me)):
    cid, options = authn.registration_options(mid)
    response = Response(options, media_type="application/json")
    response.set_cookie(CHALLENGE_COOKIE, cid, max_age=300, httponly=True, samesite="strict", secure=True)
    return response


@app.post("/auth/passkey/register/verify")
async def passkey_register_verify(request: Request, mid: str = Depends(me)):
    body = await request.json()
    try:
        authn.register(mid, request.cookies.get(CHALLENGE_COOKIE), body["credential"], body.get("label", ""))
    except Exception as e:  # verification errors come from several exception types
        raise HTTPException(400, f"Couldn't add the passkey: {e}")
    return {"ok": True}


@app.post("/auth/passkey/login/options")
def passkey_login_options():
    cid, options = authn.authentication_options()
    response = Response(options, media_type="application/json")
    response.set_cookie(CHALLENGE_COOKIE, cid, max_age=300, httponly=True, samesite="strict", secure=True)
    return response


@app.post("/auth/passkey/login/verify")
async def passkey_login_verify(request: Request):
    body = await request.json()
    try:
        member = authn.authenticate(request.cookies.get(CHALLENGE_COOKIE), body["credential"])
    except Exception as e:
        raise HTTPException(400, str(e))
    if not authn.is_active(member):
        raise HTTPException(403, "Your roster entry isn't active.")
    return start_session(request, JSONResponse({"ok": True, "next": _safe_next(body.get("next", "/"))}), member)


# ---------------- archive ----------------

PER_OPTIONS = (10, 25, 50, 0)  # list page sizes; 0 = all


def paginate(items: list, p: str, per: str, default: int = 25) -> dict:
    """One page of a long list. p and per come from the query string as text (junk falls back to defaults)."""
    n = int(per) if per.isdigit() and int(per) in PER_OPTIONS else default
    size = n or max(len(items), 1)
    pages = max(1, -(-len(items) // size))
    p = min(max(int(p) if p.isdigit() else 1, 1), pages)
    rows = items[(p - 1) * size:p * size]
    return {"rows": rows, "p": p, "pages": pages, "per": n, "options": PER_OPTIONS, "total": len(items),
            "first": (p - 1) * size + 1 if rows else 0, "last": (p - 1) * size + len(rows)}


def years() -> list[int]:
    """Years with minutes, and always this year (the default period, even before its first meeting)."""
    return sorted({m.date.year for m in archive.meetings} | {dt.date.today().year}, reverse=True)


def by_period(period: str) -> tuple[list, str, str]:
    """Meetings for a period choice: this year (default), 6m, 12m, all, or a year. -> (meetings, period, label)."""
    today = dt.date.today()
    if period in ("6m", "12m"):
        cutoff = today - dt.timedelta(days=182 if period == "6m" else 365)
        label = "in the last 6 months" if period == "6m" else "in the last 12 months"
        return [m for m in archive.meetings if m.date > cutoff], period, label
    if period == "all":
        return list(archive.meetings), "all", "on record"
    year = int(period) if period.isdigit() else today.year
    return [m for m in archive.meetings if m.date.year == year], str(year), f"in {year}"


@app.get("/", response_class=HTMLResponse)
def index(request: Request, period: str = "", p: str = Query("1", alias="page"), per: str = ""):
    """Meetings newest first, a page at a time, for a period (this year by default)."""
    ms, period, label = by_period(period)
    return page(request, "index.html", pg=paginate(ms, p, per), years=years(), period=period, label=label)


@app.get("/meetings/{slug}", response_class=HTMLResponse)
def view(request: Request, slug: str):
    m = get_meeting(slug)
    has_original = (archive.root / slug / "original.pdf").exists()
    return page(request, "meeting.html", m=m, has_original=has_original,
                emailed=console.email_status(archive, slug))


def render_pdf(m) -> tuple[str, bytes]:
    """(file name, PDF bytes) for submitted minutes."""
    try:
        from weasyprint import HTML
    except OSError as e:  # missing system libraries (pango)
        raise HTTPException(503, f"PDF rendering unavailable on this server: {e}")
    html = templates.get_template("minutes_doc.html").render(m=m, pdf=True)
    return f"{m.date.day}-{m.date:%b}-{m.date:%y}-minutes.pdf".lower(), HTML(string=html, base_url=str(HERE)).write_pdf()


@app.get("/meetings/{slug}/minutes.pdf")
def pdf(request: Request, slug: str):
    m = get_meeting(slug)
    if m.status == "draft":
        raise HTTPException(409, "This meeting is still in progress; the PDF is available once the minutes are submitted.")
    fname, data = render_pdf(m)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@app.get("/meetings/{slug}/original.pdf")
def original(slug: str):
    p = archive.root / slug / "original.pdf"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    results = archive.search(q) if q else []
    for r in results:
        r["date"] = archive.by_slug[r["slug"]].date
    return page(request, "search.html", q=q, results=results)


@app.get("/members/{mid}", response_class=HTMLResponse)
def member(request: Request, mid: str):
    if mid not in archive.club.members:
        raise HTTPException(404)
    m, viewer, club = archive.club.members[mid], request.state.member, archive.club
    values = {"email": (m.email, f"mailto:{m.email}"), "phone": (m.phone, f"tel:{m.phone}"),
              "address": (m.address, None), "birthday": (monthday(m.birthday), None)}
    # (field, value, link), with the value blank unless this viewer may see it (club.can_see)
    elevated = admin_mode(request)
    contact = [(f, v if v and club.can_see(viewer, mid, f, elevated) else None, href) for f, (v, href) in values.items()]
    return page(request, "member.html", member=m, h=archive.member_history(mid), total=len(archive.meetings),
                contact=contact, is_me=viewer == mid, is_officer=privileged(request),
                can_view_as=elevated and mid != request.state.real_member)


@app.get("/roster", response_class=HTMLResponse)
def roster(request: Request, status: str = "Active", p: str = Query("1", alias="page"), per: str = ""):
    """Everyone on the roster; contact details are on each member's own page."""
    def since(m):
        try:
            return dt.date.fromisoformat(m.member_since) if m.member_since else None
        except ValueError:
            return None
    gone = ("inactive", "silent key")
    ms = sorted(archive.club.members.values(), key=lambda m: (m.status.lower() in gone, m.last, m.first))
    statuses = sorted({m.status for m in ms}, key=lambda x: (x != "Active", x))
    shown = [m for m in ms if status == "all" or m.status == status]
    return page(request, "roster.html", pg=paginate([(m, since(m)) for m in shown], p, per, 50),
                active=sum(m.status.lower() not in gone for m in ms), statuses=statuses, status=status,
                is_officer=privileged(request),
                can_add=archive.club.keeps_roster(request.state.member) or admin_mode(request))


@app.get("/bylaws", response_class=HTMLResponse)
def bylaws(request: Request):
    """The club's constitution and bylaws, from bylaws.md in the data directory (not in this public repo)."""
    import markdown
    p = DATA / "bylaws.md"
    html = Markup(markdown.markdown(p.read_text())) if p.exists() else None
    return page(request, "bylaws.html", html=html)


LINK_ICONS = (("teams.", "video"), ("zoom.", "video"), ("meet.", "video"), ("discord.", "chat"),
              ("/bylaws", "document"), ("docs.google.", "document"), (".pdf", "document"), ("calendar", "calendar"))


def link_icon(url: str) -> str:
    """Icon name for a club link, guessed from its address. In club.yaml a link can set `icon:` to one of
    video, chat, globe, document, radio, calendar or link."""
    u = url.lower()
    return next((icon for key, icon in LINK_ICONS if key in u), "globe" if u.count("/") <= 3 else "link")


templates.env.filters["link_icon"] = link_icon


def link_host(url: str) -> str:
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return "on this site" if host == authn.rp_id else host


templates.env.filters["link_host"] = link_host


def _license(dist: str) -> str:
    md = metadata(dist)
    lic = md.get("License-Expression") or ""
    if not lic:
        lic = next((c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")), "")
    if not lic and len(md.get("License") or "") <= 40:
        lic = md.get("License") or ""
    return lic.replace(" Software License", "").replace(" License", "") or "see project"


def dependencies() -> list[dict]:
    """The app's direct dependencies, as installed: name, version, license and home page."""
    out = []
    for req in requires("w8lbz-minutes") or []:
        if "extra ==" in req:
            continue
        name = re.split(r"[\s\[<>=!~;]", req, maxsplit=1)[0]
        md = metadata(name)
        urls = dict(u.split(", ", 1) for u in md.get_all("Project-URL") or [] if ", " in u)
        home = md.get("Home-page") or urls.get("Homepage") or urls.get("Source") or next(iter(urls.values()), None)
        out.append({"name": md["Name"], "version": version(name), "license": _license(name), "url": home})
    return sorted(out, key=lambda d: d["name"].lower())


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    import markdown
    changes = (Path(__file__).resolve().parents[2] / "CHANGELOG.md")
    changelog = None
    if changes.exists():  # show the versions, without the file's own title and intro
        text = re.sub(r"## Unreleased\s*(?=## )", "", changes.read_text())  # hide an empty Unreleased section
        changelog = Markup(markdown.markdown(text[text.find("\n## "):]))
    return page(request, "about.html", deps=dependencies(), changelog=changelog, license=_license("w8lbz-minutes"))


@app.get("/preview/outbox", response_class=HTMLResponse)
def preview_outbox(request: Request):
    """Preview mode only: the emails the app would have sent."""
    p = DATA / "preview-outbox.jsonl"
    if not PREVIEW or not archive.club.is_admin(request.state.real_member):
        raise HTTPException(404)
    mail = [json.loads(line) for line in p.read_text().splitlines()][::-1] if p.exists() else []
    return page(request, "outbox.html", mail=mail)


@app.get("/links", response_class=HTMLResponse)
def links(request: Request):
    return page(request, "links.html")


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request, period: str = "", p: str = Query("1", alias="page"), per: str = ""):
    """Attendance for a period: this year (default), the last 6 or 12 months, all time, or one year."""
    ms, period, label = by_period(period)
    st = archive.stats(ms)
    return page(request, "stats.html", s=st, pg=paginate(st["rows"], p, per, 10),
                period=period, label=label, years=years())


@app.get("/guests", response_class=HTMLResponse)
def guests(request: Request):
    return page(request, "guests.html", guests=archive.guests())


@app.get("/api/meetings/{slug}/live", response_class=HTMLResponse)
def live_fragment(request: Request, slug: str):
    """The rendered minutes, for members following along (polled)."""
    return templates.get_template("_minutes.html").render(m=get_meeting(slug), pdf=False, club=archive.club,
                                                          SECTIONS=SECTIONS)


# ---------------- leader console (officers + minutes editors) ----------------

@app.get("/console", response_class=HTMLResponse)
def console_home(request: Request, mid: str = Depends(leader)):
    drafts = [m for m in archive.meetings if m.status == "draft"]
    leaders = sorted(archive.club.leaders, key=archive.club.name)
    return page(request, "console_start.html", drafts=drafts, leaders=leaders, today=dt.date.today())


@app.post("/console/start")
def console_start(date: str = Form(...), leader_id: str = Form("", alias="leader"), mid: str = Depends(leader)):
    m = console.start(archive, dt.date.fromisoformat(date), leader_id or mid)
    return RedirectResponse(f"/console/{m.slug}", status_code=303)


@app.get("/console/{slug}", response_class=HTMLResponse)
def console_page(request: Request, slug: str, mid: str = Depends(leader)):
    m = get_meeting(slug)
    if m.status == "published":
        return RedirectResponse(f"/meetings/{slug}", status_code=303)
    ctx = console.context(archive, m)
    return page(request, "console.html", m=m, data=json.dumps(ctx),
                leaders=sorted(archive.club.leaders, key=archive.club.name))


@app.put("/api/meetings/{slug}")
async def console_save(request: Request, slug: str, mid: str = Depends(leader)):
    get_meeting(slug)
    try:
        console.apply(archive, slug, await request.json())
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


def email_minutes(slug: str, url: str) -> None:
    console.email_minutes(archive, slug, lambda: render_pdf(archive.by_slug[slug]), url)


@app.post("/console/{slug}/submit")
def console_submit(request: Request, background: BackgroundTasks, slug: str, mid: str = Depends(leader)):
    get_meeting(slug)
    console.submit(archive, slug)
    background.add_task(email_minutes, slug, f"{base_url(request)}/meetings/{slug}")
    background.add_task(followups_after_submit, slug)
    return RedirectResponse(f"/meetings/{slug}", status_code=303)


@app.post("/console/{slug}/discard")
def console_discard(slug: str, mid: str = Depends(leader)):
    get_meeting(slug)
    try:
        console.discard(archive, slug)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return RedirectResponse("/console", status_code=303)
