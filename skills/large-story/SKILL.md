---
spdx-license: AGPL-3.0-or-later
user-invocable: false
description: "Internal bounded, evidence-gated large-story workflow."
---

!`bash ~/.claude/hooks/sweetclaude/record-event.sh skill_invoked "sweetclaude:large-story"`

!`bash ~/.claude/hooks/sweetclaude/read-state.sh session-state`

<preflight-guard>
STOP. Before executing this skill, check: does .sweetclaude/state/phase.yaml exist in the project directory? If NO, do not proceed. Tell the user: "This project is not set up for SweetClaude. Running the pre-flight check now." Then invoke the sweetclaude master skill (Skill tool, skill: "sweetclaude:master") and run its pre-flight. Return here only after the pre-flight passes.
</preflight-guard>

# Large Story

Internal SweetClaude 4.x workflow for complete large/high-rigor story
workflows. Users start this through `/sweetclaude:go` using natural language.

This skill is a thin phase runner around `scripts/large_story_controller.py`.
The controller and the large-story hooks — not this document — are the
enforcement layer. The hooks deterministically deny project writes outside a
controller-entered IMPLEMENT phase, record implementation evidence, and block
session end while the workflow is non-terminal. You cannot bypass them; do not
try.

## Scope

Use this workflow when a work item is too large or high-risk for a single
bounded `/sweetclaude:code-feature`, `/sweetclaude:code-issue`, or
`/sweetclaude:code-tdd` pass.

This workflow runs DEFINE, DESIGN, PLAN, IMPLEMENT, VERIFY, SHIP/closeout, and
final status rendering, with controller-enforced phase gates and hook-verified
enforcement (the gate, evidence recorder, and stop guard).

## Controller Path Resolution (do this first)

The controller ships with the plugin, not with the target project. Resolve it
from this skill's base directory (shown at the top of this skill's context):

```
CONTROLLER = {skill base directory}/../../scripts/large_story_controller.py
CONTRACTS  = {skill base directory}/../../scripts/success_criteria_contracts.py
```

Verify both files exist before starting. Every controller command below is
written as `python3 scripts/large_story_controller.py ...` for brevity — always
invoke it as `python3 "$CONTROLLER" --project-dir . ...` with the resolved
absolute path. Never assume the target project contains a `scripts/`
directory.

## The Runner Loop

For every phase, follow exactly this loop. No step may be reordered, skipped,
or replaced by your own judgment:

1. Read state: `.sweetclaude/state/workflows/{workflow_id}.yaml`.
2. Call the controller command for the transition you need.
3. Parse the controller JSON.
4. If `ok` is false: STOP. Report only the controller's `message` and
   `code` to the user. Do not work around the block. Do not retry with
   different arguments to make it pass.
5. If `ok` is true: perform exactly the phase work described below — nothing
   more.
6. Immediately call the next controller gate when the phase work is done.

Never summarize success from your own observation. Never write phase state
directly — the controller is the single writer (the gate hook denies direct
writes to `.sweetclaude/state/` and `.sweetclaude/reports/`). Never treat
screenshots or app behavior as completion evidence unless the controller has
entered them into the ledger.

## Phase Sequence

### DEFINE

1. Define the story objective with the user.
2. Define expected outcomes.
3. Define non-goals.
4. Create or locate a frozen `success_criteria_contract` at
   `.sweetclaude/contracts/success-criteria-contract.yaml`. Do NOT hand-author
   the YAML — generate a schema-valid skeleton:
   `python3 "$CONTRACTS" init-contract --project-dir . --story-id {workflow_id} --title "{title}" --criteria {n}`.
   Then replace every PLACEHOLDER with the agreed objective, outcomes,
   non-goals, statements, and binary predicates. Evidence paths and enum
   fields are pre-filled — do not change them. Criteria must be binary and
   controller- or test-measurable; human-judged and terminal-review criteria
   are rejected on this surface — route those concerns to backlog.
5. Freeze it: `python3 "$CONTRACTS" freeze-contract --project-dir .`
   (computes and writes the contract hash — never compute the hash yourself).
   Run `python3 scripts/success_criteria_contracts.py validate-workflow --stage define-exit`.
6. If validation fails, stop. Do not continue downstream.
7. If validation passes, initialize controller-owned workflow state:
   `python3 scripts/large_story_controller.py init --workflow-id {workflow_id}`.
   Do not write the workflow state file yourself.

After `init`, the contract is frozen and human-gated: any attempt to edit it
raises an approval prompt that only the user can answer, in every permission
mode. If the user approves an amendment, re-run
freeze-contract and init to rebind the workflow to the new hash — all phase
artifacts must then be regenerated through the controller.

### DESIGN → PLAN → ENFORCEMENT CHECK → IMPLEMENT

- Enter DESIGN: `python3 scripts/large_story_controller.py design --workflow-id {workflow_id} --design-summary "{summary}"`
- Enter PLAN: `python3 scripts/large_story_controller.py plan --workflow-id {workflow_id} --plan-summary "{summary}"`

**Before IMPLEMENT, verify enforcement is live.** The controller blocks
IMPLEMENT until this passes — it confirms the gate hook is actually loaded, so
the workflow never runs unprotected without anyone noticing:

1. `python3 scripts/large_story_controller.py enforcement-probe --arm --workflow-id {workflow_id}`
2. Write a one-line file at `.sweetclaude/.enforcement-control` (the gate
   allows this — it should succeed).
3. Attempt a Write at `.sweetclaude/state/workflows/.enforcement-canary` (the
   gate MUST deny this — the write should be blocked).
4. `python3 scripts/large_story_controller.py enforcement-probe --check --workflow-id {workflow_id}`
5. If `verified: false`, STOP and report the controller's reason to the user.
   Do not proceed to IMPLEMENT — enforcement is not active and the evidence
   gate cannot be trusted. (Usual cause: hooks not loaded; see the large-story
   dev-testing notes.)

- Enter IMPLEMENT: `python3 scripts/large_story_controller.py implement --workflow-id {workflow_id} --implementation-summary "{summary}"`

Project files can only be created or modified after the IMPLEMENT entry
succeeds — the gate hook denies them in every other phase. Implementation
evidence (touched files, commands) is recorded automatically by the evidence
hook; you do not need to and must not fabricate it.

### VERIFY

Run `python3 scripts/large_story_controller.py verify --workflow-id {workflow_id}`
with `--criterion-result-json` carrying the measured result for each frozen
criterion. The controller regenerates the implementation record from observed
evidence, writes the canonical ledger at
`.sweetclaude/reports/success-criteria-ledger.json`, and fails closed if any
criterion lacks evidence or if no implementation evidence was observed.

### SHIP

Run `python3 scripts/large_story_controller.py ship --workflow-id {workflow_id}`.
Closeout is written by the controller only after completion validation passes.

## Completion Authority

Completion is valid only when the SHIP/closeout controller exists, runs, and
accepts a `success-criteria-ledger.json` that evaluates every frozen criterion
and reports `all_success_criteria_passed == true`.

Before any final large-story status or completion response, run:

```bash
python3 scripts/large_story_controller.py finalize
```

If completion is not being requested but status is being rendered, run:

```bash
python3 scripts/large_story_controller.py render-status
```

Then report the controller result. Do not continue around it. Do not say "all
success criteria pass", "story complete", "done", or equivalent large-story
completion language unless the controller returns completion allowed. The stop
guard hook will block session end and re-inject controller status if the
workflow is left non-terminal.

No review, caucus, verification, release, or completion step may add completion
criteria. New concerns route to backlog, amendment request, split story, or
human escalation.
