Feature: Doctor config_compat checks
  The check_config_compat function validates that Claude settings and instruction
  files are compatible with SweetClaude. Checks: F1 (allowedTools missing required
  tools), F2 (non-SC hooks on test files), F3 (direct test runner in hooks),
  F4 (skip-hooks instructions), W1-W4 (conflicting instructions), I1-I2
  (duplicate rules already covered by SweetClaude).

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no config_compat findings
    When check_config_compat runs against the project state
    Then the result contains 0 findings

  # --- F1: allowedTools missing required tools ---

  Scenario: Global settings missing Agent from allowedTools produces error
    Given global settings has allowedTools excluding "Agent"
    When check_config_compat runs against the project state
    Then the findings include id "config-compat:F1:~/.claude/settings.json:Agent"
    And the finding with id "config-compat:F1:~/.claude/settings.json:Agent" has severity "error"
    And the finding with id "config-compat:F1:~/.claude/settings.json:Agent" has fix_type "prompted"

  Scenario: Global settings missing Bash from allowedTools produces error
    Given global settings has allowedTools excluding "Bash"
    When check_config_compat runs against the project state
    Then the findings include id "config-compat:F1:~/.claude/settings.json:Bash"

  Scenario: Global settings missing Write from allowedTools produces error
    Given global settings has allowedTools excluding "Write"
    When check_config_compat runs against the project state
    Then the findings include id "config-compat:F1:~/.claude/settings.json:Write"

  Scenario: Local settings missing required tool produces error
    Given local settings has allowedTools excluding "Agent"
    When check_config_compat runs against the project state
    Then the findings include id "config-compat:F1:.claude/settings.local.json:Agent"

  Scenario: AllowedTools containing all required tools produces no F1 finding
    Given global settings has allowedTools including Agent, Bash, and Write
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F1"

  Scenario: No allowedTools key at all produces no F1 finding
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F1"

  Scenario: Empty allowedTools list produces F1 for all three required tools
    Given global settings has allowedTools as empty list
    When check_config_compat runs against the project state
    Then the findings include id "config-compat:F1:~/.claude/settings.json:Agent"
    And the findings include id "config-compat:F1:~/.claude/settings.json:Bash"
    And the findings include id "config-compat:F1:~/.claude/settings.json:Write"

  # --- F2: non-SweetClaude hooks on test files ---

  Scenario: Non-SC hook targeting test files produces error
    Given global settings has a hook with matcher "test" and external command "run-linter"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F2"
    And the first F2 finding has severity "error"

  Scenario: Hook targeting test files with sweetclaude command is not flagged
    Given global settings has a hook with matcher "test" and command containing "sweetclaude"
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F2"

  Scenario: Hook targeting test files with plugin root variable is not flagged
    Given global settings has a hook with matcher "test" and command containing "${CLAUDE_PLUGIN_ROOT}"
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F2"

  Scenario: Hook targeting spec files produces F2 error
    Given global settings has a hook with matcher "spec" and external command "run-linter"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F2"

  Scenario: Hook not targeting test/spec files is not flagged as F2
    Given global settings has a hook with matcher "src" and external command "run-linter"
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F2"

  # --- F3: direct test runner in hooks ---

  Scenario: Hook command containing "pytest" produces F3 error
    Given global settings has a hook with command "pytest tests/"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F3"
    And the first F3 finding has severity "error"

  Scenario: Hook command containing "npm test" produces F3 error
    Given global settings has a hook with command "npm test"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F3"

  Scenario: Hook command containing "cargo test" produces F3 error
    Given global settings has a hook with command "cargo test --release"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F3"

  Scenario: Hook command containing "jest " with trailing space produces F3 error
    Given global settings has a hook with command "jest --coverage"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F3"

  Scenario: Hook command containing "go test" produces F3 error
    Given global settings has a hook with command "go test ./..."
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F3"

  Scenario: Hook command not containing any test runner is not flagged as F3
    Given global settings has a hook with command "echo done"
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F3"

  Scenario: Hook with test matcher and test runner command produces both F2 and F3
    Given global settings has a hook with matcher "test" and external command "pytest tests/"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F2"
    And the result contains at least 1 finding with id prefix "config-compat:F3"

  # --- F4: skip-hooks instructions in text sources ---

  Scenario: CLAUDE.md containing "--no-verify" produces F4 error
    Given CLAUDE.md contains the text "--no-verify"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F4"
    And the first F4 finding has severity "error"
    And the first F4 finding has fix_type "prompted"

  Scenario: CLAUDE.md containing "skip hooks" produces F4 error
    Given CLAUDE.md contains the text "skip hooks"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F4"

  Scenario: SweetClaude rules files are excluded from text scanning
    Given a SweetClaude rules file contains "skip hooks"
    When check_config_compat runs against the project state
    Then no finding has id prefix "config-compat:F4"

  Scenario: Non-SweetClaude rules file containing flagged pattern produces finding
    Given a non-SweetClaude rules file "myproject/coding.md" contains "skip hooks"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F4"

  Scenario: Global CLAUDE.md containing skip-hooks pattern produces F4 error
    Given global CLAUDE.md contains the text "bypass hooks"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F4"

  # --- W1: time-estimate instructions ---

  Scenario: CLAUDE.md containing "estimate" produces W1 warning
    Given CLAUDE.md contains the text "always provide an estimate"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:W1"
    And the first W1 finding has severity "warning"

  Scenario: CLAUDE.md containing "story points" produces W1 warning
    Given CLAUDE.md contains the text "include story points"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:W1"

  # --- W2: comment-everywhere instructions ---

  Scenario: CLAUDE.md containing "always add comments" produces W2 warning
    Given CLAUDE.md contains the text "always add comments"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:W2"
    And the first W2 finding has severity "warning"

  # --- W3: skip-tests instructions ---

  Scenario: CLAUDE.md containing "skip tests" produces W3 warning
    Given CLAUDE.md contains the text "you can skip tests"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:W3"
    And the first W3 finding has severity "warning"

  # --- W4: skip-confirmation instructions ---

  Scenario: CLAUDE.md containing "proceed without asking" produces W4 warning
    Given CLAUDE.md contains the text "proceed without asking"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:W4"
    And the first W4 finding has severity "warning"

  # --- I1: duplicate phase-dwelling rule ---

  Scenario: CLAUDE.md containing phase-dwelling duplicate produces I1 info
    Given CLAUDE.md contains the text "never ask if ready to move"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:I1"
    And the first I1 finding has severity "info"
    And the first I1 finding has fix_type "report-only"

  # --- I2: duplicate proposal-mode rule ---

  Scenario: CLAUDE.md containing proposal-mode duplicate produces I2 info
    Given CLAUDE.md contains the text "propose don't ask"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:I2"
    And the first I2 finding has severity "info"
    And the first I2 finding has fix_type "report-only"

  # --- Edge cases ---

  Scenario: Pattern matching is case-insensitive
    Given CLAUDE.md contains the text "SKIP HOOKS"
    When check_config_compat runs against the project state
    Then the result contains at least 1 finding with id prefix "config-compat:F4"

  Scenario: Info findings have empty fix_recipe
    Given CLAUDE.md contains the text "propose don't ask"
    When check_config_compat runs against the project state
    Then the first I2 finding fix_recipe is empty

  # --- Interaction ---

  Scenario: F1 and F4 findings from different sources accumulate
    Given global settings has allowedTools excluding "Agent"
    And CLAUDE.md contains the text "--no-verify"
    When check_config_compat runs against the project state
    Then the result contains at least 2 findings
    And the findings include id prefix "config-compat:F1"
    And the findings include id prefix "config-compat:F4"
