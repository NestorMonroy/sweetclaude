---
spdx-license: AGPL-3.0-or-later
user-invocable: true
description: "Recover or unblock SweetClaude projects left in bad update, migration, doctor, or repair states."
---

!`bash ~/.claude/hooks/sweetclaude/record-event.sh skill_invoked "sweetclaude:recover" 2>/dev/null || true`

# SweetClaude Recover

Recover or unblock a SweetClaude project that was left in a bad update,
migration, doctor, or repair state.

This skill is a thin orchestrator. Diagnosis, planning, snapshotting,
execution, verification, resume, rollback, and report generation are handled by
`scripts/recovery/recover_project.py`. Do not manually edit project files from
this skill.

## Step 1: Locate The Recovery Script

```bash
SCRIPT=~/.claude/scripts/sweetclaude/recovery/recover_project.py
if [ ! -f "$SCRIPT" ]; then
  SCRIPT=$(find ~/.claude/plugins/cache/sweetclaude -type f -path '*/scripts/recovery/recover_project.py' 2>/dev/null | head -1)
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  echo "ERROR: recover_project.py not found. Run /sweetclaude:update first."
  exit 1
fi
```

If the script is missing, stop. Do not attempt an ad hoc repair.

## Step 2: Resume Or Roll Back When Requested

If the user explicitly asks to resume an interrupted recovery and provides a
run directory, run:

```bash
python3 "$SCRIPT" resume --run-dir "<run-dir>" --pretty
```

If the user explicitly asks to roll back and provides a run directory, run:

```bash
python3 "$SCRIPT" rollback --run-dir "<run-dir>" --pretty
```

Summarize `status`, `report_path`, and any failed verification checks. Stop
after resume or rollback unless the user asks for another action.

## Step 3: Diagnose

```bash
python3 "$SCRIPT" diagnose --project-dir . --pretty
```

Parse the JSON output.

If diagnosis fails or is not JSON, print:
> Recovery diagnosis failed. Run `python3 "$SCRIPT" diagnose --project-dir . --pretty` manually to see the error.

Stop.

If `recovery_route` is `no-recovery-needed`, print:
> No SweetClaude recovery action is currently needed.

Stop.

If `can_plan_recovery` is false, summarize the blocking factors and print:
> This project needs manual review before automated recovery can run.

Stop. Do not mutate files.

## Step 4: Plan

```bash
python3 "$SCRIPT" plan --project-dir . --pretty
```

Parse the JSON output and render:

- recovery route
- failure classes
- blocked actions
- snapshot paths
- planned operations
- verification checks

If `can_execute_after_snapshot` is false, stop after presenting the plan.

## Step 5: Approval Gate

Ask the user before execution:

> SweetClaude can execute this recovery plan now. It will create a snapshot
> first, then apply only the manifest operations above. Product artifacts are
> not supposed to change for this recovery route. Proceed?

Options:

1. `Run recovery` - Execute the manifest-backed recovery now.
2. `Stop` - Leave the project unchanged.

If the user chooses `Stop`, stop. Do not mutate files.

## Step 6: Execute

```bash
python3 "$SCRIPT" execute --project-dir . --approve --pretty
```

Parse the JSON output and render:

- status
- run directory
- report path
- snapshot file count
- failed verification checks, if any
- rollback command
- `.gitignore` reminder: recovery run directories contain snapshots and
  should stay out of source control. If the run directory appears in git
  status, add `.sweetclaude/state/recovery-runs/` to the project `.gitignore`.

If execution exits non-zero, look for the latest run directory under
`.sweetclaude/state/recovery-runs/`, then tell the user to use
`/sweetclaude:recover` with that run directory to resume or roll back.

## Safety Rules

- Never run `sweetclaude:migrate` from this skill.
- Never move, rename, delete, or normalize product artifacts manually.
- Never bypass the recovery script's `--approve` gate.
- Never continue after failed verification without reporting the run directory
  and recovery report path.
- Unknown or unplannable states must fail closed with the diagnosis output.
