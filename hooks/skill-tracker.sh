#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude Skill Tracker Hook
# PostToolUse — records skill invocations to session-guardian.json and metrics/events.log

TOOL="$CLAUDE_TOOL_NAME"

# Only track Skill tool calls
if [[ "$TOOL" != "Skill" ]]; then
  exit 0
fi

# Find project root
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$PROJECT_DIR" ]; then
  exit 0
fi

STATE_DIR="$PROJECT_DIR/.sweetclaude/state"
GUARDIAN_FLAG="$STATE_DIR/guardian-enabled"
SESSION_FILE="$STATE_DIR/session-guardian.json"
METRICS_CONFIG="$PROJECT_DIR/.sweetclaude/metrics/config.yaml"
EVENTS_LOG="$PROJECT_DIR/.sweetclaude/metrics/events.log"

# Parse skill name from stdin JSON (field is tool_input.skill)
INPUT=$(cat)
SKILL_NAME=$(echo "$INPUT" | jq -r '.tool_input.skill' 2>/dev/null)

if [ -z "$SKILL_NAME" ] || [ "$SKILL_NAME" = "null" ]; then
  exit 0
fi

# ── Guardian tracking ─────────────────────────────────────────────────────────
if [ -f "$GUARDIAN_FLAG" ] && [ -f "$SESSION_FILE" ]; then
  TMPFILE=$(mktemp)
  if jq --arg skill "$SKILL_NAME" '.skills_invoked += [$skill]' "$SESSION_FILE" > "$TMPFILE" 2>/dev/null; then
    mv "$TMPFILE" "$SESSION_FILE"
  else
    rm -f "$TMPFILE"
  fi
fi

# ── Metrics recording ─────────────────────────────────────────────────────────
if [ -f "$METRICS_CONFIG" ] && grep -q "enabled: true" "$METRICS_CONFIG" 2>/dev/null; then
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  PHASE=$(python3 -c "
import yaml
try:
    d = yaml.safe_load(open('$PROJECT_DIR/.sweetclaude/state/sweetclaude.yaml')) or {}
    print(d.get('work', {}).get('active', {}).get('phase') or 'none')
except Exception:
    print('none')
" 2>/dev/null || echo "none")
  printf -- '---\ntimestamp: %s\nevent: skill_invoked\nskill: %s\nphase: %s\n' \
    "$TIMESTAMP" "$SKILL_NAME" "$PHASE" >> "$EVENTS_LOG"
fi

exit 0
