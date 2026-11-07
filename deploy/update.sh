#!/usr/bin/env bash
# Update to the latest main (or BRANCH=...) and restart. Run as root.
set -euo pipefail
APP=/opt/w8lbz-minutes BRANCH=${BRANCH:-main}
cd "$APP"
sudo -u minutes git fetch -q origin
sudo -u minutes git reset -q --hard "origin/$BRANCH"
sudo -u minutes env UV_CACHE_DIR=/var/lib/w8lbz-minutes-home/.cache/uv uv sync -q --frozen --no-dev
# Install the app's systemd units (new ones arrive with updates) and turn on its timers.
install -m 644 "$APP"/deploy/w8lbz-minutes*.service "$APP"/deploy/w8lbz-minutes*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q w8lbz-minutes
for t in "$APP"/deploy/w8lbz-minutes*.timer; do systemctl enable -q --now "$(basename "$t")"; done
systemctl restart w8lbz-minutes
echo "Now at $(sudo -u minutes git log --oneline -1)"
