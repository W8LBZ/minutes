"""Web UI: archive, minutes view and PDF, search, member history, stats, guests, leader console, login."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import console
from .auth import Auth, _safe_next
from .club import DATA
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
templates.env.filters["ts"] = lambda t: dt.datetime.fromtimestamp(t).strftime(DATES["list"]) if t else "never"
templates.env.globals.update(club=archive.club, SECTIONS=SECTIONS)


# ---------------- login gate ----------------

@app.middleware("http")
async def require_login(request: Request, call_next):
    request.state.member = authn.member_for(request.cookies.get(COOKIE))
    path = request.url.path
    if request.state.member or path.startswith(PUBLIC_PATHS):
        return await call_next(request)
    if request.method == "GET" and not path.startswith("/api/"):
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    return JSONResponse({"detail": "Please sign in"}, status_code=401)


def me(request: Request) -> str:
    return request.state.member


def leader(request: Request) -> str:
    if not archive.club.can_lead(request.state.member):
        raise HTTPException(403, "Only officers and minutes editors can lead a meeting.")
    return request.state.member


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    mid = getattr(request.state, "member", None)
    return templates.TemplateResponse(request, name, {
        "me": archive.club.members.get(mid) if mid else None,
        "can_lead": archive.club.can_lead(mid) if mid else False,
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

PER_PAGE = 26  # meetings per archive page: about half a year


def years() -> list[int]:
    return sorted({m.date.year for m in archive.meetings}, reverse=True)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, year: str = "", p: str = Query("1", alias="page")):
    """Meetings grouped by year, newest first. With ?year=, that year alone, PER_PAGE at a time."""
    # The "All years" option sends year= (empty); anything that isn't a number means all years.
    year = int(year) if year.isdigit() else None
    p = int(p) if p.isdigit() else 1
    if year:
        ms = [m for m in archive.meetings if m.date.year == year]
        pages = max(1, -(-len(ms) // PER_PAGE))
        p = min(max(p, 1), pages)
        groups = [(year, ms[(p - 1) * PER_PAGE:p * PER_PAGE], len(ms))]
    else:
        pages = 1
        groups = [(y, ms[:PER_PAGE], len(ms))
                  for y in years() for ms in [[m for m in archive.meetings if m.date.year == y]]]
    this_year = dt.date.today().year
    open_year = year or (this_year if this_year in years() else next(iter(years()), None))
    return page(request, "index.html", groups=groups, years=years(), year=year, open_year=open_year,
                p=p, pages=pages)


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
    return page(request, "member.html", member=archive.club.members[mid], h=archive.member_history(mid),
                total=len(archive.meetings))


@app.get("/roster", response_class=HTMLResponse)
def roster(request: Request):
    """Members' public-to-members details only: no phone, address or email."""
    def since(m):
        try:
            return dt.date.fromisoformat(m.member_since) if m.member_since else None
        except ValueError:
            return None
    gone = ("inactive", "silent key")
    ms = sorted(archive.club.members.values(), key=lambda m: (m.status.lower() in gone, m.last, m.first))
    return page(request, "roster.html", rows=[(m, since(m)) for m in ms],
                active=sum(m.status.lower() not in gone for m in ms))


@app.get("/bylaws", response_class=HTMLResponse)
def bylaws(request: Request):
    """The club's constitution and bylaws, from bylaws.md in the data directory (not in this public repo)."""
    import markdown
    p = DATA / "bylaws.md"
    html = Markup(markdown.markdown(p.read_text())) if p.exists() else None
    return page(request, "bylaws.html", html=html)


@app.get("/links", response_class=HTMLResponse)
def links(request: Request):
    return page(request, "links.html")


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request, period: str = "12m"):
    """Attendance for the last 12 months (default), all time, or one year."""
    if period == "all":
        ms, label = archive.meetings, "on record"
    elif period.isdigit():
        ms, label = [m for m in archive.meetings if m.date.year == int(period)], f"in {period}"
    else:
        period, cutoff = "12m", dt.date.today() - dt.timedelta(days=365)
        ms, label = [m for m in archive.meetings if m.date > cutoff], "in the last 12 months"
    return page(request, "stats.html", s=archive.stats(ms), period=period, label=label, years=years())


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
    return RedirectResponse(f"/meetings/{slug}", status_code=303)


@app.post("/console/{slug}/discard")
def console_discard(slug: str, mid: str = Depends(leader)):
    get_meeting(slug)
    try:
        console.discard(archive, slug)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return RedirectResponse("/console", status_code=303)
