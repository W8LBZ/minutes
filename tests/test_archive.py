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
