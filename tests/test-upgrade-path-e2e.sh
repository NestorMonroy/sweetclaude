#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# End-to-end upgrade simulation for plugin-native hook reconciliation.
# Tests that ensure-global-hooks.py keeps ~/.claude/settings.json clean now
# that SweetClaude preflight hooks are declared by the plugin manifest, covering:
#   1. Cleanup of old literal ${CLAUDE_PLUGIN_ROOT} settings entries
#   2. Idempotency after cleanup
#   3. Multi-mirror installed_plugins.json: scope=user, newest-first sort
#   4. Non-user scope entries are ignored

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENSURE_HOOKS="$REPO_ROOT/scripts/maintenance/ensure-global-hooks.py"
FAILED=0
fail() { echo "  FAIL: $1"; FAILED=$((FAILED + 1)); }
pass() { echo "  PASS: $1"; }

TMPROOT=$(mktemp -d)
trap "rm -rf $TMPROOT" EXIT

# Check assertions via Python and report pass/fail from COUNT= output.
_assert_json() {
  local label="$1"
  local settings_path="$2"
  local py_block="$3"
  local result
  result=$(printf '%s' "$py_block" | HOME="$TMPROOT" python3 - "$settings_path" 2>/dev/null) || true
  local count
  count=$(printf '%s\n' "$result" | grep '^COUNT=' | cut -d= -f2)
  if [ "${count:-0}" -eq 0 ]; then
    pass "$label"
  else
    local errors
    errors=$(printf '%s\n' "$result" | grep -v '^COUNT=' || true)
    while IFS= read -r line; do
      [ -n "$line" ] && fail "$label: $line"
    done <<< "$errors"
  fi
}

# ---------------------------------------------------------------------------
# Test 1: removes old settings.json entries for plugin-native hooks
# ---------------------------------------------------------------------------
echo "[1] ensure-global-hooks: removes old plugin-native hooks from settings.json"

FX1_HOME="$TMPROOT/home1"
mkdir -p "$FX1_HOME/.claude"

# Simulate an older settings.json with literal plugin-root hook commands.
cat > "$FX1_HOME/.claude/settings.json" << 'JSONEOF'
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-preflight.sh"}]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/preflight-guard.sh"}]
      }
    ]
  }
}
JSONEOF

HOME="$FX1_HOME" CLAUDE_PLUGIN_ROOT="$REPO_ROOT" python3 "$ENSURE_HOOKS" 2>/dev/null

_assert_json "plugin-native settings entries removed" \
  "$FX1_HOME/.claude/settings.json" '
import sys, json
errors = []
s = json.load(open(sys.argv[1]))
all_cmds = [
    h.get("command", "")
    for event in s.get("hooks", {}).values()
    for entry in event
    for h in entry.get("hooks", [])
]
for old in ["drift-gate.sh", "master-preflight.sh", "session-preflight.sh", "preflight-guard.sh", "${CLAUDE_PLUGIN_ROOT}"]:
    if any(old in c for c in all_cmds):
        errors.append(old + " still present in settings.json")
print("COUNT=" + str(len(errors)))
for e in errors:
    print(e)
'

# ---------------------------------------------------------------------------
# Test 2: idempotent — second run keeps settings clean
# ---------------------------------------------------------------------------
echo "[2] ensure-global-hooks: idempotent (second run keeps settings clean)"

HOME="$FX1_HOME" CLAUDE_PLUGIN_ROOT="$REPO_ROOT" python3 "$ENSURE_HOOKS" 2>/dev/null

_assert_json "settings remain free of plugin-native hook commands" \
  "$FX1_HOME/.claude/settings.json" '
import sys, json
errors = []
s = json.load(open(sys.argv[1]))
all_cmds = [
    h.get("command", "")
    for event in s.get("hooks", {}).values()
    for entry in event
    for h in entry.get("hooks", [])
]
for hook in ["drift-gate.sh", "master-preflight.sh", "session-preflight.sh", "preflight-guard.sh"]:
    if any(hook in c for c in all_cmds):
        errors.append(hook + " still present after idempotent cleanup")
print("COUNT=" + str(len(errors)))
for e in errors:
    print(e)
'

# ---------------------------------------------------------------------------
# Test 3: multi-mirror installed_plugins.json — picks scope=user, newest first
# ---------------------------------------------------------------------------
echo "[3] ensure-global-hooks: multi-mirror installed_plugins.json picks newest scope=user entry"

FX3_HOME="$TMPROOT/home3"
mkdir -p "$FX3_HOME/.claude/plugins"

# Stale install: old date, has a fake manifest with a "stale-hook.sh" required hook.
STALE_INSTALL="$TMPROOT/stale-install"
mkdir -p "$STALE_INSTALL/hooks"
cat > "$STALE_INSTALL/hooks/hooks-manifest.json" << 'JSONEOF'
{
  "schema_version": 2,
  "hooks": [
    {
      "file": "stale-hook.sh",
      "event": "SessionStart",
      "matcher": "startup",
      "required": true,
      "scope": "global",
      "command_path": "${CLAUDE_PLUGIN_ROOT}/hooks/stale-hook.sh"
    }
  ]
}
JSONEOF

# Current install: new date, points at the real repo (plugin-native hooks only).
cat > "$FX3_HOME/.claude/plugins/installed_plugins.json" << JSONEOF
{
  "plugins": {
    "sweetclaude": [
      {
        "scope": "user",
        "lastUpdated": "2026-01-01T00:00:00Z",
        "installPath": "$STALE_INSTALL",
        "version": "3.67.0"
      },
      {
        "scope": "user",
        "lastUpdated": "2026-05-12T00:00:00Z",
        "installPath": "$REPO_ROOT",
        "version": "3.68.0"
      }
    ]
  }
}
JSONEOF

cat > "$FX3_HOME/.claude/settings.json" << 'JSONEOF'
{"hooks": {}}
JSONEOF

# Run WITHOUT CLAUDE_PLUGIN_ROOT so it falls back to installed_plugins.json.
HOME="$FX3_HOME" python3 "$ENSURE_HOOKS" 2>/dev/null

_assert_json "newest entry used (plugin-native hooks not duplicated, stale hook not added)" \
  "$FX3_HOME/.claude/settings.json" '
import sys, json
errors = []
s = json.load(open(sys.argv[1]))
all_cmds = [
    h.get("command", "")
    for event in s.get("hooks", {}).values()
    for entry in event
    for h in entry.get("hooks", [])
]
for hook in ["drift-gate.sh", "master-preflight.sh"]:
    if any(hook in c for c in all_cmds):
        errors.append(hook + " duplicated into settings.json")
if any("stale-hook.sh" in c for c in all_cmds):
    errors.append("stale-hook.sh added (stale entry was used instead of newest)")
print("COUNT=" + str(len(errors)))
for e in errors:
    print(e)
'

# ---------------------------------------------------------------------------
# Test 4: non-user scope entries are ignored
# ---------------------------------------------------------------------------
echo "[4] ensure-global-hooks: non-user scope entries are ignored"

FX4_HOME="$TMPROOT/home4"
mkdir -p "$FX4_HOME/.claude/plugins"

# Only a "global" scope entry — should be ignored.
cat > "$FX4_HOME/.claude/plugins/installed_plugins.json" << JSONEOF
{
  "plugins": {
    "sweetclaude": [
      {
        "scope": "global",
        "lastUpdated": "2026-05-12T00:00:00Z",
        "installPath": "$REPO_ROOT",
        "version": "3.68.0"
      }
    ]
  }
}
JSONEOF

cat > "$FX4_HOME/.claude/settings.json" << 'JSONEOF'
{"hooks": {}}
JSONEOF

# Should exit cleanly without adding any hooks (no user-scope entry found).
HOME="$FX4_HOME" python3 "$ENSURE_HOOKS" 2>/dev/null

_assert_json "non-user scope entry ignored; settings.json unchanged" \
  "$FX4_HOME/.claude/settings.json" '
import sys, json
s = json.load(open(sys.argv[1]))
all_cmds = [
    h.get("command", "")
    for event in s.get("hooks", {}).values()
    for entry in event
    for h in entry.get("hooks", [])
]
errors = []
if any("drift-gate.sh" in c or "master-preflight.sh" in c or "stale-hook.sh" in c for c in all_cmds):
    errors.append("hooks added from non-user scope entry (should not happen)")
print("COUNT=" + str(len(errors)))
for e in errors:
    print(e)
'

# ---------------------------------------------------------------------------
echo
if [ "$FAILED" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "FAILURES: $FAILED"
  exit 1
fi
