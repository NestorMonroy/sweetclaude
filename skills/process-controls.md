# Process Controls For Autonomous Work

These controls apply to any SweetClaude skill path that can spawn subagents,
run caucuses, or enter correction loops.

## Required Ledger

Before spawning a caucus, test writer, implementer, or autonomous reviewer,
create or update a process-control ledger:

- Standard workflows: `.sweetclaude/state/process-control-ledger.yaml`
- John Wick: `process_control` in `.sweetclaude/state/john-wick.yaml`

The ledger must record:

- workflow or story id;
- current step;
- subagent budget approval;
- maximum caucus rounds in the current budget window;
- maximum reviewer agents in the current budget window;
- caucus rounds used;
- reviewer agents used;
- blocking caucus failures;
- WLF or process-failure count;
- adversarial pass-state bypass count;
- human approvals for extra budget, contract reopen, or resume after stop;
- current stop disposition, if any.

## Default Limits

Without explicit user approval, the defaults are:

- one three-reviewer caucus per budget window;
- maximum two caucus rounds for the same story or step;
- maximum one blocking caucus failure before contract reopen or user decision;
- maximum two WLF/process-failure records for the same story or step before
  contract reopen or user decision;
- maximum one adversarial pass-state bypass before human decision;
- no background implementer or reviewer dispatch while a process stop is active.

## Hard Stops

Stop immediately and ask the user before more subagent/caucus/patch work when:

- caucus rounds exceed the approved budget;
- reviewer-agent count exceeds the approved budget;
- a second blocking caucus failure occurs for the same story or step;
- WLF/process-failure count exceeds the approved limit;
- repeated adversarial pass-state bypasses are found;
- the story or step contract keeps expanding during correction;
- failure recording becomes part of a patch-test-recaucus loop;
- the process-control ledger is missing, stale, or contradictory.

## Resume Requirements

Resume after a hard stop requires all of:

- explicit human approval;
- a fresh budget window;
- a revised story/step contract or split-story plan when drift repeated;
- current process-control ledger;
- a recorded stop disposition explaining why continuation is bounded.

## Caucus Rules

Caucus/reviewer agents are read-only judges unless the user explicitly assigns
a separate write task. Their output may not mark work complete. A caucus may
answer only the approved question against the approved contract.

If a caucus finds a blocker, the next correction must either:

- tighten a deterministic guard, fixture, schema, hook, or controller check; or
- classify the issue as human-review-only with rationale; or
- stop for contract reopen.

Do not spawn another caucus merely because the previous caucus found a new
problem. The process-control ledger must show available budget and stop-rule
clearance first.
