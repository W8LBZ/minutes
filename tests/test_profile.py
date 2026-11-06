"""Profile edits: values-only writes to the roster sheet, change log, undo, Secretary notice, sharing."""
import json
from pathlib import Path

import pytest

from w8lbz_minutes import profile, roster
from w8lbz_minutes.club import Club
from w8lbz_minutes.roster import Sheet, SheetError, _col, _month_day

FIX = Path(__file__).parent / "fixtures"
HEADER = ["callsign", "full_name", "email", "Phone", "Address", "Title(s)", "Status", "birthday", "share"]


class FakeResponse:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = data or {}, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSheets:
    """Stands in for the Google Sheets API: a grid of values, and a record of every write."""

    def __init__(self, rows, writable=True):
        self.rows, self.writable, self.writes = [list(r) for r in rows], writable, []

    def get(self, url, params=None):
        return FakeResponse({"values": self.rows})

    def post(self, url, json=None):
        if not self.writable:
            return FakeResponse(status=403)
        assert url.endswith(":batchUpdate") and json["valueInputOption"] == "RAW"
        for d in json["data"]:
            a1 = d["range"].split("!")[1]
            col = ord(a1[0]) - 65
            row = int(a1[1:]) - 1
            self.rows[row] += [""] * (col + 1 - len(self.rows[row]))
            self.rows[row][col] = d["values"][0][0]
            self.writes.append((a1, d["values"][0][0]))
        return FakeResponse()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "DATA", tmp_path)
    monkeypatch.setattr(profile, "ROSTER_CACHE", tmp_path / "roster.json")
    monkeypatch.setattr(roster, "_sheet", lambda: ("sheet-id", "Member Roster"))
    sent = []
    monkeypatch.setattr(profile.auth, "send_email", lambda to, subject, body, **kw: sent.append((to, subject, body, kw)))
    people = [{"id": "kd8aaa", "first": "Jane", "last": "Doe", "callsign": "KD8AAA", "email": "jane@example.org",
               "role": "Secretary", "officer": True},
              {"id": "kd8ccc", "first": "Bob", "last": "Member", "callsign": "KD8CCC", "email": "bob@example.org",
               "phone": "419-555-0199"}]
    (tmp_path / "roster.json").write_text(json.dumps(people))
    club = Club(FIX / "test-club.yaml", roster=people)
    fake = FakeSheets([HEADER,
                       ["KD8AAA", "Jane Doe", "jane@example.org", "", "", "Secretary", "Active", "", ""],
                       ["KD8CCC", "Bob Member", "bob@example.org", "419-555-0199", "", "", "Active", "", ""]])
    return club, Sheet(fake), fake, sent


def test_change_writes_only_changed_cells_and_tells_the_secretary(env):
    club, sheet, fake, sent = env
    e = profile.change(club, "kd8ccc", {"phone": "419-555-0199", "address": "9 Oak Ave", "birthday": "07-04",
                                        "share": "phone, birthday"}, by="kd8ccc", sheet=sheet, url="https://x")
    assert sorted(fake.writes) == [("E3", "9 Oak Ave"), ("H3", "07-04"), ("I3", "phone, birthday")]  # phone unchanged
    assert e["old"] == {"address": "", "birthday": "", "share": ""}
    m = club.members["kd8ccc"]
    assert (m.address, m.birthday, m.share) == ("9 Oak Ave", "07-04", ["phone", "birthday"])
    cached = {r["id"]: r for r in json.loads((profile.ROSTER_CACHE).read_text())}
    assert cached["kd8ccc"]["address"] == "9 Oak Ave"
    (to, subject, body, kw), = sent
    assert to == ["jane@example.org"] and "Bob Member" in subject and "9 Oak Ave" in body and "https://x/roster/changes" in body
    assert "only_to" in kw  # email test mode applies
    assert profile.change(club, "kd8ccc", {"address": "9 Oak Ave"}, by="kd8ccc", sheet=sheet) is None  # no-op


def test_only_profile_fields_can_be_changed(env):
    club, sheet, fake, _ = env
    profile.change(club, "kd8ccc", {"status": "Inactive", "full_name": "Hacker", "phone": "1"}, by="kd8ccc", sheet=sheet)
    assert fake.writes == [("D3", "1")]


def test_undo_restores_and_refuses_if_changed_again(env):
    club, sheet, fake, sent = env
    e = profile.change(club, "kd8ccc", {"address": "9 Oak Ave"}, by="kd8ccc", sheet=sheet)
    profile.undo(club, e["id"], by="kd8aaa", sheet=sheet)
    assert fake.rows[2][4] == "" and club.members["kd8ccc"].address is None
    assert [x["undone"] for x in profile.history()] == [False, True]
    with pytest.raises(ValueError):
        profile.undo(club, e["id"], by="kd8aaa", sheet=sheet)  # only once
    e2 = profile.change(club, "kd8ccc", {"address": "1 New Rd"}, by="kd8ccc", sheet=sheet)
    profile.change(club, "kd8ccc", {"address": "2 Newer Rd"}, by="kd8ccc", sheet=sheet)
    with pytest.raises(ValueError):
        profile.undo(club, e2["id"], by="kd8aaa", sheet=sheet)  # would overwrite a newer change


def test_sheet_problems_change_nothing(env):
    club, _, fake, sent = env
    with pytest.raises(SheetError, match="Editor"):
        profile.change(club, "kd8ccc", {"address": "9 Oak Ave"}, by="kd8ccc", sheet=Sheet(FakeSheets(fake.rows, writable=False)))
    old = FakeSheets([HEADER[:7]] + [r[:7] for r in fake.rows[1:]])
    with pytest.raises(SheetError, match="birthday"):
        profile.change(club, "kd8ccc", {"birthday": "07-04"}, by="kd8ccc", sheet=Sheet(old))
    assert club.members["kd8ccc"].address is None and profile.history() == [] and sent == []


def test_helpers():
    assert [_col(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]
    assert _month_day("07-04") == "07-04" and _month_day("1961-07-04") == "07-04" and _month_day("") is None
    assert _month_day("25001") == "06-12"  # a Sheets date serial: the year is dropped


def test_can_see():
    club = Club(FIX / "test-club.yaml", roster=[
        {"id": "o", "first": "O", "last": "Officer", "officer": True},
        {"id": "a", "first": "A", "last": "Member", "share": ["phone"]},
        {"id": "b", "first": "B", "last": "Member"}])
    assert club.can_see("b", "a", "phone") and not club.can_see("b", "a", "address")
    assert club.can_see("o", "a", "address") and club.can_see("a", "a", "address")
    assert not club.can_see(None, "a", "phone")


def test_email_change_needs_confirmation(tmp_path, monkeypatch):
    from w8lbz_minutes import auth as auth_mod
    sent = []
    monkeypatch.setattr(auth_mod, "send_email", lambda to, subject, body, **kw: sent.append((to, body)))
    club = Club(FIX / "test-club.yaml", roster=[
        {"id": "kd8ccc", "first": "Bob", "last": "Member", "email": "bob@example.org"},
        {"id": "kd8aaa", "first": "Jane", "last": "Doe", "email": "jane@example.org"}])
    a = auth_mod.Auth(club, tmp_path / "auth.sqlite")
    assert a.start_email_change("kd8ccc", "jane@example.org") == "Another member already uses that address."
    assert a.start_email_change("kd8ccc", "not-an-email")
    assert a.start_email_change("kd8ccc", "bob@new.example", base_url="https://x") is None
    (to, body), = sent
    token = body.split("/profile/email?t=")[1].split()[0]
    assert to == "bob@new.example"
    assert a.confirm_email_change(token) == ("kd8ccc", "bob@new.example")
    assert a.confirm_email_change(token) is None  # one use


def test_monthday_filter():
    from w8lbz_minutes.web import monthday
    assert monthday("07-04") == "July 4" and monthday("") == "" and monthday(None) == ""
    assert monthday("1961-07-04") == "1961-07-04" and monthday("13-40") == "13-40"


def test_club_reloads_roster_after_a_sync(tmp_path, monkeypatch):
    import os
    from w8lbz_minutes import club as club_mod
    cache = tmp_path / "roster.json"
    cache.write_text(json.dumps([{"id": "kd8ccc", "first": "Bob", "last": "Member"}]))
    monkeypatch.setattr(club_mod, "ROSTER_CACHE", cache)
    cfg = tmp_path / "club.yaml"
    cfg.write_text("club: {name: T}\n")
    c = club_mod.Club(cfg)
    assert c.members["kd8ccc"].address is None and not c.refresh()
    cache.write_text(json.dumps([{"id": "kd8ccc", "first": "Bob", "last": "Member", "address": "9 Oak Ave"}]))
    os.utime(cache, (1, 2))  # a different mtime, as a sync would give
    assert c.refresh() and c.members["kd8ccc"].address == "9 Oak Ave"


def test_multiline_addresses_keep_their_line_breaks(env, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.store import Archive
    club, sheet, fake, sent = env
    assert web.clean_address(" 100 Main St  #12 \r\n\r\nAnytown, OH 44000 ") == "100 Main St #12\nAnytown, OH 44000"
    fake.rows[2][4] = "100 Main St #12 \nAnytown, OH 44000"  # as typed in the sheet, trailing space included
    club.members["kd8ccc"].address = fake.rows[2][4]
    monkeypatch.setattr(web, "archive", Archive(root=profile.DATA, club=club))  # an empty archive in tmp_path
    monkeypatch.setattr(web.authn, "member_for", lambda token: "kd8ccc")
    monkeypatch.setattr(web.profile, "Sheet", lambda: sheet)
    c = TestClient(web.app)
    page = c.get("/profile").text
    assert "<textarea" in page and "#12 \nAnytown" in page  # shown on two lines
    form = {"email": "bob@example.org", "phone": "419-555-0123", "address": "100 Main St #12\r\nAnytown, OH 44000",
            "bmonth": "", "bday": ""}
    assert c.post("/profile", data=form, follow_redirects=False).status_code == 303
    assert fake.writes == [("D3", "419-555-0123")]  # the untouched address isn't rewritten
    form["address"] = "100 Main St #13\r\nAnytown, OH 44000"
    c.post("/profile", data=form, follow_redirects=False)
    assert fake.rows[2][4] == "100 Main St #13\nAnytown, OH 44000"
    assert "#13 / Anytown" in sent[-1][2]  # readable in the Secretary's email


def test_preview_mode_never_sends_or_touches_the_real_sheet(tmp_path, monkeypatch):
    from w8lbz_minutes import auth as auth_mod
    monkeypatch.setattr(auth_mod, "PREVIEW", "some-branch")
    monkeypatch.setattr(auth_mod, "DATA", tmp_path)
    monkeypatch.setattr(auth_mod.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP used")))
    monkeypatch.setenv("W8LBZ_SMTP_USER", "u")
    monkeypatch.setenv("W8LBZ_SMTP_PASSWORD", "p")
    assert auth_mod.send_email(["a@x.org", "b@x.org"], "Hi", "body", only_to={"a@x.org"}) == 1
    e = json.loads((tmp_path / "preview-outbox.jsonl").read_text())
    assert e["to"] == ["a@x.org"] and e["withheld"] == ["b@x.org"] and e["subject"] == "Hi"

    monkeypatch.setattr(roster, "PREVIEW", "some-branch")
    monkeypatch.setattr(roster, "DATA", tmp_path)
    monkeypatch.setattr(roster, "CACHE", tmp_path / "roster.json")
    monkeypatch.setattr(roster, "_sheet", lambda: (_ for _ in ()).throw(AssertionError("real sheet used")))
    (tmp_path / "roster.json").write_text(json.dumps([{"id": "kd8ccc", "first": "Bob", "last": "Member", "callsign": "KD8CCC"}]))
    sheet = Sheet()
    assert sheet.update_member("KD8CCC", "Bob Member", {"phone": "419-555-0111"}) == {"phone": ""}
    assert "419-555-0111" in (tmp_path / "preview-sheet.json").read_text()
