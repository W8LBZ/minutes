"""Member login: passkeys (WebAuthn), with an emailed one-time link as the fallback.

Everything lives in a small SQLite file next to the archive data. Only hashes of
session and link tokens are stored, so a copy of the database can't be used to log in.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import smtplib
import sqlite3
import time
from email.message import EmailMessage
from pathlib import Path

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from .club import DATA, Club

log = logging.getLogger("w8lbz.auth")

# Passkey providers, by the AAGUID their authenticator reports (from the community-maintained
# passkey-authenticator-aaguids list). Used to name a new passkey; members can rename it.
PROVIDERS = {
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "50726f74-6f6e-5061-7373-50726f746f6e": "Proton Pass",
    "fdb141b2-5d84-443e-8a35-4698c205a502": "KeePassXC",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
}

LINK_MINUTES = 15
CHALLENGE_SECONDS = 300
EMAILS_PER_HOUR = 5

SCHEMA = """
create table if not exists sessions (token_hash text primary key, member text not null,
  created integer not null, expires integer not null, agent text);
create table if not exists links (token_hash text primary key, member text not null,
  expires integer not null, next text, used integer default 0, created integer not null);
create table if not exists passkeys (id text primary key, member text not null, public_key blob not null,
  sign_count integer not null, transports text, label text, created integer not null, last_used integer,
  aaguid text);
create table if not exists challenges (id text primary key, challenge blob not null, member text,
  kind text not null, expires integer not null);
"""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, club: Club, path: Path | None = None):
        self.club = club
        cfg = club.auth
        self.rp_id: str | None = cfg.get("rp_id")
        self.rp_name: str = cfg.get("rp_name", "W8LBZ Minutes")
        self.origins: list[str] = cfg.get("origins") or ([f"https://{self.rp_id}"] if self.rp_id else [])
        self.session_days: int = int(cfg.get("session_days", 180))
        self.base_url: str | None = cfg.get("base_url") or (self.origins[0] if self.origins else None)
        path = path or DATA / "auth.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("pragma table_info(passkeys)")}
        if "aaguid" not in cols:  # added after the first release
            self.db.execute("alter table passkeys add column aaguid text")
        os.chmod(path, 0o600)

    # ---------------- sessions ----------------
    def new_session(self, member: str, agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        self.db.execute("insert into sessions values (?,?,?,?,?)",
                        (_hash(token), member, now, now + self.session_days * 86400, agent[:200]))
        return token

    def member_for(self, token: str | None) -> str | None:
        if not token:
            return None
        row = self.db.execute("select member, expires from sessions where token_hash=?", (_hash(token),)).fetchone()
        if not row or row["expires"] < time.time():
            return None
        member = self.club.canonical(row["member"])
        return member if self.is_active(member) else None  # off the roster: access ends at the next sync

    def is_active(self, member: str) -> bool:
        m = self.club.members.get(self.club.canonical(member))
        return bool(m and m.status.lower() not in ("inactive", "silent key"))

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.execute("delete from sessions where token_hash=?", (_hash(token),))

    def sessions(self, member: str) -> list[sqlite3.Row]:
        return self.db.execute("select created, expires, agent from sessions where member=? and expires>? "
                               "order by created desc", (member, time.time())).fetchall()

    def end_all_sessions(self, member: str) -> None:
        self.db.execute("delete from sessions where member=?", (member,))

    # ---------------- email links ----------------
    def member_by_email(self, email: str) -> str | None:
        e = email.strip().lower()
        for m in self.club.members.values():
            if m.email and m.email.strip().lower() == e and self.is_active(m.id):
                return m.id
        return None

    def send_link(self, email: str, next_url: str = "/", base_url: str | None = None) -> None:
        """Email a one-time login link. Silent if the address isn't on the roster (no account probing)."""
        member = self.member_by_email(email)
        if not member:
            log.info("login link requested for an address not on the roster")
            return
        now = int(time.time())
        recent = self.db.execute("select count(*) from links where member=? and created>?",
                                 (member, now - 3600)).fetchone()[0]
        if recent >= EMAILS_PER_HOUR:
            log.warning("login link rate limit hit for %s", member)
            return
        url = self.create_link(member, next_url, base_url)
        send_email(self.club.members[member].email, "Your W8LBZ Minutes sign-in link", only_to=self.club.email_only_to(),
                   body=f"Hi {self.club.members[member].first},\n\n"
                   f"Use this link to sign in to W8LBZ Minutes. It works once, for {LINK_MINUTES} minutes:\n\n"
                   f"{url}\n\nIf you didn't ask for this, you can ignore this email.\n\n73,\nW8LBZ")

    def create_link(self, member: str, next_url: str = "/", base_url: str | None = None) -> str:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        self.db.execute("insert into links values (?,?,?,?,0,?)",
                        (_hash(token), member, now + LINK_MINUTES * 60, _safe_next(next_url), now))
        return f"{(base_url or self.base_url or '').rstrip('/')}/login/link?t={token}"

    def use_link(self, token: str) -> tuple[str, str] | None:
        """Returns (member, next_url) and burns the link, or None if invalid/expired/used."""
        row = self.db.execute("select member, expires, next, used from links where token_hash=?",
                              (_hash(token),)).fetchone()
        if not row or row["used"] or row["expires"] < time.time():
            return None
        self.db.execute("update links set used=1 where token_hash=?", (_hash(token),))
        return row["member"], row["next"] or "/"

    # ---------------- passkeys ----------------
    def _challenge(self, kind: str, challenge: bytes, member: str | None = None) -> str:
        cid = secrets.token_urlsafe(16)
        self.db.execute("delete from challenges where expires<?", (time.time(),))
        self.db.execute("insert into challenges values (?,?,?,?,?)",
                        (cid, challenge, member, kind, int(time.time()) + CHALLENGE_SECONDS))
        return cid

    def _take_challenge(self, cid: str | None, kind: str) -> sqlite3.Row | None:
        if not cid:
            return None
        row = self.db.execute("select * from challenges where id=? and kind=? and expires>?",
                              (cid, kind, time.time())).fetchone()
        self.db.execute("delete from challenges where id=?", (cid,))
        return row

    def registration_options(self, member: str) -> tuple[str, str]:
        m = self.club.members[member]
        existing = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["id"]))
                    for r in self.db.execute("select id from passkeys where member=?", (member,))]
        opts = generate_registration_options(
            rp_id=self.rp_id, rp_name=self.rp_name,
            user_id=member.encode(), user_name=m.callsign or m.email or m.name, user_display_name=m.name,
            exclude_credentials=existing,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,  # so sign-in needs no username
                user_verification=UserVerificationRequirement.PREFERRED))
        return self._challenge("register", opts.challenge, member), options_to_json(opts)

    def register(self, member: str, cid: str | None, credential: dict, label: str = "") -> None:
        ch = self._take_challenge(cid, "register")
        if not ch or ch["member"] != member:
            raise ValueError("Passkey setup expired; please try again.")
        v = verify_registration_response(credential=credential, expected_challenge=ch["challenge"],
                                         expected_rp_id=self.rp_id, expected_origin=self.origins)
        transports = json.dumps((credential.get("response") or {}).get("transports") or [])
        name = (label.strip() or PROVIDERS.get(v.aaguid) or "Passkey")[:60]
        self.db.execute("insert into passkeys (id, member, public_key, sign_count, transports, label, created, aaguid) "
                        "values (?,?,?,?,?,?,?,?)",
                        (bytes_to_base64url(v.credential_id), member, v.credential_public_key, v.sign_count,
                         transports, name, int(time.time()), v.aaguid))

    def authentication_options(self) -> tuple[str, str]:
        opts = generate_authentication_options(rp_id=self.rp_id,
                                               user_verification=UserVerificationRequirement.PREFERRED)
        return self._challenge("login", opts.challenge), options_to_json(opts)

    def authenticate(self, cid: str | None, credential: dict) -> str:
        ch = self._take_challenge(cid, "login")
        if not ch:
            raise ValueError("Sign-in expired; please try again.")
        row = self.db.execute("select * from passkeys where id=?", (credential.get("id"),)).fetchone()
        if not row:
            raise ValueError("That passkey isn't registered here. Sign in by email, then add it on your account page.")
        v = verify_authentication_response(credential=credential, expected_challenge=ch["challenge"],
                                           expected_rp_id=self.rp_id, expected_origin=self.origins,
                                           credential_public_key=row["public_key"],
                                           credential_current_sign_count=row["sign_count"])
        self.db.execute("update passkeys set sign_count=?, last_used=? where id=?",
                        (v.new_sign_count, int(time.time()), row["id"]))
        return row["member"]

    def passkeys(self, member: str) -> list[sqlite3.Row]:
        return self.db.execute("select id, label, created, last_used from passkeys where member=? "
                               "order by created", (member,)).fetchall()

    def rename_passkey(self, member: str, pid: str, label: str) -> None:
        self.db.execute("update passkeys set label=? where id=? and member=?", (label.strip()[:60] or "Passkey", pid, member))

    def remove_passkey(self, member: str, pid: str) -> None:
        self.db.execute("delete from passkeys where id=? and member=?", (pid, member))


def _safe_next(url: str) -> str:
    """Only allow local paths as a post-login redirect."""
    return url if url.startswith("/") and not url.startswith("//") else "/"


def send_email(to: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] = (),
               only_to: set[str] | None = None) -> bool:
    """Send through SMTP (Gmail by default) using W8LBZ_SMTP_* environment variables.

    `only_to` is the test-mode allowlist (club.yaml email.only_to): anything addressed to
    someone else is withheld. Without SMTP credentials, the message is logged instead.
    Returns True if the message was sent.
    """
    if only_to is not None and to.strip().lower() not in only_to:
        log.warning("email test mode: withheld %r to a recipient not in email.only_to", subject)
        return False
    user = os.environ.get("W8LBZ_SMTP_USER")
    password = (os.environ.get("W8LBZ_SMTP_PASSWORD") or "").replace(" ", "")  # Google shows app passwords in groups
    if not (user and password):
        log.warning("SMTP not configured; email to %s not sent:\n%s\n%s", to, subject, body)
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("W8LBZ_SMTP_FROM", f"W8LBZ <{user}>")
    msg["To"] = to
    msg["Subject"] = subject
    if os.environ.get("W8LBZ_SMTP_REPLY_TO"):
        msg["Reply-To"] = os.environ["W8LBZ_SMTP_REPLY_TO"]
    msg.set_content(body)
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    host, port = os.environ.get("W8LBZ_SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("W8LBZ_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    log.info("email %r sent", subject)
    return True
