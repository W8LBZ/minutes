"""AI assistance, through OpenRouter (so the model can be chosen and changed in club.yaml).

Ground rules (ROADMAP):
- A person always approves. The AI only ever *suggests*; nothing is added or changed until a leader
  accepts it, and suggestions are marked as AI until then.
- Lines naming anyone on the never-record list are dropped before any text leaves the server.
- Each call is logged (when, what for, model, size, cost), never the text itself.

Configuration: `ai: {model: ...}` in club.yaml and the API key in the environment
(W8LBZ_OPENROUTER_KEY, e.g. in /etc/w8lbz-minutes/env). Without both, AI features stay hidden.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import time

from .club import DATA, Club
from .meeting import Meeting

log = logging.getLogger("w8lbz.ai")
URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_SUGGESTIONS = 8
SECTIONS_READ = ("Bills and Communications", "Community Reports", "Old Business", "New Business", "Upcoming Events")


class AIError(Exception):
    pass


def configured(club: Club) -> bool:
    return bool(os.environ.get("W8LBZ_OPENROUTER_KEY") and club.ai.get("model") and club.ai.get("enabled", True))


def _log(entry: dict) -> None:
    p = DATA / "ai-log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"at": int(time.time()), **entry}) + "\n")
    p.chmod(0o600)


def complete(club: Club, system: str, user: str, purpose: str, post=None) -> str:
    """One chat completion; returns the reply text. `post` replaces requests.post in tests."""
    if not configured(club):
        raise AIError("AI isn't set up (club.yaml ai.model and W8LBZ_OPENROUTER_KEY).")
    if post is None:
        import requests
        post = requests.post
    body = {"model": club.ai["model"], "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "usage": {"include": True}}
    started = time.time()
    try:
        r = post(URL, json=body, timeout=90, headers={
            "Authorization": f"Bearer {os.environ['W8LBZ_OPENROUTER_KEY']}",
            "X-Title": f"{club.info.get('callsign', 'Club')} Minutes"})
        if r.status_code != 200:
            raise AIError(f"OpenRouter answered {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
    except AIError as e:
        _log({"purpose": purpose, "model": club.ai["model"], "error": str(e)})
        raise
    except Exception as e:
        _log({"purpose": purpose, "model": club.ai["model"], "error": str(e)[:200]})
        raise AIError(f"The AI service didn't answer: {e}") from e
    usage = data.get("usage") or {}
    _log({"purpose": purpose, "model": data.get("model", club.ai["model"]), "seconds": round(time.time() - started, 1),
          "sent_chars": len(system) + len(user), "tokens_in": usage.get("prompt_tokens"),
          "tokens_out": usage.get("completion_tokens"), "cost": usage.get("cost")})
    return text


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError(f"The AI's answer wasn't valid JSON: {e}") from e


def safe_lines(club: Club, lines: list[str]) -> list[str]:
    """Drop any line that names someone on the never-record list, before text leaves the server."""
    return [x for x in lines if x.strip() and not club.is_redacted(x)]


# ---------------- suggested follow-ups ----------------

SYSTEM_FOLLOWUPS = """You help the Secretary of a small amateur radio club keep track of follow-ups from its weekly meeting minutes.

From the minutes you are given, suggest tracked business items: things someone said they would do, decisions that need someone to act, or plans with a date. For each, give a short item in plain words (close to the minutes' own wording), the member who owns it if the minutes make that clear, and a due date only if the minutes give or clearly imply one.

You may also suggest an owner or due date for an item that is already tracked, if tonight's minutes make it clear (kind "update", with its id).

Rules:
- Only what the minutes support. Don't invent owners, dates or tasks. Fewer, solid suggestions beat many weak ones.
- Don't suggest anything already tracked unless you are adding an owner or due date to it.
- Skip routine reports with nothing to follow up (e.g. "worked some DX", "the repeater is fine"), drawings and chow.
- Owners must be member ids from the roster list. Dates are YYYY-MM-DD, on or after the meeting date.
- "why" is one short sentence quoting or pointing to the line it came from.

Answer with JSON only: {"suggestions": [{"kind": "new" | "update", "item": null | "<tracked item id>", "text": "...", "owner": null | "<member id>", "due": null | "YYYY-MM-DD", "why": "..."}]}. An empty list is a fine answer."""


def followups_prompt(club: Club, m: Meeting, open_items: list[dict]) -> str:
    members = [f"{x.id}: {x.name}" + (f" ({x.callsign})" if x.callsign else "")
               for x in sorted(club.members.values(), key=lambda x: (x.last, x.first))
               if x.status.lower() not in ("inactive", "silent key")]
    tracked = [f"{x['id']} | {x['text']} | owner: {x['owner'] or '-'} | due: {x['due'] or '-'}"
               for x in open_items if not club.is_redacted(x["text"])]
    parts = [f"Meeting date: {m.slug} ({m.date.strftime('%A')})", "", "Roster (id: name):", *members, "",
             "Already tracked (id | item | owner | due):", *(tracked or ["(none)"]), "", "Tonight's minutes:"]
    for sec in SECTIONS_READ:
        lines = safe_lines(club, [i.text for i in m.items(sec)])
        if lines:
            parts += [f"## {sec}", *[f"- {x}" for x in lines]]
    return "\n".join(parts)


def suggest_followups(club: Club, m: Meeting, open_items: list[dict], post=None) -> list[dict]:
    """Ask the AI for follow-ups from a meeting's minutes; returns checked suggestions (never applied here)."""
    reply = _json(complete(club, SYSTEM_FOLLOWUPS, followups_prompt(club, m, open_items), f"followups {m.slug}", post))
    ids = {x["id"] for x in open_items}
    out = []
    for x in (reply.get("suggestions") or [])[:MAX_SUGGESTIONS]:
        if not isinstance(x, dict):
            continue
        kind = "update" if x.get("kind") == "update" and x.get("item") in ids else "new"
        text = " ".join(str(x.get("text") or "").split())[:300]
        owner = x.get("owner") if x.get("owner") in club.members else None
        try:
            due = dt.date.fromisoformat(str(x.get("due"))).isoformat() if x.get("due") else None
        except ValueError:
            due = None
        if due and due < m.slug:
            due = None
        if kind == "new" and not text:
            continue
        if kind == "update" and not (owner or due):
            continue
        if club.is_redacted(text):
            continue
        out.append({"kind": kind, "item": x.get("item") if kind == "update" else None, "text": text,
                    "owner": owner, "due": due, "why": " ".join(str(x.get("why") or "").split())[:300]})
    return out


# ---------------- "ask about" prompts for Community Reports ----------------

SYSTEM_ASK = """You help the leader of a small amateur radio club's weekly meeting. During community reports each member says what they've been doing on the radio, and the leader likes to follow up on what they said before.

For each member you get their recent reports, oldest first. Give at most two short prompts for the leader: things worth asking about now, such as a project they were building, a plan or trip they mentioned, a problem they were fixing, an event or contest they were going to, or a license exam they were studying for.

Rules:
- Leave out routine or finished things ("nothing new", "worked some stations", something they already said was done) and anything a later report already settled.
- Each prompt is under 12 words and starts with a verb, e.g. "Ask how the 40 m dipole build went." Use the member's own subject words; never invent details.
- An empty list is the right answer when nothing needs a follow-up.

Answer with JSON only: {"members": {"<member id>": ["...", "..."]}}, including every member id you were given."""

MAX_ASK = 2


def ask_about(club: Club, histories: dict[str, list[tuple[str, str]]], post=None) -> dict[str, list[str]]:
    """histories: member id -> [(date, report text)], oldest first. Returns id -> up to two prompts."""
    lines = []
    for mid, reports in histories.items():
        kept = [(d, t) for d, t in reports if not club.is_redacted(t)]
        if not kept or mid not in club.members:
            continue
        lines += [f"### {mid} ({club.members[mid].name})", *[f"- {d}: {t}" for d, t in kept], ""]
    if not lines:
        return {}
    reply = _json(complete(club, SYSTEM_ASK, "\n".join(lines), "ask-about", post))
    out = {}
    for mid, prompts in (reply.get("members") or {}).items():
        if mid in histories and isinstance(prompts, list):
            out[mid] = [" ".join(str(p).split())[:120] for p in prompts if str(p).strip()
                        and not club.is_redacted(str(p))][:MAX_ASK]
    return out
