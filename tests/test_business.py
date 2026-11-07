"""Tracked business items: carried until done, owners and due dates, the minutes' Old and New Business."""
import datetime as dt
from pathlib import Path

import pytest

from w8lbz_minutes import business, chow, console
from w8lbz_minutes.club import Club
from w8lbz_minutes.meeting import Item, Meeting
from w8lbz_minutes.store import Archive

FIX = Path(__file__).parent / "fixtures"
PEOPLE = [{"id": "sec", "first": "Sam", "last": "Scribe", "role": "Secretary", "officer": True},
          {"id": "amy", "first": "Amy", "last": "Able"},
          {"id": "bob", "first": "Bob", "last": "Baker"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(business, "DATA", tmp_path)
    monkeypatch.setattr(chow, "DATA", tmp_path)
    club = Club(FIX / "test-club.yaml", roster=PEOPLE)
    meetings = tmp_path / "meetings"
    meetings.mkdir()
    Meeting(date=dt.date(2026, 10, 22), status="published", sections={"New Business": [Item("Club  patches for hats")]}).save(meetings)
    Meeting(date=dt.date(2026, 10, 29), status="published", sections={
        "Old Business": [Item("Club patches for hats")], "New Business": [Item("Field Day at Osborn Park?")]}).save(meetings)
    return club, Archive(meetings, club)


def test_items_carry_until_done(env):
    club, a = env
    m = console.start(a, dt.date(2026, 11, 5), "sec")
    assert [i.text for i in m.items("Old Business")] == ["Club patches for hats", "Field Day at Osborn Park?"]  # seeded
    s = business.load()
    patches, park = s["items"]
    assert (patches["opened"], park["opened"]) == ("2026-10-22", "2026-10-29")  # when each first came up
    business.edit(s, patches["id"], "sec", owner="amy", due="2026-11-01")
    business.close(s, park["id"], "sec", "2026-11-05")
    new = business.add(s, "Order a new feedline", "sec", opened="2026-11-05")
    business.save(s)
    assert business.view(club, business.get(s, patches["id"]), "2026-11-05")["overdue"]
    console.submit(a, "2026-11-05")
    m = a.by_slug["2026-11-05"]
    assert [i.text for i in m.items("Old Business")] == ["Club patches for hats (Amy, due Nov 1)",
                                                        "Field Day at Osborn Park? Done."]
    assert [i.text for i in m.items("New Business")] == ["Order a new feedline"]

    m = console.start(a, dt.date(2026, 11, 12), "sec")  # done items drop off; tonight's new item is now old
    assert [i.text for i in m.items("Old Business")] == ["Club patches for hats (Amy, due Nov 1)", "Order a new feedline"]
    s = business.load()
    business.close(s, new["id"], "amy", "2026-11-09")  # marked done between meetings: shows as done at the next one
    business.save(s)
    old, _ = business.for_meeting(s, "2026-11-12", since="2026-11-05")
    assert [business.line(club, x, "2026-11-12") for x in old][-1] == "Order a new feedline Done."


def test_agenda_hold_and_deleted_meetings(env):
    club, a = env
    s = business.load()
    business.seed(s, a.meetings)
    sotc = business.add(s, "State of the Club (President)", "sec", agenda="2027-01-07", opened="2026-11-01")
    assert sotc not in business.for_meeting(s, "2026-11-05")[0] and sotc in business.for_meeting(s, "2027-01-07")[0]
    # A practice meeting is deleted: what it added goes, what it closed reopens.
    oops = business.add(s, "practice item", "sec", opened="2026-11-20")
    business.close(s, s["items"][0]["id"], "sec", "2026-11-20")
    assert business.forget_meeting(s, "2026-11-20") == 1 and oops not in s["items"]
    assert s["items"][0]["status"] == "open"
    with pytest.raises(ValueError):
        business.remove(s, sotc["id"], "2026-11-05")  # only items added at that meeting can be deleted
    with pytest.raises(ValueError):
        business.add(s, "   ", "sec")
    with pytest.raises(ValueError):
        business.edit(s, sotc["id"], "sec", due="soon")


def test_business_page_permissions(env, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    club, a = env
    monkeypatch.setattr(web, "archive", a)
    who = {"id": "amy"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: who["id"])
    c = TestClient(web.app)
    assert "Club patches for hats" in c.get("/business").text and "Add an item" not in c.get("/business").text
    assert c.post("/business/add", data={"text": "x"}).status_code == 403
    iid = business.load()["items"][0]["id"]
    assert "Only a leader or the item" in c.post(f"/business/{iid}/edit", data={"due": "2026-12-01"}).text
    who["id"] = "sec"
    c.post(f"/business/{iid}/edit", data={"owner": "amy"})
    who["id"] = "amy"  # now Amy owns it: she can set the due date and mark it done, but not hand it off
    c.post(f"/business/{iid}/edit", data={"due": "2026-12-01", "owner": "bob"})
    x = business.get(business.load(), iid)
    assert x["due"] == "2026-12-01" and x["owner"] == "amy"
    c.post(f"/business/{iid}/done", data={"done": 1})
    assert business.get(business.load(), iid)["status"] == "done"
    who["id"] = "sec"
    r = c.post("/business/add", data={"text": "Order a new feedline", "meeting": "2026-11-05"},
               headers={"Accept": "application/json"})
    assert [x["text"] for x in r.json()["new"]] == ["Order a new feedline"]
