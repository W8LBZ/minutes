"""Adding a member: a new roster row and Membership Log row (values only), the app updated, guests offered."""
import datetime as dt
import json
from pathlib import Path

import pytest

from w8lbz_minutes import chow, membership, profile, roster
from w8lbz_minutes.club import Club
from w8lbz_minutes.roster import Sheet

FIX = Path(__file__).parent / "fixtures"
PEOPLE = [{"id": "kd8aaa", "first": "Jane", "last": "Doe", "callsign": "KD8AAA", "email": "jane@example.org",
           "role": "Secretary", "officer": True, "status": "Active"},
          {"id": "kd8bbb", "first": "Tom", "last": "Till", "callsign": "KD8BBB", "email": "tom@example.org",
           "role": "Treasurer", "officer": True, "status": "Active"},
          {"id": "kd8ccc", "first": "Bob", "last": "Member", "callsign": "KD8CCC", "status": "Active"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    cache = tmp_path / "roster.json"
    cache.write_text(json.dumps(PEOPLE))
    for mod, attr in ((roster, "CACHE"), (membership, "ROSTER_CACHE")):
        monkeypatch.setattr(mod, attr, cache)
    monkeypatch.setattr(roster, "PREVIEW", "test")
    monkeypatch.setattr(roster, "DATA", tmp_path)
    monkeypatch.setattr(chow, "DATA", tmp_path)
    monkeypatch.setattr(profile, "DATA", tmp_path)
    monkeypatch.setattr(roster, "_sheet", lambda: (_ for _ in ()).throw(AssertionError("real sheet used")))
    sent = []
    monkeypatch.setattr(membership.auth, "send_email", lambda to, subject, body, **kw: sent.append((to, subject)))
    club = Club(FIX / "test-club.yaml", roster=json.loads(cache.read_text()))
    return club, tmp_path, sent


def test_add_member_writes_rows_and_updates_the_app(env):
    club, tmp, sent = env
    sheet = Sheet()
    sheet.read()  # builds the preview grid
    tabs = json.loads((tmp / "preview-sheet.json").read_text())
    tabs["Member Roster"].append(["", "", "", "", "", "", "", "Active"])  # an empty row with only a dropdown value
    (tmp / "preview-sheet.json").write_text(json.dumps(tabs))
    mid = membership.add_member(club, {"first": "Ann", "last": "New", "callsign": "kd8new", "email": "ann@example.org",
                                       "license_class": "General", "joined": "2026-11-05"}, by="kd8bbb", sheet=sheet)
    assert mid == "kd8new" and club.members["kd8new"].name == "Ann New" and club.members["kd8new"].status == "Active"
    tabs = json.loads((tmp / "preview-sheet.json").read_text())
    roster_rows, log_rows = tabs["Member Roster"], tabs["Membership Log"]
    assert roster_rows[len(PEOPLE) + 1][:3] == ["KD8NEW", "Ann New", "ann@example.org"]  # into the dropdown-only row
    assert len(roster_rows) == 1 + len(PEOPLE) + 1
    assert log_rows[1] == ["KD8NEW", "Ann New", "2026-11-05", "Joined", "Added in the app by Tom Till"]
    assert json.loads((tmp / "roster.json").read_text())[-1]["member_since"] == "2026-11-05"
    assert chow.load()["order"] == ["kd8new"]                    # at the bottom of the chow rotation
    assert sent == [(["jane@example.org"], "New member: Ann New")]  # the Secretary is told
    with pytest.raises(ValueError):
        membership.add_member(club, {"first": "Ann", "last": "Again", "callsign": "KD8NEW", "license_class": "General"},
                              by="kd8bbb", sheet=sheet)
    e = profile.history()[0]
    assert e["added"] and e["member"] == "kd8new" and e["by"] == "kd8bbb" and e["new"]["callsign"] == "KD8NEW"
    with pytest.raises(ValueError):
        profile.undo(club, e["id"], by="kd8aaa")  # an addition isn't undone from Recent changes
    for bad in ({"first": "Ann"}, {"first": "A", "last": "B", "callsign": "not a call"},
                {"first": "A", "last": "B", "callsign": "KD8XYZ"},  # no license class: members must be licensed
                {"first": "A", "last": "B", "license_class": "General"},  # no callsign
                {"first": "A", "last": "B", "callsign": "KD8XYZ", "license_class": "General", "email": "nope"},
                {"first": "A", "last": "B", "callsign": "KD8XYZ", "license_class": "General", "joined": "soon"}):
        with pytest.raises(ValueError):
            membership.clean(bad)


def test_ready_guests_and_names():
    guests = [{"name": "Pat Visitor", "visits": [1, 2, 3, 4], "member": None},
              {"name": "Once Only", "visits": [1], "member": None},
              {"name": "Bob Member", "visits": [1, 2, 3, 4, 5], "member": "kd8ccc"}]
    assert [g["name"] for g in membership.ready_guests(guests, 4)] == ["Pat Visitor"]
    assert membership.split_name("Mary Ann Smith") == ("Mary Ann", "Smith")


def test_only_roster_keepers_can_add(env, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.store import Archive
    club, tmp, _ = env
    monkeypatch.setattr(web, "archive", Archive(tmp, club))
    who = {"id": "kd8ccc"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: who["id"])
    c = TestClient(web.app)
    assert c.get("/roster/add").status_code == 403 and "Add a member" not in c.get("/roster").text
    who["id"] = "kd8bbb"  # the Treasurer
    assert "Add a member" in c.get("/roster").text and c.get("/roster/add").status_code == 200
    r = c.post("/roster/add", data={"first": "Ann", "last": "New", "callsign": "KD8NEW", "license_class": "Technician"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/members/kd8new?added=1"
    assert "Added to the roster" in c.get(r.headers["location"]).text
    assert "Added to the roster" in c.get("/roster/changes").text and "Tom Till" in c.get("/roster/changes").text
    assert "already on the roster" in c.post("/roster/add", data={"first": "X", "last": "Y", "callsign": "KD8NEW", "license_class": "General"}).text
