---
spdx-license: AGPL-3.0-or-later
user-invocable: false
description: "Internal bounded, evidence-gated large-story workflow."
---

!`bash ~/.claude/hooks/sweetclaude/record-event.sh skill_invoked "sweetclaude:large-story" 2>/dev/null || true`

!`cat .sweetclaude/state/session-state.yaml 2>/dev/null || echo "STATE_NOT_FOUND"`

<preflight-guard>
STOP. Before executing this skill, check: does .sweetclaude/state/phase.yaml exist in the project directory? If NO, do not proceed. Tell the user: "This project is not set up for SweetClaude. Running the pre-flight check now." Then invoke the sweetclaude master skill (Skill tool, skill: "sweetclaude:master") and run its pre-flight. Return here only after the pre-flight passes.
</preflight-guard>

# Large Story

Internal SweetClaude 4.x workflow for complete large/high-rigor story
workflows. Users start this through `/sweetclaude:go` using natural language.

This workflow is bounded, evidence-gated, and human-approved at explicit gates.
It must not delegate entrypoint authority to any other workflow.

## Scope

Use this workflow when a work item is too large or high-risk for a single
bounded `/sweetclaude:code-feature`, `/sweetclaude:code-issue`, or
`/sweetclaude:code-tdd` pass.

## Current Product Surface

This Track B surface currently supports DEFINE, DESIGN, PLAN, IMPLEMENT,
VERIFY, SHIP/closeout, final status rendering, and automated end-to-end
regression coverage. Fresh disposable execution remains blocked until the next
Track B slice.

All route, transition, status, and completion responses for this skill are
controller-owned. Do not bypass `scripts/large_story_controller.py` for
large-story status or completion language.

On start or resume, maintain large-story state in
`.sweetclaude/state/large-story.yaml` or
`.sweetclaude/state/workflows/{workflow_id}.yaml`.

Required state fields:

- `workflow_id`
- `requires_success_criteria_contract: true`
- `success_criteria_contract_path`
- `success_criteria_contract_hash`
- `criterion_ids`
- `success_criteria_ledger_path`

## Entry Gate

Before planning, design, implementation, review, release, or caucus completion
evaluation starts:

1. Define the story objective.
2. Define expected outcomes.
3. Define non-goals.
4. Create or locate a frozen `success_criteria_contract`.
5. Run `python3 scripts/success_criteria_contracts.py validate-workflow --stage define-exit`.
6. If validation fails, stop. Do not continue downstream.
7. If validation passes, store the required state fields.
8. Run `python3 scripts/large_story_controller.py design --workflow-id {workflow_id} --design-summary "{summary}"` before entering DESIGN.
9. Run `python3 scripts/large_story_controller.py plan --workflow-id {workflow_id} --plan-summary "{summary}"` before entering PLAN.
10. Run `python3 scripts/large_story_controller.py implement --workflow-id {workflow_id} --implementation-summary "{summary}"` before entering IMPLEMENT.
11. Run `python3 scripts/large_story_controller.py verify --workflow-id {workflow_id}` before entering VERIFY.
12. Run `python3 scripts/large_story_controller.py ship --workflow-id {workflow_id}` before entering SHIP.

Do not enter terminal review or claim product readiness yet. If the user asks
for final workflow status after SHIP, run:

```bash
python3 scripts/large_story_controller.py finalize --workflow-id {workflow_id}
```

Then report the controller result. Do not continue around it.

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

Do not say "all success criteria pass", "story complete", "done", or equivalent
large-story completion language unless the controller returns completion
allowed.

No review, caucus, verification, release, or completion step may add completion
criteria. New concerns route to backlog, amendment request, split story, or
human escalation.
