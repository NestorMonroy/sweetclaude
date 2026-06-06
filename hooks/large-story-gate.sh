#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude Large-Story Gate Hook (Track C TASK-C2)
# PreToolUse Write|Edit|NotebookEdit|Bash — deterministic deny outside the
# controller-permitted phase. Policy lives in scripts/large_story_controller.py
# gate_tool_use; this script is a protocol adapter.
#
# Protocol (verified 2026-06-06, see 13-hook-protocol-reference.md):
#   deny  = exit 0 + {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#           "permissionDecision":"deny","permissionDecisionReason":...}}
#   allow = exit 0, no output
# Fail-safe: no active large-story workflow -> allow on any error.
#            active workflow -> fail closed (deny) on any error.

set -uo pipefail

INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
WORKFLOWS_DIR="$PROJECT_DIR/.sweetclaude/state/workflows"

# Fast path: no large-story workflow state anywhere -> not our concern.
if ! compgen -G "$WORKFLOWS_DIR/*.yaml" > /dev/null 2>&1; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT:-$SCRIPT_DIR/..}/scripts"

GATE_INPUT="$INPUT" GATE_PROJECT_DIR="$PROJECT_DIR" GATE_SCRIPTS_DIR="$SCRIPTS_DIR" python3 - <<'PYEOF'
import json
import os
import sys


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


try:
    sys.path.insert(0, os.environ["GATE_SCRIPTS_DIR"])
    from large_story_controller import gate_tool_use

    data = json.loads(os.environ["GATE_INPUT"])
    tool = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    command = tool_input.get("command")
    project = os.environ.get("GATE_PROJECT_DIR") or data.get("cwd") or os.getcwd()

    result = gate_tool_use(
        project_dir=project,
        tool=tool,
        file_path=file_path,
        command=command,
    )
except BaseException as exc:  # noqa: BLE001 — fail closed on ANY failure,
    # including SystemExit from controller import guards. The fast path
    # already proved a large-story workflow exists.
    deny(
        "Large-story gate failed closed: the gate could not evaluate this tool "
        f"use while a large-story workflow is active ({exc}). Run "
        "'python3 scripts/large_story_controller.py render-status' and report "
        "the controller status."
    )

if not result.get("allow"):
    deny(str(result.get("reason") or "Large-story gate denied this tool use."))
PYEOF
exit 0
