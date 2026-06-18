#!/usr/bin/env bash
# Build submission.tar.gz for pokemon-tcg-ai-battle.
# Run from repo root: ./explore/build_submission.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="${1:-submission.tar.gz}"

if [[ ! -f agent/main.py ]] || [[ ! -f agent/deck.csv ]]; then
  echo "error: agent/main.py and agent/deck.csv are required" >&2
  exit 1
fi

DECK_LINES=$(wc -l < agent/deck.csv)
if [[ "$DECK_LINES" -ne 60 ]]; then
  echo "error: agent/deck.csv must have 60 lines (found $DECK_LINES)" >&2
  exit 1
fi

TAR_ARGS=(
  -czf "$OUT"
  -C "$ROOT"
  --transform='s|^agent/main\.py$|main.py|'
  --transform='s|^agent/deck\.csv$|deck.csv|'
  agent/main.py agent/deck.csv
  agent/mcts_agent.py agent/mcts.py agent/value_net.py
  agent/features.py agent/greedy.py agent/search_api.py
)

if [[ -f models/value_net_best.pt ]]; then
  TAR_ARGS+=(models/value_net_best.pt)
else
  echo "warning: models/value_net_best.pt not found — building without value net" >&2
fi

tar "${TAR_ARGS[@]}"

echo "Built $OUT"
tar -tzf "$OUT"
