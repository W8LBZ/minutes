"""Chow list: rotation with constraints, swap requests, leader changes, meeting-night records, import."""
import datetime as dt
from pathlib import Path

import pytest

from w8lbz_minutes import chow, console
from w8lbz_minutes.club import Club
from w8lbz_minutes.meeting import Item, Meeting
from w8lbz_minutes.store import Archive

FIX = Path(__file__).parent / "fixtures"
PEOPLE = [
    {"id": "sec", "first": "Sam", "last": "Scribe", "email": "sec@example.org", "role": "Secretary", "officer": True},
    {"id": "amy", "first": "Amy", "last": "Able", "email": "amy@example.org"},
    {"id": "bob", "first": "Bob", "last": "Baker", "email": "bob@example.org"},
    {"id": "cal", "first": "Cal", "last": "Carter", "email": "cal@example.org"},
    {"id": "dee", "first": "Dee", "last": "Dunn", "email": "dee@example.org"},
    {"id": "old", "first": "Old", "last": "Timer", "status": "Silent Key"},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(chow, "DATA", tmp_path)
    sent = []
    monkeypatch.setattr(chow.auth, "send_email", lambda to, subject, body, **kw: sent.append((sorted(to), subject, body)))
    club = Club(FIX / "test-club.yaml", roster=PEOPLE)
    club.info["meeting_day"] = "Thursday"
    s = chow.load()
    s["order"] = ["amy", "bob", "cal", "dee", "old"]
    return club, s, sent


THU = dt.date(2027, 1, 7)  # a first Thursday


def test_generate_follows_the_rotation_and_constraints(env):
    club, s, _ = env
    s["constraints"]["bob"] = {"not_weeks": [2]}               # can't do 2nd Thursdays
    s["constraints"]["cal"] = {"away": [["2027-01-01", "2027-01-31"]]}
    s["nights"]["2027-01-28"] = {"member": None, "status": "none", "note": "Holiday"}
    filled = chow.generate(club, s, dt.date(2027, 2, 25), "sec", today=THU - dt.timedelta(days=3))
    who = {d: s["nights"][d]["member"] for d in filled}
    assert who == {"2027-01-07": "amy",   # Jan 14 is Bob's 2nd Thursday: Cal is next but away, so Dee
                   "2027-01-14": "dee", "2027-01-21": "bob",  # Bob keeps his turn and gets the next night he can do
                   "2027-02-04": "cal", "2027-02-11": "amy",  # Cal is back in February; Jan 28 stays "no chow"
                   "2027-02-18": "bob", "2027-02-25": "cal"}  # next round in order; the Silent Key is never scheduled
    assert s["nights"]["2027-01-28"]["status"] == "none"
    s["next"] = "cal"
    assert chow.next_up(club, s) == "cal"


def test_swap_request_approved_by_the_other_member(env, monkeypatch):
    club, s, sent = env
    monkeypatch.setattr(chow.dt, "date", type("D", (dt.date,), {"today": staticmethod(lambda: THU - dt.timedelta(days=1))}))
    s["nights"] = {"2027-01-07": {"member": "amy", "status": "scheduled"}, "2027-01-14": {"member": "bob", "status": "scheduled"}}
    r = chow.request_swap(club, s, "amy", "2027-01-07", "2027-01-14", "https://x")
    assert sent[-1][0] == ["bob@example.org"] and "swap" in sent[-1][1].lower()  # only Bob is asked
    with pytest.raises(ValueError):
        chow.decide_swap(club, s, r["id"], "amy", True)       # the requester can't approve their own request
    with pytest.raises(ValueError):
        chow.request_swap(club, s, "amy", "2027-01-07", "2027-01-14")  # already waiting
    chow.decide_swap(club, s, r["id"], "bob", True, "https://x")
    assert s["nights"]["2027-01-07"]["member"] == "bob" and s["nights"]["2027-01-14"]["member"] == "amy"
    assert sent[-1][0] == ["amy@example.org", "bob@example.org", "sec@example.org"]  # both, and the Secretary
    with pytest.raises(ValueError):
        chow.decide_swap(club, s, r["id"], "bob", True)       # answered already


def test_swap_request_declined_cancelled_or_stale(env, monkeypatch):
    club, s, sent = env
    monkeypatch.setattr(chow.dt, "date", type("D", (dt.date,), {"today": staticmethod(lambda: THU - dt.timedelta(days=1))}))
    s["nights"] = {d: {"member": m, "status": "scheduled"} for d, m in
                   (("2027-01-07", "amy"), ("2027-01-14", "bob"), ("2027-01-21", "cal"))}
    with pytest.raises(ValueError):
        chow.request_swap(club, s, "amy", "2027-01-14", "2027-01-21")  # not Amy's night to give
    r = chow.request_swap(club, s, "amy", "2027-01-07", "2027-01-14")
    chow.decide_swap(club, s, r["id"], "bob", False)
    assert r["status"] == "declined" and sent[-1][0] == ["amy@example.org"] and s["nights"]["2027-01-07"]["member"] == "amy"
    r = chow.request_swap(club, s, "amy", "2027-01-07", "2027-01-21")
    chow.decide_swap(club, s, r["id"], "amy", False)
    assert r["status"] == "cancelled"
    r = chow.request_swap(club, s, "amy", "2027-01-07", "2027-01-21")
    chow.assign(club, s, "2027-01-21", "dee", "sec")             # a leader changed it meanwhile
    with pytest.raises(ValueError):
        chow.decide_swap(club, s, r["id"], "cal", True)
    assert r["status"] == "stale"


def test_meeting_night_record_and_minutes(env, tmp_path, monkeypatch):
    club, s, _ = env
    today = dt.date.today()
    d = [(today + dt.timedelta(days=7 * i)).isoformat() for i in range(4)]
    s["nights"] = {d[0]: {"member": "amy", "status": "scheduled"}, d[1]: {"member": "bob", "status": "scheduled"},
                   d[2]: {"member": "cal", "status": "scheduled"}, d[3]: {"member": "dee", "status": "scheduled"}}
    chow.record(club, s, d[0], "provided", "sec", note="brownies")
    assert chow.tonight_line(club, d[0], s["nights"][d[0]]) == "Chow tonight provided by Amy Able (brownies)."
    chow.record(club, s, d[0], "missed", "sec", note="ignored")
    assert chow.tonight_line(club, d[0], s["nights"][d[0]]) == "Chow tonight: Amy Able did not provide chow."
    chow.record(club, s, d[0], "covered", "sec", covered_by="dee", note="pizza delivered")
    assert s["nights"][d[0]] == {"member": "amy", "status": "covered", "covered_by": "dee", "note": "pizza delivered"}
    chow.swap(club, s, d[1], d[2], "sec")
    chow.save(s)
    # Changes are logged with today's date, and the meeting is today: only the latest record counts.
    lines = chow.minutes_section(club, s, chow.history(), d[0])
    assert lines[0] == "Chow tonight provided by Dee Dunn for Amy Able (pizza delivered)."
    assert lines[1].startswith("Chow swap: Bob Baker now has")
    assert lines[2:] == [chow.describe(club, x, s["nights"][x]) for x in d[1:]]

    meetings = tmp_path / "meetings"
    meetings.mkdir()
    Meeting(date=today, status="draft", sections={"Upcoming Chow": [Item("stale line from the start")]}).save(meetings)
    a = Archive(meetings, club)
    console.submit(a, d[0])
    assert [i.text for i in a.by_slug[d[0]].items("Upcoming Chow")] == lines


def test_describe_and_missed(env):
    club, s, _ = env
    chow.set_none(s, "2026-11-26", "Thanksgiving", "sec")
    assert chow.describe(club, "2026-11-26", s["nights"]["2026-11-26"]) == "Nov 26: no chow (Thanksgiving)"
    s["nights"]["2026-12-03"] = {"member": "amy", "status": "scheduled"}
    chow.record(club, s, "2026-12-03", "missed", "sec")
    assert s["nights"]["2026-12-03"]["status"] == "missed"
    with pytest.raises(ValueError):
        chow.record(club, s, "2026-12-03", "bogus", "sec")


def test_import_matches_misspelled_names_and_fixes_dates(env, tmp_path):
    import openpyxl
    club, _, _ = env
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["", "26 Chow List"])
    ws.append(["Able, Amy", dt.datetime(2026, 11, 5)])
    ws.append(["Bob Bakker", dt.datetime(2026, 11, 12)])     # misspelled
    ws.append(["", dt.datetime(2026, 11, 25)])               # a Wednesday, and blank: no chow
    ws.append(["Carter", None, "3-Dec"])                     # date typed as text, in column C
    ws.append(["Nobody, Atall", dt.datetime(2026, 12, 10)])
    p = tmp_path / "chow.xlsx"
    wb.save(p)
    s, problems = chow.import_xlsx(club, p, ["Able", "Baker", "Carter", "Dunn"], "sec", 2026)
    assert {d: x["member"] for d, x in s["nights"].items()} == {
        "2026-11-05": "amy", "2026-11-12": "bob", "2026-11-26": None, "2026-12-03": "cal"}
    assert s["nights"]["2026-11-26"] == {"member": None, "status": "none", "note": "Thanksgiving"}
    assert s["order"] == ["amy", "bob", "cal", "dee"] and s["pending"] == ["sec"]
    assert any("Nov 25" in p for p in problems) and any("Nobody" in p for p in problems)


def test_chow_page_permissions(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    club, s, _ = env
    s["nights"] = {"2099-01-01": {"member": "amy", "status": "scheduled"}, "2099-01-08": {"member": "bob", "status": "scheduled"}}
    chow.save(s)
    monkeypatch.setattr(web, "archive", Archive(tmp_path, club))
    who = {"id": "amy"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: who["id"])
    c = TestClient(web.app)
    page = c.get("/chow").text
    assert "Amy Able" in page and "Ask to swap" in page and "Fill the schedule" not in page  # a member
    assert c.post("/chow/assign", data={"date": "2099-01-01", "member": "bob"}).status_code == 403
    assert c.post("/chow/swap", data={"a": "2099-01-01", "b": "2099-01-08"}).status_code == 403
    c.post("/chow/request", data={"mine": "2099-01-01", "theirs": "2099-01-08"})
    who["id"] = "bob"
    assert "asks to swap" in c.get("/chow").text
    rid = chow.load()["swaps"][0]["id"]
    c.post(f"/chow/requests/{rid}/answer", data={"approve": 1})
    assert chow.load()["nights"]["2099-01-01"]["member"] == "bob"
    assert c.get("/chow/rotation").status_code == 404                    # a member has only the schedule
    who["id"] = "sec"  # an officer can lead, so can edit
    assert "Swap two nights" in c.get("/chow").text and "Fill the schedule" in c.get("/chow/rotation").text
    assert "Past nights" in c.get("/chow/history").text
    assert c.post("/chow/assign", data={"date": "2099-01-08", "member": "cal"}, follow_redirects=False).status_code == 303
    assert chow.load()["nights"]["2099-01-08"]["member"] == "cal"
