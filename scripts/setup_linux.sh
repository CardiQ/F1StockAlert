#!/bin/bash
# Set up restock-watch as a systemd service on a Debian/Ubuntu server.
# Run from the repo checkout as a normal user with sudo:  scripts/setup_linux.sh
#
# Installs: python venv in ~/.venvs/restock-watch, Google Chrome (+ its system libs),
# and a systemd service `restock-watch` that runs `watch.py run` and restarts on failure.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.venvs/restock-watch"
USER_NAME="$(id -un)"

sudo apt-get update -q
sudo apt-get install -y -q python3 python3-venv git
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt"
# Google Chrome + the libraries it needs (patchright drives it with channel="chrome").
command -v google-chrome >/dev/null || sudo "$VENV/bin/patchright" install --with-deps chrome

[ -f "$REPO/.env" ] || { cp "$REPO/.env.example" "$REPO/.env"; chmod 600 "$REPO/.env"; \
    echo ">> Edit $REPO/.env with your SMTP login, then re-run this script."; exit 1; }

sudo tee /etc/systemd/system/restock-watch.service >/dev/null <<UNIT
[Unit]
Description=restock-watch (product restock / price-drop email alerts)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$VENV/bin/python $REPO/watch.py run
Restart=always
RestartSec=60
# Chrome can leak memory over months; restart the service daily as a safety valve.
RuntimeMaxSec=1d
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now restock-watch
echo "Running. Logs: journalctl -u restock-watch -f"
