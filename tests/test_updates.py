"""Updating from the admin page: the version check, deploy notes, and the request the root updater picks up."""
import json

import pytest

from w8lbz_minutes import updates

NOTES = """- **Business items are tracked** ...
- **Deploy notes:** copy business.json to /var/lib/w8lbz-minutes
  - add `admins:` to club.yaml
- **Reminders** ..."""


REAL_LATEST = updates.latest  # conftest stubs it out for every other test


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "latest", REAL_LATEST)
    monkeypatch.setattr(updates, "DATA", tmp_path)
    monkeypatch.setattr(updates, "PREVIEW", None)
    monkeypatch.setattr(updates, "running", lambda: "0.6.0")
    return tmp_path


def test_check_and_deploy_notes(env):
    assert updates.newer("0.10.0", "0.9.1") and not updates.newer("0.6.0", "0.6.0")
    assert updates.deploy_notes(NOTES) == ["copy business.json to /var/lib/w8lbz-minutes", "add `admins:` to club.yaml"]
    calls = []
    def fetch():
        calls.append(1)
        return {"tag_name": "v0.7.0", "body": NOTES, "html_url": "https://github.com/x"}
    rel = updates.available(fetch)
    assert rel["version"] == "0.7.0" and len(rel["deploy_notes"]) == 2
    updates.available(fetch)
    assert len(calls) == 1                              # cached for a few hours
    assert updates.latest(lambda: (_ for _ in ()).throw(OSError("offline")), force=True)["version"] == "0.7.0"  # keeps the last


def test_request(env, monkeypatch):
    monkeypatch.setattr(updates, "latest", lambda *a, **k: {"version": "0.7.0", "notes": NOTES, "deploy_notes": ["x"]})
    with pytest.raises(ValueError):
        updates.request("ko4cgq", "0.7.0", notes_confirmed=False)       # steps by hand come first
    updates.request("ko4cgq", "0.7.0", notes_confirmed=True)
    req = json.loads((env / "update-request.json").read_text())
    assert req["by"] == "ko4cgq" and req["from"] == "0.6.0" and req["to"] == "0.7.0"
    assert "requested" in updates.status()
    with pytest.raises(ValueError):
        updates.request("ko4cgq", "0.7.0", True)                          # one at a time
    monkeypatch.setattr(updates, "PREVIEW", "branch")
    (env / "update-request.json").unlink()
    with pytest.raises(ValueError):
        updates.request("ko4cgq", "0.7.0", True)                          # previews never update themselves


def test_admin_page(env, tmp_path, monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.auth import Auth
    from w8lbz_minutes.club import Club
    from w8lbz_minutes.store import Archive
    club = Club(Path(__file__).parent / "fixtures" / "test-club.yaml",
                roster=[{"id": "ko4cgq", "first": "Jim", "last": "F", "callsign": "KO4CGQ"}, {"id": "bob", "first": "Bob", "last": "B"}])
    club.admins = {"ko4cgq"}
    a = Auth(club, tmp_path / "auth.sqlite")
    monkeypatch.setattr(web, "archive", Archive(root=tmp_path, club=club))
    monkeypatch.setattr(web, "authn", a)
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setattr(updates, "latest", lambda *a, **k: {"version": "0.7.0", "notes": NOTES, "url": "u",
                                                              "deploy_notes": updates.deploy_notes(NOTES)})
    c = TestClient(web.app)
    token = a.new_session("ko4cgq")
    c.cookies.set(web.COOKIE, token)
    assert c.get("/admin/updates", follow_redirects=False).headers["location"].startswith("/admin/confirm")
    a.set_admin(token, 60)
    page = c.get("/admin/updates").text
    assert "Version 0.7.0" in page and "copy business.json" in page and "I've done these steps" in page
    assert "Version 0.7.0 is available" in c.get("/links").text                  # the admin banner says so
    assert "needs the steps" in c.post("/admin/updates/run", data={"target": "0.7.0"}).text
    c.post("/admin/updates/run", data={"target": "0.7.0", "notes_done": 1})
    assert (tmp_path / "update-request.json").exists() and "Updating to 0.7.0" in c.get("/admin/updates").text
    c.cookies.set(web.COOKIE, a.new_session("bob"))
    assert c.post("/admin/updates/run", data={"target": "0.7.0", "notes_done": 1}).status_code == 403
