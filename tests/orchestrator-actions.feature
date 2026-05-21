Feature: Orchestrator actions registry
  The orchestrator actions module provides a pluggable registry for
  steps executed directly by the orchestrator (agent: null).

  Scenario: Register decorator adds action to ACTIONS dict
    Given a function decorated with @register("my_action")
    Then ACTIONS["my_action"] is the decorated function

  Scenario: verify_artifacts action checks all input artifacts exist
    Given a step with input_artifacts ["spec_file", "story_file"]
    And all artifacts exist on disk
    When verify_artifacts is called
    Then it returns success

  Scenario: verify_artifacts action fails when artifact missing
    Given a step with input_artifacts ["spec_file"]
    And spec_file does not exist on disk
    When verify_artifacts is called
    Then it returns failure with the missing artifact name

  Scenario: run_tests action executes test command
    Given a step with action "run_tests"
    When run_tests is called
    Then it executes the configured test command

  Scenario: checkpoint_only action writes checkpoint and succeeds
    Given a step with action "checkpoint_only"
    When checkpoint_only is called
    Then it writes a checkpoint message to state
    And it returns success

  Scenario: Unknown action name raises ValueError
    Given a step with action "nonexistent_action"
    When the orchestrator dispatches the action
    Then it raises ValueError for unregistered action
