"""Web UI: archive, minutes view and PDF, search, member history, stats, guests, leader console."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import console
from .meeting import SECTIONS
from .store import Archive

HERE = Path(__file__).parent
app = FastAPI(title="W8LBZ Minutes")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
archive = Archive()

URL_RE = re.compile(r"(https?://[^\s<]+[^\s<.,)])")


def linkify(text: str) -> Markup:
    return Markup(URL_RE.sub(r'<a href="\1">\1</a>', str(escape(text))))


templates.env.filters["linkify"] = linkify
templates.env.filters["longdate"] = lambda d: f"{d:%A, %B} {d.day}, {d.year}"
templates.env.globals.update(club=archive.club, SECTIONS=SECTIONS)


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


def get_meeting(slug: str):
    m = archive.by_slug.get(slug)
    if not m:
        raise HTTPException(404, "No minutes for that date")
    return m


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request, "index.html", meetings=archive.meetings)


@app.get("/meetings/{slug}", response_class=HTMLResponse)
def view(request: Request, slug: str):
    m = get_meeting(slug)
    has_original = (archive.root / slug / "original.pdf").exists()
    return page(request, "meeting.html", m=m, has_original=has_original)


@app.get("/meetings/{slug}/minutes.pdf")
def pdf(request: Request, slug: str):
    m = get_meeting(slug)
    try:
        from weasyprint import HTML
    except OSError as e:  # missing system libraries (pango)
        raise HTTPException(503, f"PDF rendering unavailable on this server: {e}")
    html = templates.get_template("minutes_doc.html").render(m=m, pdf=True)
    data = HTML(string=html, base_url=str(HERE)).write_pdf()
    fname = f"{m.date.day}-{m.date:%b}-{m.date:%y}-minutes.pdf".lower()
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
    return page(request, "search.html", q=q, results=archive.search(q) if q else [])


@app.get("/members/{mid}", response_class=HTMLResponse)
def member(request: Request, mid: str):
    if mid not in archive.club.members:
        raise HTTPException(404)
    return page(request, "member.html", member=archive.club.members[mid], h=archive.member_history(mid),
                total=len(archive.meetings))


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    return page(request, "stats.html", s=archive.stats())


@app.get("/guests", response_class=HTMLResponse)
def guests(request: Request):
    return page(request, "guests.html", guests=archive.guests())


# ---------------- leader console ----------------
# NOTE: no login yet (LAN only). Leaders are picked from the roster's officers + minutes_editor.

@app.get("/console", response_class=HTMLResponse)
def console_home(request: Request):
    drafts = [m for m in archive.meetings if m.status == "draft"]
    leaders = sorted(archive.club.leaders, key=archive.club.name)
    return page(request, "console_start.html", drafts=drafts, leaders=leaders, today=dt.date.today())


@app.post("/console/start")
def console_start(date: str = Form(...), leader: str = Form("")):
    m = console.start(archive, dt.date.fromisoformat(date), leader or None)
    return RedirectResponse(f"/console/{m.slug}", status_code=303)


@app.get("/console/{slug}", response_class=HTMLResponse)
def console_page(request: Request, slug: str):
    m = get_meeting(slug)
    if m.status == "published":
        return RedirectResponse(f"/meetings/{slug}", status_code=303)
    ctx = console.context(archive, m)
    return page(request, "console.html", m=m, data=json.dumps(ctx),
                leaders=sorted(archive.club.leaders, key=archive.club.name))


@app.put("/api/meetings/{slug}")
async def console_save(request: Request, slug: str):
    get_meeting(slug)
    try:
        console.apply(archive, slug, await request.json())
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/api/meetings/{slug}/live", response_class=HTMLResponse)
def live_fragment(request: Request, slug: str):
    """The rendered minutes, for viewers following along (polled)."""
    return templates.get_template("_minutes.html").render(m=get_meeting(slug), pdf=False, club=archive.club,
                                                          SECTIONS=SECTIONS)


@app.post("/console/{slug}/submit")
def console_submit(slug: str):
    get_meeting(slug)
    console.submit(archive, slug)
    return RedirectResponse(f"/meetings/{slug}", status_code=303)


@app.post("/console/{slug}/discard")
def console_discard(slug: str):
    get_meeting(slug)
    try:
        console.discard(archive, slug)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return RedirectResponse("/console", status_code=303)
