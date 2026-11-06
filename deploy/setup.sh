#!/usr/bin/env bash
# One-time setup of the minutes app on a Debian container. Run as root. Safe to re-run.
#   Layout:  /opt/w8lbz-minutes        app code (git clone of main), owned by the 'minutes' user
#            /etc/w8lbz-minutes/       club.yaml, google-service-account.json, env (secrets; not in git)
#            /var/lib/w8lbz-minutes/   data: meetings archive, roster cache
set -euo pipefail
REPO=${REPO:-https://github.com/W8LBZ/minutes.git}
APP=/opt/w8lbz-minutes CONF=/etc/w8lbz-minutes DATA=/var/lib/w8lbz-minutes

apt-get update -qq
# git/curl: deploy; pango + fonts: PDF rendering (WeasyPrint)
apt-get install -y -qq git curl ca-certificates libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core fonts-liberation >/dev/null

id minutes >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/w8lbz-minutes-home --shell /usr/sbin/nologin minutes
install -d -o minutes -g minutes -m 750 "$DATA"
install -d -o root -g minutes -m 750 "$CONF"
[ -f "$CONF/env" ] || install -o root -g minutes -m 640 /dev/null "$CONF/env"

# uv (Python package manager), installed system-wide for the service user
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi

if [ ! -d "$APP/.git" ]; then
  install -d -o minutes -g minutes "$APP"
  sudo -u minutes git clone -q "$REPO" "$APP"
fi

install -m 644 "$APP/deploy/w8lbz-minutes.service" "$APP/deploy/w8lbz-minutes-roster.service" \
  "$APP/deploy/w8lbz-minutes-roster.timer" /etc/systemd/system/
systemctl daemon-reload
"$APP/deploy/update.sh"
systemctl enable --now w8lbz-minutes-roster.timer
echo "Setup done. Put club.yaml and google-service-account.json in $CONF, then: systemctl restart w8lbz-minutes"
