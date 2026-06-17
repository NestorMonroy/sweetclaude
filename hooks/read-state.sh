#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude state reader for skill bang-command preprocessing.
# Emits a state file's contents, or a sentinel if it is absent/unreadable.
# Exists so skills can pre-load state with a SINGLE, non-compound `!`...``
# command — compound bang commands (||, &&, |) hard-error and halt the skill
# under default permissions. Invoked via ${CLAUDE_SKILL_DIR}/../../hooks/ so the
# path resolves on fresh installs regardless of the current working directory.
# Usage: read-state.sh <state-stem> [sentinel]
#   read-state.sh session-state
#   read-state.sh sweetclaude SC_YAML_NOT_FOUND

STEM="${1:-session-state}"
SENTINEL="${2:-STATE_NOT_FOUND}"
FILE=".sweetclaude/state/${STEM}.yaml"

if [ -f "$FILE" ] && cat "$FILE" 2>/dev/null; then
    :
else
    printf '%s\n' "$SENTINEL"
fi

exit 0
