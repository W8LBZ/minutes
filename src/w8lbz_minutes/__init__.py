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
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("w8lbz_minutes.web:app", host=a.host, port=a.port, reload=a.reload,
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1")
