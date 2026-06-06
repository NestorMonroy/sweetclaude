#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude Large-Story Evidence Hook (Track C TASK-C3)
# PostToolUse Write|Edit|NotebookEdit|Bash — appends harness-observed
# implementation evidence to the controller-owned evidence log during
# IMPLEMENT. Never blocks; missing evidence fails closed later at VERIFY
# (GUARD-IMPLEMENT-EVIDENCE-NONEMPTY).

set -uo pipefail

INPUT_FILE=$(mktemp "${TMPDIR:-/tmp}/sc-ls-hook.XXXXXX")
trap 'rm -f "$INPUT_FILE"' EXIT
cat > "$INPUT_FILE"

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
WORKFLOWS_DIR="$PROJECT_DIR/.sweetclaude/state/workflows"

if ! compgen -G "$WORKFLOWS_DIR/*.yaml" > /dev/null 2>&1; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT:-$SCRIPT_DIR/..}/scripts"

EVIDENCE_INPUT_FILE="$INPUT_FILE" EVIDENCE_PROJECT_DIR="$PROJECT_DIR" EVIDENCE_SCRIPTS_DIR="$SCRIPTS_DIR" python3 - <<'PYEOF' || true
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["EVIDENCE_SCRIPTS_DIR"])
from large_story_controller import (
    _active_large_story_workflow,
    record_evidence,
)

CONTROLLER_SCRIPT_TOKENS = (
    "large_story_controller.py",
    "success_criteria_contracts.py",
)

with open(os.environ["EVIDENCE_INPUT_FILE"], encoding="utf-8") as handle:
    data = json.load(handle)
tool = str(data.get("tool_name") or "")
tool_input = data.get("tool_input") or {}
file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
command = tool_input.get("command")
project = Path(os.environ.get("EVIDENCE_PROJECT_DIR") or data.get("cwd") or os.getcwd())

active = _active_large_story_workflow(project.expanduser().resolve(strict=False))
if active is None:
    sys.exit(0)
workflow_id, state = active
if str(state.get("phase") or "") != "IMPLEMENT":
    sys.exit(0)

if command and any(token in command for token in CONTROLLER_SCRIPT_TOKENS):
    sys.exit(0)
if file_path and ".sweetclaude" in Path(file_path).parts:
    sys.exit(0)
if file_path and str(file_path).startswith(".sweetclaude/"):
    sys.exit(0)
if not file_path and not command:
    sys.exit(0)

record_evidence(
    project_dir=project,
    tool=tool,
    file_path=file_path,
    command=command,
    workflow_id=workflow_id,
)
PYEOF
exit 0
