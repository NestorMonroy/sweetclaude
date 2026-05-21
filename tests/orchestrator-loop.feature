Feature: Orchestrator main loop
  The orchestrator loop reads workflow state, determines the next step,
  executes it (via subagent or direct action), validates output, routes
  to the next step, and writes state. It yields structured YieldPoints
  when user interaction is needed.

  # --- Main loop flow ---

  Scenario: Loop executes a single step and advances
    Given a workflow at step "activate" with no gate
    And the step has no input artifacts and no output artifact
    When the loop runs one iteration
    Then the state file shows current_step_id as the next step
    And "activate" appears in completed_steps

  Scenario: Loop re-reads state from disk on every iteration
    Given a workflow at step "activate"
    When the state file is modified externally between iterations
    Then the loop uses the modified state, not a cached copy

  Scenario: Loop terminates on COMPLETE
    Given a workflow with current_step_id "COMPLETE"
    When the loop runs
    Then it yields a YieldPoint with reason "complete"

  Scenario: Loop terminates on HALTED
    Given a workflow with current_step_id "HALTED"
    When the loop runs
    Then it yields a YieldPoint with reason "halted"

  # --- Gate enforcement ---

  Scenario: Soft gate yields for approval in collaborative mode
    Given a workflow at step "spec" with gate "user_approval"
    And deference_level is "collaborative"
    When the loop reaches the gate
    Then it yields a YieldPoint with reason "gate"
    And the yield payload contains gate_type "user_approval"

  Scenario: Soft gate auto-advances in autonomous mode with no critical findings
    Given a workflow at step "spec" with gate "user_approval"
    And deference_level is "autonomous"
    And the previous step produced no critical findings
    When the loop reaches the gate
    Then it does not yield — it auto-advances past the gate

  Scenario: Hard gate always yields regardless of deference level
    Given a workflow at step "spec" with gate "user_approval_hard"
    And deference_level is "autonomous"
    When the loop reaches the gate
    Then it yields a YieldPoint with reason "gate"

  Scenario: Gate passage is persisted to disk before execution continues
    Given a workflow at step "spec" with gate "user_approval"
    And the loop yields a gate YieldPoint
    When the user approves and resume_loop is called
    Then record_gate_passage is written to state on disk
    And the state file shows the gate in gates_passed before step execution begins

  Scenario: Iterate gate option routes back to input producer
    Given a workflow at step "implement" with gate "user_approval"
    And "implement" has input_artifacts ["spec_file"]
    And "spec" produces output_artifact "spec_file"
    When the user selects "iterate" at the gate
    Then current_step_id is set to "spec"

  # --- Subagent invocation ---

  Scenario: Agent step builds prompt with context file paths
    Given a workflow at step "spec" with agent "spec-writer"
    And input artifacts resolve to ["/project/docs/story.md"]
    When the loop executes the step
    Then the agent prompt contains the file path "/project/docs/story.md"
    And the agent prompt specifies the output path

  Scenario: Agent step creates output directory before invocation
    Given a workflow at step "spec" with agent "spec-writer"
    And the output directory does not exist
    When the loop executes the step
    Then the output directory is created before the agent runs

  Scenario: Steps with agent null dispatch via orchestrator_actions
    Given a workflow at step "verify" with agent null and action "verify_artifacts"
    When the loop executes the step
    Then orchestrator_actions.ACTIONS["verify_artifacts"] is called

  # --- Failure handling ---

  Scenario: Missing output artifact yields failure
    Given a workflow at step "spec" with agent "spec-writer"
    And the agent produces no output file
    When exit checks run
    Then the loop yields a YieldPoint with reason "failure"
    And the yield payload describes the missing artifact

  Scenario: Empty output artifact yields failure
    Given a workflow at step "spec" with agent "spec-writer"
    And the agent produces an empty output file
    When exit checks run
    Then the loop yields a YieldPoint with reason "failure"

  Scenario: Retry decision re-runs the step
    Given a failure yield at step "spec"
    When resume_loop is called with action "retry"
    Then current_step_id remains "spec"
    And stale output is cleaned before re-execution

  Scenario: Skip decision advances past the failed step
    Given a failure yield at step "spec"
    When resume_loop is called with action "skip"
    Then current_step_id advances to the next step
    And the skip reason is recorded in state

  Scenario: Abort decision halts the workflow
    Given a failure yield at step "spec"
    When resume_loop is called with action "abort"
    Then the state file shows status "HALTED"
    And a checkpoint message explains the abort

  # --- Crash recovery ---

  Scenario: Active workflow detected on entry
    Given an active workflow state file exists for "STORY-025"
    When run_loop is called for "STORY-025"
    Then the loop detects the existing state
    And it can resume from the last checkpoint

  Scenario: Stale output artifact cleaned before step re-run
    Given a workflow at step "spec" with a stale output artifact from a prior run
    When the loop executes the step
    Then the stale artifact is deleted before the agent runs

  Scenario: Resume appends a new session entry
    Given a workflow that was interrupted mid-session
    When resume_loop is called
    Then a new session entry is appended to state.sessions

  # --- Configuration ---

  Scenario: Default max iterations from config
    Given config/orchestrator-defaults.yaml has iteration_limits.default_max = 3
    And a step with no explicit max_iterations
    When the loop tracks iterations for a backward step
    Then it uses 3 as the max

  Scenario: Per-step max_iterations overrides config default
    Given config/orchestrator-defaults.yaml has iteration_limits.default_max = 3
    And a step with max_iterations = 5
    When the loop tracks iterations for a backward step
    Then it uses 5 as the max

  Scenario: Output dir read from config
    Given config/orchestrator-defaults.yaml has paths.output_dir = ".sweetclaude/workflows"
    When an agent prompt is built
    Then the output path uses ".sweetclaude/workflows" as the base directory

  # --- Session state integration ---

  Scenario: Workflow start sets orchestrated flag
    Given sweetclaude.yaml has work.active.id = "STORY-025"
    When run_loop starts a new workflow
    Then sweetclaude.yaml shows orchestrated = true
    And sweetclaude.yaml shows workflow_state_file path

  Scenario: Workflow completion clears orchestrated flag
    Given a workflow reaches COMPLETE
    When the loop yields "complete"
    Then sweetclaude.yaml work.active is cleared
    And work_history has an entry with result "complete"

  Scenario: Workflow abort clears orchestrated flag
    Given a workflow is aborted
    When the loop yields "halted"
    Then sweetclaude.yaml work.active is cleared
    And work_history has an entry with result "halted"

  Scenario: Phase update uses next step's phase after routing
    Given a workflow at step "spec" (phase DEFINE) that routes backward to "activate" (phase ACTIVATION)
    When the step completes and routing resolves
    Then sweetclaude.yaml work.active.phase is updated to "ACTIVATION", not "DEFINE"

  Scenario: Completion validates work.active.id before clearing
    Given sweetclaude.yaml work.active.id was changed externally to "STORY-999"
    And the loop is completing workflow "STORY-025"
    When the loop attempts to clear sweetclaude.yaml
    Then it does not modify sweetclaude.yaml because the id does not match

  # --- Escalation handling ---

  Scenario: Escalation condition triggers yield
    Given a workflow at step "review" with escalation {signal: "critical", action: "pause"}
    And the agent output signal is "critical"
    When the loop checks escalation
    Then it yields a YieldPoint with reason "escalation"
    And the yield payload contains the escalation details

  # --- Pre-step cleanup ---

  Scenario: Stale artifact deleted before step execution
    Given a workflow at step "spec" with output_artifact "spec_file"
    And a stale file exists at the expected output path
    When the loop begins step execution
    Then the stale file is deleted before the agent runs

  Scenario: Deletion validates containment
    Given a workflow with a manipulated output path outside the project
    When pre-step cleanup attempts to delete the file
    Then it raises ValueError for path containment violation

  # --- Observability ---

  Scenario: Checkpoint written after each step
    Given a workflow at step "activate"
    When the step completes successfully
    Then state.checkpoint describes what was completed
    And state.checkpoint_at is updated

  # --- Routing and iteration ---

  Scenario: Output signal validated against routing keys
    Given a step with routing {"clean": "continue", "issues": "fix"}
    And the agent output signal is "unknown_signal"
    When the loop processes the signal
    Then it yields a failure (unrecognized signal)

  Scenario: Missing signal on routed step yields failure
    Given a step with routing {"clean": "continue", "issues": "fix"}
    And the agent produces output with no signal
    When the loop checks for routing
    Then it yields a failure (expected signal but got none)

  Scenario: Backward routing uses strict less-than for detection
    Given a step at index 3 that routes to itself (index 3)
    When the loop checks for backward movement
    Then it does not treat this as a backward step

  Scenario: Backward routing to earlier step increments iteration
    Given a step at index 3 that routes to step at index 1
    When the loop checks for backward movement
    Then it increments the iteration counter for this loop

  Scenario: Max iterations reached yields for user decision
    Given a backward loop that has reached max_iterations
    When the loop detects max iterations
    Then it yields a YieldPoint with reason "max_iterations"

  # --- Re-entry guards ---

  Scenario: resume_loop rejects terminal workflow state
    Given a workflow with status "HALTED"
    When resume_loop is called
    Then it raises ValueError

  Scenario: resume_loop rejects invalid action
    Given a valid active workflow
    When resume_loop is called with action "invalid_action"
    Then it raises ValueError

  Scenario: resume_loop writes decision to state before continuing
    Given a gate yield at step "spec"
    When resume_loop is called with action "approve"
    Then the decision is written to the state file before the loop continues

  # --- Validation at load time ---

  Scenario: Step IDs validated against safe pattern at template load
    Given a workflow template with step id "../../malicious"
    When the template is loaded
    Then it raises ValueError for invalid step id

  Scenario: Subagent type validated against allowlist
    Given a step with subagent_type "dangerous_type"
    When an agent prompt is built
    Then it raises ValueError for invalid subagent_type
