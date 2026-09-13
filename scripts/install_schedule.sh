#!/bin/bash
# Install (or remove) the launchd jobs: daily news at 07:30, weekly full
# refresh Mondays 08:00. Logs land in logs/.
#     scripts/install_schedule.sh          # install / reload
#     scripts/install_schedule.sh remove
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$ROOT/logs"
for job in com.trendscout.daily com.trendscout.weekly; do
  launchctl unload "$AGENTS/$job.plist" 2>/dev/null || true
  if [ "${1:-}" = "remove" ]; then
    rm -f "$AGENTS/$job.plist"; echo "removed $job"
  else
    cp "$ROOT/deploy/launchd/$job.plist" "$AGENTS/$job.plist"
    launchctl load "$AGENTS/$job.plist"; echo "loaded $job"
  fi
done
launchctl list | grep trendscout || true

cat <<'NOTE'

macOS note: if the project lives under ~/Desktop or ~/Documents, launchd jobs
are blocked by privacy protection and the log shows "Operation not permitted".
Grant Full Disk Access to /bin/bash once:
  System Settings -> Privacy & Security -> Full Disk Access -> "+" -> press
  Cmd+Shift+G, type /bin/bash, add it, toggle on.
Then test with:  launchctl start com.trendscout.daily ; tail -f logs/daily.log
(Alternatively keep the project outside ~/Desktop and ~/Documents.)
NOTE
