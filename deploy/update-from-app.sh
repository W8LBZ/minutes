#!/usr/bin/env bash
# Run as root by w8lbz-minutes-update.service when the app's admin page asks for an update
# (it writes update-request.json in the data folder). Runs update.sh, the same as updating by hand,
# and leaves the outcome in update-status.json for the app to show. update.sh replaces this file while
# it runs, so everything is inside main(), which bash reads in full before starting.
main() {
  set -uo pipefail
  local DATA=/var/lib/w8lbz-minutes APP=/opt/w8lbz-minutes
  local REQ=$DATA/update-request.json RUN=$DATA/update-running.json OUT=$DATA/update-status.json
  [ -f "$REQ" ] || return 0
  mv "$REQ" "$RUN"
  local LOG; LOG=$(mktemp)
  local start; start=$(date +%s)
  local ok=false
  if "$APP/deploy/update.sh" >"$LOG" 2>&1; then ok=true; fi
  "$APP/.venv/bin/python" - "$RUN" "$LOG" "$OUT" "$ok" "$start" <<'PY'
import json, sys, time
run, logf, out, ok, start = sys.argv[1:]
req = json.load(open(run))
tail = open(logf, errors="replace").read()[-4000:]
json.dump({**req, "ok": ok == "true", "started": int(start), "finished": int(time.time()), "output": tail}, open(out, "w"))
PY
  chown minutes:minutes "$OUT"; chmod 600 "$OUT"
  rm -f "$RUN" "$LOG"
}
main "$@"; exit
