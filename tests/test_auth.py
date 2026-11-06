from pathlib import Path

import pytest

from w8lbz_minutes import auth as auth_mod
from w8lbz_minutes.auth import Auth, _safe_next
from w8lbz_minutes.club import Club

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def a(tmp_path, monkeypatch):
    club = Club(FIX / "test-club.yaml",
                roster=[{"id": "kd8aaa", "first": "Jane", "last": "Doe", "email": "Jane@Example.org", "officer": True},
                        {"id": "kd8bbb", "first": "Old", "last": "Timer", "email": "old@example.org", "status": "Silent Key"}])
    club.auth = {"rp_id": "localhost"}
    sent = []
    monkeypatch.setattr(auth_mod, "send_email", lambda to, subject, body, **kw: sent.append((to, body)))
    obj = Auth(club, tmp_path / "auth.sqlite")
    obj.sent = sent
    return obj


def link_token(body: str) -> str:
    return body.split("/login/link?t=")[1].split()[0]


def test_email_link_flow(a):
    a.send_link("  jane@example.ORG ", "/console", base_url="http://192.168.23.100:8000")
    (to, body), = a.sent
    assert to == "Jane@Example.org" and "http://192.168.23.100:8000/login/link?t=" in body
    t = link_token(body)
    assert a.use_link(t) == ("kd8aaa", "/console")
    assert a.use_link(t) is None  # one use only


def test_unknown_and_inactive_addresses_get_nothing(a):
    a.send_link("stranger@example.org")
    a.send_link("old@example.org")  # silent key
    assert a.sent == []


def test_rate_limit(a):
    for _ in range(8):
        a.send_link("jane@example.org")
    assert len(a.sent) == auth_mod.EMAILS_PER_HOUR


def test_sessions(a):
    tok = a.new_session("kd8aaa", "pytest")
    assert a.member_for(tok) == "kd8aaa"
    assert a.member_for("bogus") is None and a.member_for(None) is None
    a.end_session(tok)
    assert a.member_for(tok) is None
    # only hashes are stored
    assert tok not in str(a.db.execute("select * from sessions").fetchall())


def test_safe_next():
    assert _safe_next("/console") == "/console"
    assert _safe_next("https://evil.example") == "/" and _safe_next("//evil.example") == "/"


def test_passkey_options(a):
    cid, options = a.registration_options("kd8aaa")
    assert '"residentKey": "required"' in options and '"id": "localhost"' in options
    with pytest.raises(ValueError):
        a.register("kd8aaa", "wrong-challenge", {})


def test_admin_link(a):
    url = a.create_link("kd8aaa", base_url="https://minutes.example")
    assert url.startswith("https://minutes.example/login/link?t=")
    assert a.use_link(url.split("t=")[1]) == ("kd8aaa", "/")


def test_email_test_mode_withholds_other_recipients(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, user, password): calls.append(("login", password))
        def send_message(self, msg): calls.append(("send", msg["To"]))

    monkeypatch.setattr(auth_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("W8LBZ_SMTP_USER", "club@example.org")
    monkeypatch.setenv("W8LBZ_SMTP_PASSWORD", "abcd efgh ijkl mnop")
    allow = {"me@example.org"}
    assert auth_mod.send_email("someone@example.org", "s", "b", only_to=allow) == 0
    assert calls == []
    assert auth_mod.send_email("Me@Example.org", "s", "b", only_to=allow) == 1
    assert calls == [("login", "abcdefghijklmnop"), ("send", "Me@Example.org")]


def test_only_to_resolves_callsigns():
    club = Club(FIX / "test-club.yaml", roster=[{"id": "kd8aaa", "first": "J", "last": "D", "email": "J@x.org"}])
    club.email = {"only_to": ["KD8AAA", "other@y.org"]}
    assert club.email_only_to() == {"j@x.org", "other@y.org"}
    club.email = {}
    assert club.email_only_to() is None


def test_rename_passkey_and_old_db_upgrade(a, tmp_path):
    a.db.execute("insert into passkeys (id, member, public_key, sign_count, label, created) values ('p1','kd8aaa',x'00',0,'Windows PC',0)")
    a.rename_passkey("kd8aaa", "p1", "  Bitwarden ")
    a.rename_passkey("kd8bbb", "p1", "not mine")  # someone else's passkey: no effect
    assert a.passkeys("kd8aaa")[0]["label"] == "Bitwarden"
    # an auth.sqlite created before the aaguid column existed gets upgraded on start
    import sqlite3
    old = tmp_path / "old.sqlite"
    con = sqlite3.connect(old)
    con.executescript("create table passkeys (id text primary key, member text not null, public_key blob not null, "
                      "sign_count integer not null, transports text, label text, created integer not null, last_used integer)")
    con.close()
    Auth(a.club, old)
    assert "aaguid" in [r[1] for r in sqlite3.connect(old).execute("pragma table_info(passkeys)")]
