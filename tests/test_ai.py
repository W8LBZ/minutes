"""AI follow-ups: what's sent (never-record lines removed), checking the answer, and nothing applied until accepted."""
import datetime as dt
import json
from pathlib import Path

import pytest

from w8lbz_minutes import ai, business
from w8lbz_minutes.club import Club
from w8lbz_minutes.meeting import Item, Meeting

FIX = Path(__file__).parent / "fixtures"
PEOPLE = [{"id": "sec", "first": "Sam", "last": "Scribe", "role": "Secretary", "officer": True},
          {"id": "amy", "first": "Amy", "last": "Able", "callsign": "KD8AMY"}]


class Reply:
    def __init__(self, content, status=200):
        self.status_code, self.text = status, content
        self._data = {"choices": [{"message": {"content": content}}], "model": "test/model",
                      "usage": {"prompt_tokens": 900, "completion_tokens": 120, "cost": 0.0004}}

    def json(self):
        return self._data


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "DATA", tmp_path)
    monkeypatch.setenv("W8LBZ_OPENROUTER_KEY", "test-key")
    club = Club(FIX / "test-club.yaml", roster=PEOPLE)
    club.ai = {"model": "test/model"}
    club.redact = ["secretname"]
    m = Meeting(date=dt.date(2026, 11, 12), status="published", sections={
        "Community Reports": [Item("Amy will call the park about Field Day by December 1", "amy"),
                              Item("Secret Name visited again")],
        "New Business": [Item("Order a new feedline")]})
    return club, m, tmp_path


def test_followups_sent_and_checked(env):
    club, m, tmp = env
    sent = {}

    def post(url, json, timeout, headers):
        sent.update(json)
        assert headers["Authorization"] == "Bearer test-key"
        return Reply(__import__("json").dumps({"suggestions": [
            {"kind": "new", "text": "Call the park about Field Day", "owner": "amy", "due": "2026-12-01", "why": "Amy will call"},
            {"kind": "new", "text": "Order a new feedline", "owner": "nobody-here", "due": "2020-01-01"},  # bad owner/date dropped
            {"kind": "update", "item": "abc", "owner": "amy"},                       # unknown item: treated as new, no text: dropped
            {"kind": "new", "text": "Ask Secret Name to join"},                     # never-record: dropped
        ]}))
    found = ai.suggest_followups(club, m, [{"id": "x1", "text": "Club patches", "owner": None, "due": None}], post=post)
    prompt = sent["messages"][1]["content"]
    assert "Secret Name" not in prompt and "Amy will call the park" in prompt and "x1 | Club patches" in prompt
    assert "amy: Amy Able (KD8AMY)" in prompt and sent["model"] == "test/model"
    assert found == [{"kind": "new", "item": None, "text": "Call the park about Field Day", "owner": "amy",
                      "due": "2026-12-01", "why": "Amy will call"},
                     {"kind": "new", "item": None, "text": "Order a new feedline", "owner": None, "due": None, "why": ""}]
    log = json.loads((tmp / "ai-log.jsonl").read_text())
    assert log["cost"] == 0.0004 and "text" not in log and "Amy" not in json.dumps(log)  # usage only, no content


def test_not_configured_or_failing(env, monkeypatch):
    club, m, _ = env
    with pytest.raises(ai.AIError):
        ai.suggest_followups(club, m, [], post=lambda *a, **k: Reply("oops", 500))
    with pytest.raises(ai.AIError):
        ai.suggest_followups(club, m, [], post=lambda *a, **k: Reply("not json"))
    monkeypatch.delenv("W8LBZ_OPENROUTER_KEY")
    assert not ai.configured(club)


def test_suggestions_wait_for_a_person(tmp_path, monkeypatch):
    s = business.load()
    item = business.add(s, "Club patches", "sec", opened="2026-11-05")
    business.add_suggestions(s, "2026-11-12", [
        {"kind": "new", "item": None, "text": "Call the park", "owner": "amy", "due": "2026-12-01", "why": ""},
        {"kind": "update", "item": item["id"], "text": "", "owner": "sec", "due": None, "why": ""},
        {"kind": "new", "item": None, "text": "Not really a task", "owner": None, "due": None, "why": ""}], "m")
    assert len(s["items"]) == 1                                       # nothing applied yet
    a, b, c = s["suggestions"]
    x = business.accept_suggestion(s, a["id"], "sec", text="Call the park about Field Day", owner="amy", due="2026-12-01")
    assert x["opened"] == "2026-11-12" and x["text"] == "Call the park about Field Day"
    business.accept_suggestion(s, b["id"], "sec")
    assert item["owner"] == "sec"
    business.dismiss_suggestion(s, c["id"], "sec")
    with pytest.raises(ValueError):
        business.accept_suggestion(s, c["id"], "sec")
    assert [g["status"] for g in s["suggestions"]] == ["accepted", "accepted", "dismissed"]


def test_business_page_suggestions_for_leaders_only(env, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from w8lbz_minutes import web
    from w8lbz_minutes.store import Archive
    club, m, _ = env
    meetings = tmp_path / "meetings"
    m.save(meetings)
    monkeypatch.setattr(web, "archive", Archive(meetings, club))
    who = {"id": "amy"}
    monkeypatch.setattr(web.authn, "member_for", lambda token: who["id"])
    monkeypatch.setattr(ai, "suggest_followups", lambda club, m, items, post=None: [
        {"kind": "new", "item": None, "text": "Call the park", "owner": "amy", "due": None, "why": "Amy will call"}])
    c = TestClient(web.app)
    assert c.post("/business/suggest", data={"meeting": "2026-11-12"}).status_code == 403
    who["id"] = "sec"
    assert "1 suggestion from the November 12 minutes" in c.post("/business/suggest", data={"meeting": "2026-11-12"}).text
    page = c.get("/business?tab=suggestions").text
    assert "Suggestions (1)" in page and "Call the park" in page
    who["id"] = "amy"
    page = c.get("/business?tab=suggestions").text
    assert "Suggestions (" not in page and "Call the park" not in page   # members don't see suggestions
    who["id"] = "sec"
    sid = business.load()["suggestions"][0]["id"]
    c.post(f"/business/suggestions/{sid}/accept", data={"text": "Call the park about Field Day", "owner": "amy", "due": ""})
    assert [x["text"] for x in business.load()["items"]][-1] == "Call the park about Field Day"


def test_ask_about_prompts(env, monkeypatch, tmp_path):
    from w8lbz_minutes import console
    from w8lbz_minutes.store import Archive
    club, _, _ = env
    sent = {}

    def post(url, json, timeout, headers):
        sent["user"] = json["messages"][1]["content"]
        return Reply(__import__("json").dumps({"members": {
            "amy": ["Ask how the 40 m dipole build went.", "Ask about the VE exam.", "a third one is dropped"],
            "sec": [], "stranger": ["not a member we asked about"]}}))
    meetings = tmp_path / "meetings"
    for d, text in (("2026-10-22", "Amy started building a 40 m dipole"), ("2026-10-29", "Amy is studying for General"),
                    ("2026-11-05", "Amy talked to Secret Name on 2 m")):
        Meeting(date=dt.date.fromisoformat(d), status="published",
                sections={"Community Reports": [Item(text, "amy"), Item("Sam: nothing new", "sec")]}).save(meetings)
    a = Archive(meetings, club)
    monkeypatch.setattr(console, "DATA", tmp_path)
    monkeypatch.setattr(ai, "complete", lambda club, system, user, purpose, post_=None: post(None, {"messages": [{}, {"content": user}]}, 0, {}).text)
    assert console.refresh_ask_about(a) == 2
    assert "40 m dipole" in sent["user"] and "Secret Name" not in sent["user"]       # never-record line not sent
    m = console.start(a, dt.date(2026, 11, 12), "sec")
    asks = console.context(a, m)["ask_about"]
    assert asks == {"amy": ["Ask how the 40 m dipole build went.", "Ask about the VE exam."], "sec": []}
    # A newer report makes the saved prompts stale: the console falls back to what they said.
    console.submit(a, m.slug)
    a.by_slug[m.slug].sections["Community Reports"] = [Item("Amy finished the dipole", "amy")]
    a.by_slug[m.slug].save(meetings)
    a.reload()
    assert "amy" not in console.context(a, console.start(a, dt.date(2026, 11, 19), "sec"))["ask_about"]
