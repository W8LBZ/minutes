from pathlib import Path

import pytest

from w8lbz_minutes.club import Club
from w8lbz_minutes.importer import file_date, parse
from w8lbz_minutes.meeting import Meeting

FIX = Path(__file__).parent / "fixtures"
club = Club(FIX / "test-club.yaml")


@pytest.fixture(scope="module")
def m():
    return parse((FIX / "old-format.txt").read_text(), club)


def test_parse(m):
    assert str(m.date) == "2026-11-05"
    assert sorted(m.in_person) == ["doe", "kim"]
    assert m.remote == ["roe"]  # "Rowe" alias resolved
    assert m.guests == [{"name": "Pat Guest", "callsign": "KE8ABC", "notes": "2nd meeting"}]
    assert m.items("Financial Report") == []  # empty template dropped
    assert m.items("Upcoming Chow") == []  # "See attached list" dropped
    reports = m.items("Community Reports")
    assert [r.member for r in reports] == ["roe", "doe", "kim"]  # "Jane": only Doe was present
    assert reports[1].text == "Jane worked on a long report that wraps onto a second line."


def test_never_record_names_are_dropped(m):
    assert "Tiny" not in m.to_markdown()


def test_markdown_round_trip(m):
    assert Meeting.from_markdown(m.to_markdown()) == m


def test_ambiguous_first_name():
    assert club.speaker_of("Jane nothing.", ["doe", "dunn"]) is None
    assert club.speaker_of("Jane D was busy") == "doe"


def test_file_date():
    assert str(file_date("29-jan-26-minutes-R1JCmreIiha6nmwZ.pdf")) == "2026-01-29"
    assert str(file_date("10-sept-26-minutes.pdf")) == "2026-09-10"


def test_permissions_and_possessives():
    assert club.can_lead("doe") and not club.can_lead("kim")
    assert club.speaker_of("Sams antenna fell down") == "kim"


def test_former_callsign_maps_to_member(tmp_path, m):
    from w8lbz_minutes.store import Archive
    m.in_person = ["doe", "kd8old"]  # stored before Sam's callsign change
    m.save(tmp_path)
    a = Archive(tmp_path, club)
    assert a.meetings[0].in_person == ["doe", "kim"]
    assert club.members["kim"].aliases == []  # not treated as a name spelling


def test_membership_log():
    from w8lbz_minutes.roster import attach_log, to_members
    ms = to_members([{"full_name": "Sam Kim", "callsign": "KD8NEW", "is_officer": "True"},
                     {"full_name": "Old Timer", "status": "Silent Key"}])
    attach_log(ms, [{"callsign": "KD8NEW", "date": "46043", "event": "Joined"},
                    {"callsign": "", "full_name": "Old Timer", "date": "", "event": "Silent Key"}])
    assert ms[0]["officer"] and ms[0]["member_since"] == "2026-01-21"
    assert ms[1]["id"] == "old-timer" and ms[1]["events"][0]["event"] == "Silent Key"


def test_guests_page_moves_new_members_to_their_own_section(tmp_path, monkeypatch):
    import datetime as dt
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.store import Archive
    for d in (dt.date(2026, 10, 1), dt.date(2026, 10, 8)):
        Meeting(date=d, status="published", guests=[{"name": "Rick Roe"}, {"name": "Pat Guest"}]).save(tmp_path)
    Meeting(date=dt.date(2026, 10, 15), status="published", in_person=["roe"]).save(tmp_path)
    monkeypatch.setattr(web, "archive", Archive(tmp_path, club))
    monkeypatch.setattr(web.authn, "member_for", lambda token: "doe")
    html = TestClient(web.app).get("/guests").text
    current, joined = html.split("<h2>Became members")
    assert "Pat Guest" in current and "Rick Roe" not in current
    assert "Rick Roe" in joined and "Oct 15, 2026" in joined and "after 2.0 visits" in joined
