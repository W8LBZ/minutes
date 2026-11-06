#!/usr/bin/env bash
# Update to the latest main (or BRANCH=...) and restart. Run as root.
set -euo pipefail
APP=/opt/w8lbz-minutes BRANCH=${BRANCH:-main}
cd "$APP"
sudo -u minutes git fetch -q origin
sudo -u minutes git reset -q --hard "origin/$BRANCH"
sudo -u minutes env UV_CACHE_DIR=/var/lib/w8lbz-minutes-home/.cache/uv uv sync -q --frozen --no-dev
systemctl enable -q w8lbz-minutes
systemctl restart w8lbz-minutes
echo "Now at $(sudo -u minutes git log --oneline -1)"
