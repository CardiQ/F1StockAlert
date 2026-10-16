#!/bin/bash
# Run `watch.py check` every 30 minutes on this Mac via launchd (use this if the store
# blocks GitHub's servers). Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.restock-watch.check.plist && rm ~/Library/LaunchAgents/com.restock-watch.check.plist
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.venvs/restock-watch"
[ -x "$VENV/bin/python" ] || { python3 -m venv "$VENV"; "$VENV/bin/pip" install -q -r "$REPO/requirements.txt"; }
PLIST="$HOME/Library/LaunchAgents/com.restock-watch.check.plist"
mkdir -p "$HOME/Library/Logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.restock-watch.check</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>cd "$REPO" &amp;&amp; (git pull -q --rebase --autostash || true) &amp;&amp; "$VENV/bin/python" watch.py check; git add watches.json &amp;&amp; git commit -qm "Update watch state (local)" &amp;&amp; git push -q || true</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/restock-watch.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/restock-watch.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed. Log: ~/Library/Logs/restock-watch.log"
