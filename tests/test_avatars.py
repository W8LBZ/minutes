"""Profile pictures: squared and stripped of camera data, members-only, removable by the member or an officer."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from w8lbz_minutes import avatars

FIX = Path(__file__).parent / "fixtures"


def photo(w=800, h=600, fmt="JPEG", exif=True) -> bytes:
    img = Image.new("RGB", (w, h), (200, 30, 30))
    out = io.BytesIO()
    kw = {}
    if exif:
        e = Image.Exif()
        e[0x010F] = "PhoneMaker"   # camera make
        e[0x8825] = {2: (41.0, 27.0, 0.0)}  # GPS latitude
        kw["exif"] = e
    img.save(out, fmt, **kw)
    return out.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(avatars, "DATA", tmp_path)
    return tmp_path


def test_save_squares_and_strips(env):
    avatars.save("amy", photo())
    img = Image.open(avatars.path("amy"))
    assert img.size == (256, 256) and img.format == "JPEG" and not dict(img.getexif())
    assert avatars.url("amy").startswith("/avatars/amy.jpg?v=") and avatars.url("bob") is None
    assert oct(avatars.path("amy").stat().st_mode)[-3:] == "600"
    for bad in (b"", b"not a picture", photo(fmt="GIF", exif=False)):
        with pytest.raises(ValueError):
            avatars.save("amy", bad)
    assert avatars.remove("amy") and not avatars.path("amy").exists()


def test_routes(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.club import Club
    from w8lbz_minutes.store import Archive
    club = Club(FIX / "test-club.yaml", roster=[
        {"id": "amy", "first": "Amy", "last": "Able"}, {"id": "bob", "first": "Bob", "last": "Baker"},
        {"id": "sec", "first": "Sam", "last": "Scribe", "role": "Secretary", "officer": True}])
    monkeypatch.setattr(web, "archive", Archive(tmp_path, club))
    who = {"id": "amy"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: who["id"])
    c = TestClient(web.app)
    assert 'class="avatar md initials"' in c.get("/profile").text and ">AA<" in c.get("/profile").text
    r = c.post("/profile/photo", files={"photo": ("me.jpg", photo(), "image/jpeg")}, follow_redirects=False)
    assert r.headers["location"] == "/profile?photo=1"
    page = c.get("/roster").text
    assert "/avatars/amy.jpg?v=" in page
    img = c.get("/avatars/amy.jpg")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert "a picture we can read" in c.post("/profile/photo", files={"photo": ("x.jpg", b"nope", "image/jpeg")}).text
    who["id"] = "bob"
    assert c.post("/members/amy/photo/remove").status_code == 403          # not an officer
    who["id"] = "sec"
    c.post("/members/amy/photo/remove")
    assert not avatars.path("amy").exists() and c.get("/avatars/amy.jpg").status_code == 404
