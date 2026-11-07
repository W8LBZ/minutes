"""Roster sync from the club's Google Sheet, the single source of truth for people.

Reads columns by header name, so adding or reordering columns doesn't break it.
Columns used: callsign, full_name, email, Title(s), is_officer, is_board, Class,
minutes_editor (may lead meetings and edit minutes), Status (Active / Inactive /
Silent Key / Prospect) and aliases (comma-separated spellings seen in old minutes).

Also phone, address, birthday (MM-DD) and share (which of email, phone, address,
birthday the member shows to all members; officers always see them). The cache
file is readable only by the app.

Members' own profile edits are written back through `Sheet`, which only ever
writes cell values to existing columns: never formatting, dropdowns or structure.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .club import DATA, PREVIEW, ROOT, ROSTER_CACHE as CACHE

KEY_FILE = Path(os.environ.get("W8LBZ_GOOGLE_KEY", ROOT / "private" / "google-service-account.json"))


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("true", "yes", "y", "1", "x")


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def _sheet() -> tuple[str, str]:
    """Sheet ID and tab come from local club.yaml (`roster:`), never from code in git."""
    import yaml
    cfg = yaml.safe_load(Path(os.environ.get("W8LBZ_CONFIG", ROOT / "club.yaml")).read_text()) or {}
    r = cfg.get("roster") or {}
    if not r.get("sheet_id"):
        raise SystemExit("Set roster.sheet_id in club.yaml")
    return r["sheet_id"], r.get("tab", "Member Roster")


SHAREABLE = ("email", "phone", "address", "birthday")
EDITABLE = ("email", "phone", "address", "birthday", "share")  # member field = lowercase sheet header


def _col(i: int) -> str:
    """0-based column index -> A1 letters."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetError(Exception):
    pass


class Sheet:
    """Values-only read/write of the roster tab, for members' profile edits."""

    def __init__(self, session=None):
        if session is None and PREVIEW:
            session = PreviewSheet()
        if session is None:
            import google.auth.transport.requests as gr
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                KEY_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            session = gr.AuthorizedSession(creds)
        self.s = session
        self.sid, self.tab = ("preview", "Member Roster") if PREVIEW else _sheet()

    def _url(self, rng: str = "") -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self.sid}/values{rng}"

    def read(self, tab: str | None = None) -> list[list[str]]:
        r = self.s.get(self._url(f"/'{tab or self.tab}'"), params={"valueRenderOption": "UNFORMATTED_VALUE"})
        r.raise_for_status()
        return [[str(x) for x in row] for row in r.json().get("values", [])]

    def write(self, cells: dict[str, str], tab: str | None = None) -> None:
        """cells: A1 address (e.g. D5) -> value. RAW, so nothing typed is ever parsed as a formula."""
        body = {"valueInputOption": "RAW",
                "data": [{"range": f"'{tab or self.tab}'!{a1}", "values": [[v]]} for a1, v in cells.items()]}
        r = self.s.post(self._url(":batchUpdate"), json=body)
        if r.status_code == 403:
            raise SheetError("The app can't write to the roster sheet yet (it needs Editor access).")
        r.raise_for_status()

    def update_member(self, callsign: str | None, full_name: str, changes: dict[str, str]) -> dict[str, str]:
        """Write `changes` (field -> new value) into the member's row. Returns the old values."""
        values = self.read()
        header = [h.strip().lower() for h in values[0]]
        missing = [f for f in changes if f not in header]
        if missing:
            raise SheetError(f"The roster sheet has no {', '.join(missing)} column yet.")
        key = header.index("callsign") if callsign else header.index("full_name")
        want = (callsign or full_name).strip().upper()
        rows = [i for i, row in enumerate(values[1:], start=2)
                if len(row) > key and row[key].strip().upper() == want]
        if len(rows) != 1:
            raise SheetError(f"Couldn't find exactly one roster row for {callsign or full_name}.")
        row = values[rows[0] - 1] + [""] * len(header)
        old = {f: row[header.index(f)] for f in changes}
        self.write({f"{_col(header.index(f))}{rows[0]}": v for f, v in changes.items() if old[f] != v})
        return old


    def add_row(self, values: dict[str, str], tab: str | None = None, optional: tuple[str, ...] = ()) -> int:
        """Write a new row (header name -> value) under the last row that has a full_name. Values only:
        rows are never inserted, so the sheet's formatting, dropdowns and structure are left alone.
        (Going by full_name, not "any cell", skips rows that only hold empty checkboxes or dropdowns.)"""
        grid = self.read(tab)
        header = [h.strip().lower() for h in grid[0]] if grid else []
        values = {f: v for f, v in values.items() if f in header or f not in optional}
        missing = [f for f in values if f not in header]
        if missing or "full_name" not in header:
            raise SheetError(f"The {tab or self.tab} tab has no {', '.join(missing or ['full_name'])} column.")
        key = header.index("full_name")
        row = max((i for i, r in enumerate(grid, start=1) if i > 1 and len(r) > key and str(r[key]).strip()),
                  default=1) + 1
        self.write({f"{_col(header.index(f))}{row}": v for f, v in values.items() if v}, tab)
        return row


class PreviewSheet:
    """Preview mode's stand-in for the Sheets API: local grids (preview-sheet.json, one per tab) built from
    the roster cache, so roster edits can be tried without touching the real sheet."""
    HEADER = ["callsign", "full_name", "email", "Phone", "Address", "Class", "Title(s)", "Status", "birthday", "share"]
    LOG_HEADER = ["callsign", "full_name", "date", "event", "note"]

    def __init__(self):
        self.path = DATA / "preview-sheet.json"
        if not self.path.exists():
            people = json.loads(CACHE.read_text()) if CACHE.exists() else []
            rows = [[p.get("callsign") or "", f"{p['first']} {p['last']}", p.get("email") or "", p.get("phone") or "",
                     p.get("address") or "", p.get("license_class") or "", p.get("role") or "",
                     p.get("status") or "Active", p.get("birthday") or "", ", ".join(p.get("share") or [])]
                    for p in people]
            self.path.write_text(json.dumps({"Member Roster": [self.HEADER] + rows, "Membership Log": [self.LOG_HEADER]}))

    class _Response:
        def __init__(self, data=None):
            self.data, self.status_code = data or {}, 200

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    def get(self, url, params=None):
        tab = url.rsplit("/", 1)[1].strip("'")
        return self._Response({"values": json.loads(self.path.read_text()).get(tab, [])})

    def post(self, url, json=None):
        import json as j
        tabs = j.loads(self.path.read_text())
        for d in json["data"]:
            tab, a1 = d["range"].split("!")
            grid = tabs.setdefault(tab.strip("'"), [])
            col_letters = re.match(r"[A-Z]+", a1).group()
            col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(col_letters))) - 1
            row = int(a1[len(col_letters):]) - 1
            grid += [[] for _ in range(row + 1 - len(grid))]
            grid[row] += [""] * (col + 1 - len(grid[row]))
            grid[row][col] = d["values"][0][0]
        self.path.write_text(j.dumps(tabs))
        return self._Response()


def fetch_rows(tab: str | None = None) -> list[dict[str, str]]:
    import google.auth.transport.requests as gr
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        KEY_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    r = gr.AuthorizedSession(creds).get(
        "https://sheets.googleapis.com/v4/spreadsheets/{}/values/{}".format(_sheet()[0], tab or _sheet()[1]),
        params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
    r.raise_for_status()
    values = r.json().get("values", [])
    if not values:
        return []
    header = [h.strip().lower() for h in values[0]]
    return [dict(zip(header, [str(x) for x in row] + [""] * (len(header) - len(row)))) for row in values[1:]]


def to_members(rows: list[dict[str, str]]) -> list[dict]:
    out = []
    for r in rows:
        name, cs = r.get("full_name", "").strip(), r.get("callsign", "").strip().upper()
        if not name:
            continue
        first, _, last = name.partition(" ")
        titles = _split(r.get("title(s)", ""))
        out.append({
            # Callsign is the stable key; fall back to the name (e.g. a silent key whose call is unknown).
            "id": cs.lower() or re.sub(r"[^a-z]+", "-", name.lower()).strip("-"),
            "first": first,
            "last": last,
            "callsign": cs or None,
            "email": r.get("email", "").strip() or None,
            "role": ", ".join(titles) or None,
            "officer": _truthy(r.get("is_officer", "")),
            "board": _truthy(r.get("is_board", "")),
            "license_class": r.get("class", "").strip() or None,
            "aliases": _split(r.get("aliases", "")),
            "minutes_editor": _truthy(r.get("minutes_editor", "")),
            "status": r.get("status", "").strip() or "Active",
            "phone": r.get("phone", "").strip() or None,
            "address": r.get("address", "").strip() or None,
            "birthday": _month_day(r.get("birthday", "")),
            "share": [x.lower() for x in _split(r.get("share", "")) if x.lower() in SHAREABLE],
        })
    return out


def _iso_date(v: str) -> str | None:
    """Sheets date serial (days since 1899-12-30) or a typed date -> YYYY-MM-DD."""
    import datetime as dt
    v = v.strip()
    if not v:
        return None
    try:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(v)))).isoformat()
    except ValueError:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(v, fmt).date().isoformat()
            except ValueError:
                pass
    return v


def _month_day(v: str) -> str | None:
    """Birthday as MM-DD (the year is never kept), from MM-DD, a typed date or a Sheets date serial."""
    v = v.strip()
    if re.fullmatch(r"\d{2}-\d{2}", v):
        return v
    iso = _iso_date(v) if v else None
    return iso[5:] if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else None


def attach_log(members: list[dict], log: list[dict[str, str]]) -> None:
    """Membership Log tab: one row per event (Joined, Left, Silent Key, Callsign Change, ...)."""
    by_cs = {m["callsign"]: m for m in members if m["callsign"]}
    by_name = {m["first"] + " " + m["last"]: m for m in members}
    for e in log:
        m = by_cs.get(e.get("callsign", "").strip().upper()) or by_name.get(e.get("full_name", "").strip())
        if m and e.get("event"):
            m.setdefault("events", []).append(
                {"date": _iso_date(e.get("date", "")), "event": e["event"].strip(), "note": e.get("note", "").strip() or None})
    for m in members:
        joins = [e["date"] for e in m.get("events", []) if e["event"] in ("Joined", "Rejoined") and e["date"]]
        m["member_since"] = max(joins) if joins else None


def sync() -> list[dict]:
    members = to_members(fetch_rows())
    try:
        attach_log(members, fetch_rows("Membership Log"))
    except Exception as e:  # the log is optional
        print(f"Membership Log not read: {e}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(members, indent=1))
    tmp.chmod(0o600)
    tmp.replace(CACHE)
    return members


def load_cached() -> list[dict] | None:
    return json.loads(CACHE.read_text()) if CACHE.exists() else None
