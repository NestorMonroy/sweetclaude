#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude Large-Story Stop Guard Hook (Track C TASK-C4)
# Stop — blocks session end exactly once while a large-story workflow is
# active and non-terminal, forcing controller-rendered status into the
# conversation. Honors stop_hook_active so a deliberate second stop succeeds
# (Claude Code also hard-caps consecutive stop blocks).
#
# Protocol: block = exit 0 + {"decision":"block","reason":...}; allow = silent.

set -uo pipefail

INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
WORKFLOWS_DIR="$PROJECT_DIR/.sweetclaude/state/workflows"

if ! compgen -G "$WORKFLOWS_DIR/*.yaml" > /dev/null 2>&1; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT:-$SCRIPT_DIR/..}/scripts"

STOP_INPUT="$INPUT" STOP_PROJECT_DIR="$PROJECT_DIR" STOP_SCRIPTS_DIR="$SCRIPTS_DIR" python3 - <<'PYEOF'
import json
import os
import sys
from pathlib import Path


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


try:
    data = json.loads(os.environ["STOP_INPUT"])
    if data.get("stop_hook_active"):
        sys.exit(0)

    sys.path.insert(0, os.environ["STOP_SCRIPTS_DIR"])
    from large_story_controller import (
        _active_large_story_workflow,
        render_large_story_status,
    )

    project = Path(os.environ.get("STOP_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    project = project.expanduser().resolve(strict=False)

    active = _active_large_story_workflow(project)
    if active is None:
        sys.exit(0)
    workflow_id, state = active

    status = render_large_story_status(project_dir=project, workflow_id=workflow_id)
    if status.get("ok") and status.get("completion_claim_allowed"):
        sys.exit(0)

    phase = str(state.get("phase") or "UNKNOWN")
    summary = str(status.get("allowed_summary") or "Large-story workflow is not complete.")
    block(
        f"Large-story workflow {workflow_id} is NOT complete "
        f"(phase: {phase}; controller status: {status.get('status')}). {summary} "
        "Before stopping: render controller status with "
        "'python3 scripts/large_story_controller.py render-status' and report it "
        "verbatim to the user. Do not describe this story as done, finished, or "
        "successful. If the user intends to pause mid-story, say so explicitly and "
        "stop again — the second stop will be allowed and state will persist."
    )
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001 — workflow state exists; fail closed once
    block(
        "Large-story stop guard failed closed: could not evaluate workflow "
        f"completion ({exc}). A large-story workflow state file exists in this "
        "project. Report controller status before stopping; stop again to "
        "pause anyway."
    )
PYEOF
exit 0
