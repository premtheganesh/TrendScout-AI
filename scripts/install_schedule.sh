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
