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


def test_past_guests_exclude_members_and_sort_recent_first(tmp_path):
    for d, guests in ((dt.date(2026, 10, 1), [{"name": "Pat Guest", "callsign": "KE8ABC"}, {"name": "Rick Roe"}]),
                      (dt.date(2026, 10, 8), [{"name": "Lee Visitor"}])):
        Meeting(date=d, status="published", in_person=["roe"] if d.day == 8 else [], guests=guests).save(tmp_path)
    a = Archive(tmp_path, club)
    m = console.start(a, dt.date(2026, 11, 12), "doe")
    past = console.context(a, m)["past_guests"]
    assert [g["name"] for g in past] == ["Lee Visitor", "Pat Guest"]  # Rick Roe became a member
    assert past[1] == {"name": "Pat Guest", "callsign": "KE8ABC", "visits": 1, "last": "2026-10-01"}


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


class FakeSMTP:
    """Stands in for smtplib.SMTP: records messages instead of sending them."""
    outbox: list = []

    def __init__(self, host, port, timeout=None): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def starttls(self): pass
    def login(self, user, password): pass
    def send_message(self, msg): FakeSMTP.outbox.append(msg)


def mail_archive(tmp_path, monkeypatch, only_to):
    from w8lbz_minutes import auth
    monkeypatch.setattr(auth.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("W8LBZ_SMTP_USER", "club@example.org")
    monkeypatch.setenv("W8LBZ_SMTP_PASSWORD", "abcd efgh")
    FakeSMTP.outbox = []
    c = Club(Path(__file__).parent / "fixtures" / "test-club.yaml", roster=[
        {"id": "doe", "first": "Jane", "last": "Doe", "email": "jane@example.org", "minutes_editor": True},
        {"id": "kim", "first": "Sam", "last": "Kim", "email": "sam@example.org"},
        {"id": "roe", "first": "Rick", "last": "Roe", "email": "rick@example.org", "status": "Silent Key"},
        {"id": "dunn", "first": "Jane", "last": "Dunn"}])
    c.email = {"only_to": only_to} if only_to is not None else {}
    Meeting(date=dt.date(2026, 11, 12), status="published", leader="doe").save(tmp_path)
    return Archive(tmp_path, c)


def test_email_minutes_test_mode_only_reaches_allowlist(tmp_path, monkeypatch):
    a = mail_archive(tmp_path, monkeypatch, only_to=["doe"])
    st = console.email_minutes(a, "2026-11-12", lambda: ("m.pdf", b"%PDF"), "http://x/meetings/2026-11-12")
    assert [m["To"] for m in FakeSMTP.outbox] == ["jane@example.org"]  # Sam is on the roster but withheld
    assert st["sent"] == 1 and st["roster"] == 2 and st["test_mode"]
    msg = FakeSMTP.outbox[0]
    assert msg["Reply-To"] == "jane@example.org" and "November 12, 2026" in msg["Subject"]
    assert [p.get_filename() for p in msg.iter_attachments()] == ["m.pdf"]
    console.email_minutes(a, "2026-11-12", lambda: ("m.pdf", b"%PDF"), "u")  # only once
    assert len(FakeSMTP.outbox) == 1


def test_email_minutes_empty_allowlist_sends_nothing(tmp_path, monkeypatch):
    a = mail_archive(tmp_path, monkeypatch, only_to=[])
    assert console.email_minutes(a, "2026-11-12", lambda: ("m.pdf", b"%PDF"), "u")["sent"] == 0
    assert FakeSMTP.outbox == []


def test_email_minutes_live_skips_inactive_and_addressless(tmp_path, monkeypatch):
    a = mail_archive(tmp_path, monkeypatch, only_to=None)
    console.email_minutes(a, "2026-11-12", lambda: ("m.pdf", b"%PDF"), "u")
    assert sorted(m["To"] for m in FakeSMTP.outbox) == ["jane@example.org", "sam@example.org"]


def test_email_minutes_records_failure_and_retries(tmp_path, monkeypatch):
    a = mail_archive(tmp_path, monkeypatch, only_to=["doe"])
    def broken(): raise OSError("no pango")
    assert "no pango" in console.email_minutes(a, "2026-11-12", broken, "u")["error"]
    assert console.email_status(a, "2026-11-12")["error"]
    assert console.email_minutes(a, "2026-11-12", lambda: ("m.pdf", b"%PDF"), "u")["sent"] == 1
