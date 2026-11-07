"""Updating the app from its own admin page.

- "Update available": the latest GitHub release vs. the running version, checked at most every few hours.
- "Update now": the app runs as the unprivileged `minutes` user, so it only writes update-request.json in
  its data folder. A root-owned systemd path unit (deploy/w8lbz-minutes-update.path) notices the file and
  runs deploy/update-from-app.sh, which runs update.sh (the same as a manual update: latest main) and writes
  update-status.json for this page. The app can't make it do anything else.
- Deploy notes: a release whose CHANGELOG section has a "Deploy notes:" line needs extra steps by hand
  (a config change, a data file). The page shows them and an admin must confirm they're done first.
"""
from __future__ import annotations

import json
import logging
import re
import time
from importlib.metadata import version as installed_version

from .club import DATA, PREVIEW

log = logging.getLogger("w8lbz.updates")
REPO = "W8LBZ/minutes"
STUCK_AFTER = 600  # seconds a request may wait before the page says the updater didn't pick it up
CHECK_EVERY = 3600  # GitHub allows 60 unauthenticated checks an hour; one is plenty


def running() -> str:
    return installed_version("w8lbz-minutes")


def _v(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def newer(a: str, b: str) -> bool:
    """Is version a newer than version b?"""
    return _v(a) > _v(b)


def deploy_notes(notes: str) -> list[str]:
    """Lines under a "Deploy notes:" marker in a release's notes (its CHANGELOG section)."""
    out, on = [], False
    for line in notes.splitlines():
        m = re.match(r"^\s*[-*]?\s*\**Deploy notes:?\**:?\s*(.*)$", line, re.I)
        if m:
            on = True
            if m.group(1).strip():
                out.append(m.group(1).strip())
            continue
        if on:
            if line.startswith("  ") and line.strip():
                out.append(line.strip().lstrip("-* ").strip())
            elif line.strip():
                on = False
    return out


def latest(fetch=None, force: bool = False) -> dict | None:
    """The latest GitHub release: {version, notes, url, deploy_notes}; cached in update-check.json."""
    cache = DATA / "update-check.json"
    if not force and cache.exists():
        c = json.loads(cache.read_text())
        if time.time() - c.get("at", 0) < CHECK_EVERY:
            return c.get("release")
    try:
        if fetch is None:
            import requests
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=10,
                             headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            data = r.json()
        else:
            data = fetch()
        notes = data.get("body") or ""
        rel = {"version": data["tag_name"].lstrip("v"), "notes": notes, "url": data.get("html_url"),
               "deploy_notes": deploy_notes(notes)}
    except Exception as e:
        log.warning("update check failed: %s", e)
        return json.loads(cache.read_text()).get("release") if cache.exists() else None
    cache.write_text(json.dumps({"at": int(time.time()), "release": rel}))
    return rel


def available(fetch=None) -> dict | None:
    """The latest release if it's newer than what's running."""
    rel = latest(fetch)
    return rel if rel and newer(rel["version"], running()) else None


def status() -> dict:
    """{"requested": {...}} while an update is waiting or running, and the last result."""
    out = {}
    for key, name in (("requested", "update-request.json"), ("running", "update-running.json"),
                      ("last", "update-status.json")):
        p = DATA / name
        if p.exists():
            try:
                out[key] = json.loads(p.read_text())
            except ValueError:
                out[key] = {}
    req = out.get("requested")
    if req and "running" not in out and time.time() - req.get("at", 0) > STUCK_AFTER:
        out["stuck"] = True  # nothing on the server picked it up: the updater isn't installed or failed to start
    return out


def cancel() -> bool:
    """Withdraw a request the updater never picked up."""
    p = DATA / "update-request.json"
    if p.exists():
        p.unlink()
        return True
    return False


def request(by: str, target: str, notes_confirmed: bool) -> None:
    """Ask the root-owned updater to run. Raises ValueError if it can't be asked now."""
    if PREVIEW:
        raise ValueError("Previews don't update themselves; use deploy/preview.sh.")
    st = status()
    if "requested" in st or "running" in st:
        raise ValueError("An update is already waiting or running.")
    rel = latest()
    if rel and rel.get("deploy_notes") and not notes_confirmed:
        raise ValueError("This release needs the steps under Deploy notes first. Tick the box once they're done.")
    p = DATA / "update-request.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": int(time.time()), "by": by, "from": running(), "to": target}))
    tmp.replace(p)  # the path unit fires on the file appearing
