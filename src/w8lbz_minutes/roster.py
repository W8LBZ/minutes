"""Roster sync from the club's Google Sheet, the single source of truth for people.

Reads columns by header name, so adding or reordering columns doesn't break it.
Columns used: callsign, full_name, email, Title(s), is_officer, is_board, Class,
minutes_editor (may lead meetings and edit minutes), Status (Active / Inactive /
Silent Key / Prospect) and aliases (comma-separated spellings seen in old minutes).

Only the fields the app needs are cached (no phone or address).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .club import ROOT, ROSTER_CACHE as CACHE

KEY_FILE = Path(os.environ.get("W8LBZ_GOOGLE_KEY", ROOT / "private" / "google-service-account.json"))


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("true", "yes", "y", "1", "x")


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def _sheet() -> tuple[str, str]:
    """Sheet ID and tab come from local club.yaml (`roster:`), never from code in git."""
    import yaml
    cfg = yaml.safe_load(Path(os.environ.get("W8LBZ_CONFIG", ROOT / "club.yaml")).read_text()) or {}
    r = cfg.get("roster") or {}
    if not r.get("sheet_id"):
        raise SystemExit("Set roster.sheet_id in club.yaml")
    return r["sheet_id"], r.get("tab", "Member Roster")


def fetch_rows() -> list[dict[str, str]]:
    import google.auth.transport.requests as gr
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        KEY_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    r = gr.AuthorizedSession(creds).get(
        "https://sheets.googleapis.com/v4/spreadsheets/{}/values/{}".format(*_sheet()))
    r.raise_for_status()
    values = r.json().get("values", [])
    if not values:
        return []
    header = [h.strip().lower() for h in values[0]]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]


def to_members(rows: list[dict[str, str]]) -> list[dict]:
    out = []
    for r in rows:
        name, cs = r.get("full_name", "").strip(), r.get("callsign", "").strip().upper()
        if not name or not cs:
            continue
        first, _, last = name.partition(" ")
        titles = _split(r.get("title(s)", ""))
        out.append({
            "id": cs.lower(),
            "first": first,
            "last": last,
            "callsign": cs,
            "email": r.get("email", "").strip() or None,
            "role": ", ".join(titles) or None,
            "officer": _truthy(r.get("is_officer", "")),
            "board": _truthy(r.get("is_board", "")),
            "license_class": r.get("class", "").strip() or None,
            "aliases": _split(r.get("aliases", "")),
            "minutes_editor": _truthy(r.get("minutes_editor", "")),
            "status": r.get("status", "").strip() or "Active",
        })
    return out


def sync() -> list[dict]:
    members = to_members(fetch_rows())
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(members, indent=1))
    tmp.chmod(0o600)
    tmp.replace(CACHE)
    return members


def load_cached() -> list[dict] | None:
    return json.loads(CACHE.read_text()) if CACHE.exists() else None
