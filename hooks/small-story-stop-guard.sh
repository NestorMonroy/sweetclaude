#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SweetClaude Small-Story Stop Guard Hook (Track C TASK-C4)
# Stop — blocks session end while a small-story workflow is active and
# non-terminal, surfacing a one-line status summary. A deliberate second stop
# (stop_hook_active) confirms an intentional pause and is recorded to disk,
# fingerprinted to the workflow's material state; later turns then stop
# silently until the story progresses (re-arming one reminder) or goes
# terminal. This prevents the block re-firing on every turn of a paused story.
#
# Protocol: block = exit 0 + {"decision":"block","reason":...}; allow = silent.

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

STOP_INPUT_FILE="$INPUT_FILE" STOP_PROJECT_DIR="$PROJECT_DIR" STOP_SCRIPTS_DIR="$SCRIPTS_DIR" python3 - <<'PYEOF'
import json
import os
import sys
from pathlib import Path


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


with open(os.environ["STOP_INPUT_FILE"], encoding="utf-8") as handle:
    data = json.load(handle)
stop_hook_active = bool(data.get("stop_hook_active"))

try:
    sys.path.insert(0, os.environ["STOP_SCRIPTS_DIR"])
    from small_story_controller import (
        _active_small_story_workflow,
        render_small_story_status,
    )
    from story_stop_ack import compute_fingerprint, read_ack_fingerprint, write_ack

    project = Path(os.environ.get("STOP_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    project = project.expanduser().resolve(strict=False)

    active = _active_small_story_workflow(project)
    if active is None:
        sys.exit(0)
    workflow_id, state = active

    status = render_small_story_status(project_dir=project, workflow_id=workflow_id)
    if status.get("ok") and status.get("completion_claim_allowed"):
        sys.exit(0)

    phase = str(state.get("phase") or "UNKNOWN")
    fingerprint = compute_fingerprint(phase, status)

    # A deliberate second stop within the same turn = the user confirmed the
    # pause. Record it so later turns stay silent until the story progresses.
    if stop_hook_active:
        try:
            write_ack(project, workflow_id, fingerprint)
        except BaseException:  # noqa: BLE001 — never block a deliberate pause
            pass
        sys.exit(0)

    # Pause already acknowledged and nothing material has changed since.
    if read_ack_fingerprint(project, workflow_id) == fingerprint:
        sys.exit(0)

    summary = str(status.get("allowed_summary") or "Small-story workflow is not complete.")
    block(
        f"Small-story workflow {workflow_id} is still open and NOT complete "
        f"(phase: {phase}). {summary} Tell the user in one plain sentence that this "
        "story is paused mid-flight — not done, not failed — and that progress is "
        "saved. Do not paste raw controller JSON or describe the story as done, "
        "finished, or successful. Then stop again to confirm the pause; the guard "
        "will stay silent about it on later turns until the story progresses or closes."
    )
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001 — workflow state exists; fail closed once
    if stop_hook_active:
        # A deliberate pause is always honored, even if evaluation failed.
        sys.exit(0)
    block(
        "Small-story stop guard failed closed: could not evaluate workflow "
        f"completion ({exc}). A small-story workflow state file exists in this "
        "project. Summarize the status in one line before stopping; stop again to "
        "pause anyway."
    )
PYEOF
exit 0
