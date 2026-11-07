#!/usr/bin/env bash
# Run a branch as a preview on this machine, reachable from the LAN, without touching CT103.
#
#   deploy/preview.sh BRANCH          start or update the preview of BRANCH (prints its address and a sign-in link)
#   deploy/preview.sh --stop BRANCH   stop it and delete its copy
#   deploy/preview.sh --list          show running previews
#
# Each preview gets its own checkout and its own copy of data/ (meetings, roster cache, chow schedule;
# never the login database), with made-up contact details in place of the real ones. It runs in preview mode: email goes to an outbox page instead of being sent,
# and roster edits go to a local copy of the sheet. Ports start at 8100.
set -euo pipefail
REPO=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
BASE=${W8LBZ_PREVIEWS:-$(dirname "$REPO")/previews}
HOST_IP=$(hostname -I | awk '{print $1}')
unit() { echo "w8lbz-preview-$(echo "$1" | tr -c 'a-zA-Z0-9-\n' '-')"; }

case "${1:-}" in
  --list)
    systemctl --user list-units --no-legend 'w8lbz-preview-*' | awk '{print $1, $3, $4}'
    for d in "$BASE"/*/; do [ -f "$d/port" ] && echo "$(basename "$d"): http://$HOST_IP:$(cat "$d/port")"; done
    exit 0 ;;
  --stop)
    B=${2:?branch}; systemctl --user stop "$(unit "$B")" 2>/dev/null || true
    git -C "$REPO" worktree remove --force "$BASE/$B/app" 2>/dev/null || true
    rm -rf "${BASE:?}/$B"; echo "Stopped and removed the preview of $B"; exit 0 ;;
  ""|-*) sed -n '2,11p' "$0"; exit 1 ;;
esac

B=$1; DIR=$BASE/$B; U=$(unit "$B")
mkdir -p "$DIR"
git -C "$REPO" fetch -q origin
if [ -d "$DIR/app" ]; then git -C "$DIR/app" reset -q --hard "origin/$B"
else git -C "$REPO" worktree add -q --detach "$DIR/app" "origin/$B"; fi

# Older branches have no preview mode: they would send real email and write to the real roster sheet.
if ! grep -q W8LBZ_PREVIEW "$DIR/app/src/w8lbz_minutes/club.py"; then
  echo "Refusing: $B has no preview mode (it would send real email). Rebase it on main first." >&2
  git -C "$REPO" worktree remove --force "$DIR/app"; rm -rf "${DIR:?}"; exit 1
fi

# A fresh copy of the data each time; the preview keeps its own sign-ins (auth.sqlite) between updates.
mkdir -p "$DIR/data"
find "$DIR/data" -mindepth 1 -maxdepth 1 ! -name auth.sqlite -exec rm -rf {} +
# Everything in data/ (meetings, roster cache, chow schedule, ...) except the live login database.
find "$REPO/data" -mindepth 1 -maxdepth 1 ! -name 'auth.sqlite*' ! -name 'preview-*' -exec cp -r {} "$DIR/data/" \;
[ -f "$REPO/private/bylaws.md" ] && cp "$REPO/private/bylaws.md" "$DIR/data/"
cp "$REPO/club.yaml" "$DIR/club.yaml"
# Made-up contact details for everyone (see the script for which members to test sharing with).
[ -f "$DIR/data/roster.json" ] && python3 "$REPO/deploy/preview-fake.py" "$DIR/data"
chmod -R go-rwx "$DIR/data" "$DIR/club.yaml"

if [ -f "$DIR/port" ]; then PORT=$(cat "$DIR/port")
else PORT=8100; while ss -ltn | grep -q ":$PORT " || grep -qx "$PORT" "$BASE"/*/port 2>/dev/null; do PORT=$((PORT+1)); done
  echo "$PORT" > "$DIR/port"; fi

(cd "$DIR/app" && uv sync -q --frozen)
systemctl --user stop "$U" 2>/dev/null || true
systemctl --user reset-failed "$U" 2>/dev/null || true
ENV=(W8LBZ_PREVIEW="$B" W8LBZ_DATA="$DIR/data" W8LBZ_CONFIG="$DIR/club.yaml" W8LBZ_ROOT="$DIR/app")
systemd-run --user -q --unit "$U" --collect -p WorkingDirectory="$DIR/app" \
  $(printf -- '--setenv=%s ' "${ENV[@]}") "$DIR/app/.venv/bin/w8lbz-minutes" serve --host 0.0.0.0 --port "$PORT"
for _ in $(seq 20); do curl -s -o /dev/null "http://127.0.0.1:$PORT/login" && break; sleep 0.5; done

echo "Preview of $B ($(git -C "$DIR/app" log --oneline -1)): http://$HOST_IP:$PORT"
echo "Sign in (one use, 15 minutes):"
(cd "$DIR/app" && env "${ENV[@]}" .venv/bin/w8lbz-minutes login-link "${W8LBZ_PREVIEW_USER:-KO4CGQ}" --base-url "http://$HOST_IP:$PORT" | tail -1)
