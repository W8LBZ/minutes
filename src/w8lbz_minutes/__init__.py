import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="w8lbz-minutes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import historical minutes (PDFs + *CORRECTED*.txt) into the archive")
    imp.add_argument("src", type=Path)
    sub.add_parser("roster", help="sync the roster from the club Google Sheet")
    lk = sub.add_parser("login-link", help="print a one-time sign-in link for a member (admin recovery)")
    lk.add_argument("who", help="callsign, or the member's email")
    lk.add_argument("--base-url", help="defaults to https://<auth.rp_id>")
    rm = sub.add_parser("delete-meeting", help="delete one meeting's minutes, e.g. after a test (restart the service afterwards)")
    rm.add_argument("date", help="YYYY-MM-DD")
    ci = sub.add_parser("chow-import", help="one-time import of the Secretary's chow .xlsx (prints it; --write saves)")
    ci.add_argument("xlsx", type=Path)
    ci.add_argument("--order", required=True, help="rotation order: surnames, comma-separated")
    ci.add_argument("--next", help="who the rotation continues with (surname)")
    ci.add_argument("--year", type=int, default=2026, help="year for dates written like 5-Mar")
    ci.add_argument("--write", action="store_true", help="save it (refuses if a chow schedule already exists)")
    srv = sub.add_parser("serve", help="run the web UI")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--reload", action="store_true")
    a = ap.parse_args()

    if a.cmd == "import":
        from .importer import import_archive
        ms = import_archive(a.src)
        print(f"imported {len(ms)} meetings")
    elif a.cmd == "roster":
        from .roster import sync
        ms = sync()
        print(f"synced {len(ms)} members, {sum(m['officer'] for m in ms)} officers")
    elif a.cmd == "login-link":
        from .auth import Auth
        from .club import Club
        auth = Auth(Club())
        mid = a.who.lower() if a.who.lower() in auth.club.members else auth.member_by_email(a.who)
        if not mid or not auth.is_active(mid):
            raise SystemExit(f"No active member matches {a.who!r}")
        print(f"Sign-in link for {auth.club.name(mid)} (one use, 15 minutes):")
        print(auth.create_link(mid, base_url=a.base_url))
    elif a.cmd == "delete-meeting":
        import datetime as dt
        import shutil
        from .club import MEETINGS
        d = MEETINGS / dt.date.fromisoformat(a.date).isoformat()
        if not (d / "minutes.md").exists():
            raise SystemExit(f"No minutes for {a.date}")
        shutil.rmtree(d)
        print(f"Deleted {d}. Restart the web service so it drops it from memory.")
    elif a.cmd == "chow-import":
        from . import chow
        from .club import Club
        club = Club()
        s, problems = chow.import_xlsx(club, a.xlsx, [x.strip() for x in a.order.split(",")], "import", a.year)
        if a.next:
            s["next"] = chow.match_name(club, a.next) or problems.append(f"--next: no member matches {a.next!r}")
        for d, x in sorted(s["nights"].items()):
            print(d, club.name(x["member"]) if x["member"] else f"no chow ({x.get('note') or ''})")
        print("Rotation:", ", ".join(club.name(m) for m in s["order"]))
        print("Next up:", club.name(chow.next_up(club, s)))
        print("Not in the rotation yet:", ", ".join(club.name(m) for m in s["pending"]) or "nobody")
        for p in problems:
            print("CHECK:", p)
        if a.write:
            if chow._path().exists():
                raise SystemExit(f"{chow._path()} already exists; not overwriting it.")
            chow.save(s)
            chow._log("import", "import", file=a.xlsx.name, nights=len(s["nights"]))
            print(f"Saved {len(s['nights'])} nights to {chow._path()}")
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("w8lbz_minutes.web:app", host=a.host, port=a.port, reload=a.reload,
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1")
