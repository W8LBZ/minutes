from pathlib import Path

import pytest

from w8lbz_minutes.club import Club
from w8lbz_minutes.importer import file_date, parse
from w8lbz_minutes.meeting import Meeting
from w8lbz_minutes.store import Archive

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


def test_roster_contact_details_follow_sharing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    c = Club(FIX / "test-club.yaml", roster=[
        {"id": "kd8aaa", "first": "Jane", "last": "Doe", "callsign": "KD8AAA", "email": "jane@example.org",
         "phone": "419-555-0101", "address": "1 Elm St", "birthday": "07-04", "share": ["phone", "birthday"],
         "license_class": "Extra", "role": "Secretary", "officer": True, "member_since": "2024-03-07"},
        {"id": "kd8ccc", "first": "Bob", "last": "Member", "callsign": "KD8CCC", "email": "bob@example.org",
         "phone": "419-555-0199", "address": "9 Oak Ave"},
        {"id": "kd8bbb", "first": "Old", "last": "Timer", "status": "Silent Key", "member_since": "not a date"}])
    monkeypatch.setattr(web, "archive", Archive(tmp_path, c))
    monkeypatch.setattr(web.templates.env, "globals", {**web.templates.env.globals, "club": c})
    viewer = {"id": "kd8ccc"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: viewer["id"])
    client = TestClient(web.app)

    html = client.get("/roster").text  # Bob, a regular member
    assert "KD8AAA" in html and "Secretary" in html and "Mar 7, 2024" in html and "Silent Key" in html
    assert "419-555" not in html and "@example.org" not in html  # contact details live on member pages
    assert html.index("Doe") < html.index("Timer")
    assert client.get("/roster/changes").status_code == 403     # officers only

    jane = client.get("/members/kd8aaa").text
    assert "419-555-0101" in jane and "July 4" in jane              # Jane shared these
    assert "jane@example.org" not in jane and "1 Elm St" not in jane  # but not these
    own = client.get("/members/kd8ccc").text
    assert "bob@example.org" in own and "9 Oak Ave" in own and 'href="/profile"' in own  # Bob sees his own
    assert "Contact" not in client.get("/members/kd8bbb").text      # nothing to show: no section

    viewer["id"] = "kd8aaa"  # Jane, an officer, sees everything, with unshared details marked
    bob = client.get("/members/kd8ccc").text
    assert "bob@example.org" in bob and "9 Oak Ave" in bob and "Only officers can see this" in bob
    assert client.get("/roster/changes").status_code == 200


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A signed-in test client over a throwaway archive of weekly meetings, 30 in 2024 and 3 in 2025."""
    import datetime as dt
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    for i in range(30):
        Meeting(date=dt.date(2024, 1, 4) + dt.timedelta(weeks=i), status="published", in_person=["doe"]).save(tmp_path)
    for d in (dt.date(2025, 1, 2), dt.date(2025, 1, 9), dt.date.today()):
        Meeting(date=d, status="published", in_person=["doe", "kim"]).save(tmp_path)
    monkeypatch.setattr(web, "archive", Archive(tmp_path, club))
    monkeypatch.setattr(web.authn, "member_for", lambda token: "doe")
    return TestClient(web.app)


def rows(html):
    return html.count('<tr><td data-sort=')


def test_archive_groups_by_year_and_pages(client):
    html = client.get("/").text
    assert "All 30 meetings from 2024" in html  # 2024 is cut at a page and links to its own view
    assert rows(html) == 26 + 2 + 1  # 2024 cut to one page, 2025, and this year
    assert html.count("<details class=\"year\"") == 3 and html.count("<details class=\"year\" open") == 1
    p1, p2 = client.get("/?year=2024").text, client.get("/?year=2024&page=2").text
    assert rows(p1) == 26 and rows(p2) == 4 and "Page 2 of 2" in p2
    assert rows(client.get("/?year=2024&page=99").text) == 4  # clamped to the last page
    for junk in ("/?year=", "/?year=abc", "/?year=2024&page=x"):  # "All years" sends year= (empty)
        r = client.get(junk)
        assert r.status_code == 200 and "<details" in r.text


def test_stats_periods(client):
    assert "33 meetings on record" in client.get("/stats?period=all").text
    assert "30 meetings in 2024" in client.get("/stats?period=2024").text
    assert "1 meeting in the last 12 months" in client.get("/stats").text

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


def test_bylaws_page(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setattr(web.authn, "member_for", lambda token: "doe")
    c = TestClient(web.app)
    assert "haven't been added yet" in c.get("/bylaws").text
    (tmp_path / "bylaws.md").write_text("# Constitution\n\n### Article I\n\n**A.** Meetings <b>weekly</b>.")
    html = c.get("/bylaws").text
    assert "<h1>Constitution</h1>" in html and "<strong>A.</strong>" in html


def test_links_page_lists_club_links(monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    monkeypatch.setattr(web.archive.club, "links", [{"label": "Club Discord", "url": "https://discord.example/x"}])
    monkeypatch.setattr(web.authn, "member_for", lambda token: "doe")
    html = TestClient(web.app).get("/links").text
    assert 'href="https://discord.example/x"' in html and "Club Discord" in html and 'href="/links"' in html


def test_link_icons():
    from w8lbz_minutes.web import link_icon
    assert link_icon("https://teams.live.com/meet/1?p=x") == "video"
    assert link_icon("https://discord.com/invite/abc") == "chat"
    assert link_icon("https://minutes.example.ts.net/bylaws") == "document"
    assert link_icon("https://w8lbz.org") == "globe"
    assert link_icon("https://example.org/some/page") == "link"


def test_about_page(monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    monkeypatch.setattr(web.authn, "member_for", lambda token: "doe")
    c = TestClient(web.app)
    html = c.get("/about").text
    assert web.version("w8lbz-minutes") in html and "Jim Flattery, KO4CGQ" in html and "AGPL-3.0-or-later" in html
    assert ">fastapi<" in html.lower() and "What's new" in html
    assert 'href="/about"' in c.get("/links").text  # in the name menu on every page
