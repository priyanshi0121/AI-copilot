#!/usr/bin/env bash
# End-to-end AIOps Copilot demo — proves detection → diagnosis → remediation.
# Usage: ./scripts/demo.sh   (the full stack must be running: docker compose up -d)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

DASH="http://localhost:8000"
PAY="http://localhost:5002"

say() { echo; echo "== $1 =="; }

say "1. Baseline — copilot health & current state"
curl -s "$DASH/health"; echo
python3 "$DIR/show_state.py"

say "2. Record a deploy (gives the correlation engine something to blame)"
curl -s -X POST "$DASH/deploys" -d "service=payment-service" -d "note=demo: connection pool change" -o /dev/null
echo "deploy recorded."

say "3. Inject chaos: payment-service slow mode (+2s per request)"
curl -s -X POST "$PAY/chaos/slow?enabled=true" -o /dev/null
echo "chaos ON. Waiting ~35s for the detector..."
sleep 35
python3 "$DIR/show_state.py"

say "4. Open $DASH in your browser — review the incident card, then click Rollback."
read -r -p "Press Enter to run the rollback from the CLI instead…" _
curl -s -X POST "$DASH/action/rollback" -d "incident_id=1" -o /dev/null || true
echo "rollback sent. Waiting ~30s for auto-resolution + postmortem..."
sleep 30
python3 "$DIR/show_state.py" --resolved

say "Done. Full timeline, knapsack plan, and postmortems at $DASH"
