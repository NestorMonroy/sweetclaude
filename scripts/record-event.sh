#!/usr/bin/env bash
set -euo pipefail

EVENT_TYPE="${1:-}"
shift || true

if [ -z "$EVENT_TYPE" ]; then
  exit 0
fi

PROJECT_DIR="${PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
METRICS_DIR="$PROJECT_DIR/.sweetclaude/metrics"
CONFIG="$METRICS_DIR/config.yaml"
EVENTS_LOG="$METRICS_DIR/events.log"

if [ ! -f "$CONFIG" ] || ! grep -q "enabled: true" "$CONFIG" 2>/dev/null; then
  exit 0
fi

# A skill_completed event exists to carry an outcome. Writing one without a
# valid outcome would land in the log as `unknown`, indistinguishable from an
# invocation that never reported at all — so it is rejected loudly instead
# (ISSUE-276).
if [ "$EVENT_TYPE" = "skill_completed" ]; then
  OUTCOME=""
  for arg in "$@"; do
    case "$arg" in outcome=*) OUTCOME="${arg#outcome=}" ;; esac
  done
  case "$OUTCOME" in
    completed|failed|abandoned|blocked) ;;
    *)
      echo "record-event.sh: skill_completed needs outcome=completed|failed|abandoned|blocked (got '${OUTCOME}')" >&2
      exit 2
      ;;
  esac
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

{
  printf -- '---\ntimestamp: %s\nevent: %s\n' "$TIMESTAMP" "$EVENT_TYPE"
  for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"
    printf '%s: %s\n' "$key" "$value"
  done
} >> "$EVENTS_LOG"
