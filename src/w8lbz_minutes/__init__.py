import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="w8lbz-minutes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import historical minutes (PDFs + *CORRECTED*.txt) into the archive")
    imp.add_argument("src", type=Path)
    sub.add_parser("roster", help="sync the roster from the club Google Sheet")
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
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("w8lbz_minutes.web:app", host=a.host, port=a.port, reload=a.reload)
