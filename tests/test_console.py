import datetime as dt
from pathlib import Path

from w8lbz_minutes import console
from w8lbz_minutes.club import Club
from w8lbz_minutes.meeting import Item, Meeting
from w8lbz_minutes.store import Archive

club = Club(Path(__file__).parent / "fixtures" / "test-club.yaml")


def archive_with_prev(tmp_path):
    prev = Meeting(date=dt.date(2026, 11, 5), status="published", in_person=["doe"],
                   sections={"Old Business": [Item("Fix the tower")], "New Business": [Item("Plan field day")],
                             "Upcoming Events": [Item("VE testing")],
                             "Community Reports": [Item("Sam built a dipole", "kim")]})
    prev.save(tmp_path)
    return Archive(tmp_path, club)


def test_start_carries_business_forward(tmp_path):
    a = archive_with_prev(tmp_path)
    m = console.start(a, dt.date(2026, 11, 12), "doe")
    assert m.status == "draft" and m.leader == "doe"
    assert [i.text for i in m.items("Old Business")] == ["Fix the tower", "Plan field day"]
    assert [i.text for i in m.items("Upcoming Events")] == ["VE testing"]
    ctx = console.context(a, m)
    assert ctx["history"]["kim"] == [("2026-11-05", "Sam built a dipole")]


def test_apply_saves_and_drops_never_record_guests(tmp_path):
    a = archive_with_prev(tmp_path)
    console.start(a, dt.date(2026, 11, 12), "doe")
    data = {"meeting": {"in_person": ["doe", "kim"], "remote": ["kim", "roe"],
                        "guests": [{"name": "Pat Guest", "callsign": "KE8ABC"}, {"name": "Tiny Visitor"}],
                        "visitors": 1,
                        "sections": {"Community Reports": [{"text": "Sam got on HF", "member": "kim"}, {"text": " "}]}},
            "state": {"done": ["kim"]}}
    m = console.apply(a, "2026-11-12", data)
    assert m.in_person == ["doe", "kim"] and m.remote == ["roe"]  # can't be both
    assert [g["name"] for g in m.guests] == ["Pat Guest"]
    assert m.visitors == 1
    assert [(i.text, i.member) for i in m.items("Community Reports")] == [("Sam got on HF", "kim")]
    console.submit(a, "2026-11-12")
    try:
        console.apply(a, "2026-11-12", data)
        raise AssertionError("published minutes must not be overwritten")
    except ValueError:
        pass


def test_discard_only_drafts(tmp_path):
    a = archive_with_prev(tmp_path)
    console.start(a, dt.date(2026, 11, 12), "doe")
    console.discard(a, "2026-11-12")
    assert "2026-11-12" not in a.by_slug
    try:
        console.discard(a, "2026-11-05")
        raise AssertionError("published minutes must not be discarded")
    except ValueError:
        pass
