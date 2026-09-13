#!/bin/bash
# Scheduled refresh: ingest, process what changed, write the digest, tell
# the API to reload. The schedule is weekly (Monday 08:00). Run from anywhere:
#     scripts/update.sh weekly     # every source, then the previous week's digest
#     scripts/update.sh daily      # on demand: only the sources marked daily
set -uo pipefail
SCHEDULE="${1:-daily}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export TOKENIZERS_PARALLELISM=false   # the pipeline forks after loading tokenizers

echo "== $(date -u +%FT%TZ) update $SCHEDULE =="
if ! pgrep -x mongod >/dev/null; then
  echo "mongod not running; trying brew services"
  brew services start mongodb-community >/dev/null 2>&1 || true
  sleep 3
fi

if [ "$SCHEDULE" = "weekly" ]; then
  "$PY" scripts/ingest.py --schedule weekly --schedule daily
else
  "$PY" scripts/ingest.py --schedule daily
fi
INGEST_STATUS=$?

"$PY" scripts/run_pipeline.py --funding-limit 150
PIPELINE_STATUS=$?

if [ "$SCHEDULE" = "weekly" ]; then
  "$PY" scripts/generate_digest.py --week previous || echo "digest: nothing to write or generation failed"
fi

# Hot-reload a running API, if any.
if [ -f "$ROOT/.env" ]; then
  TOKEN="$(grep '^ADMIN_TOKEN=' "$ROOT/.env" | cut -d= -f2-)"
  if [ -n "$TOKEN" ]; then
    # -f: a 401/404/500 is a failure, not "reloaded".
    if curl -sf -m 60 -X POST -H "Authorization: Bearer $TOKEN" \
         "${API_URL:-http://localhost:8000}/admin/reload" >/dev/null 2>&1; then
      echo "api reloaded"
    else
      echo "api not running or reload refused; skipped"
    fi
  fi
fi

echo "== done: ingest=$INGEST_STATUS pipeline=$PIPELINE_STATUS =="
exit $(( INGEST_STATUS || PIPELINE_STATUS ))
