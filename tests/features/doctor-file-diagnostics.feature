Feature: Doctor file_diagnostics checks
  The check_file_diagnostics function validates frontmatter quality of product
  artifact files: missing frontmatter, parse errors, duplicate IDs, missing
  required fields (id, title, type, status), unknown status/type values.

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no file_diagnostics findings
    When check_file_diagnostics runs against the project state
    Then the result contains 0 findings

  # --- No frontmatter ---

  Scenario: File without frontmatter delimiter produces error
    Given a backlog file "ISSUE-001-test.md" with content "No frontmatter here"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:no-frontmatter:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:no-frontmatter:ISSUE-001-test.md" has severity "error"
    And the finding with id "file-diagnostics:no-frontmatter:ISSUE-001-test.md" has fix_type "report-only"

  # --- YAML parse error ---

  Scenario: File with broken YAML in frontmatter produces error
    Given a backlog file "ISSUE-001-test.md" with content "---\n{{bad: yaml\n---\n# Body"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:parse-error:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:parse-error:ISSUE-001-test.md" has severity "error"
    And the finding with id "file-diagnostics:parse-error:ISSUE-001-test.md" has fix_type "report-only"

  # --- Duplicate IDs ---

  Scenario: Two files with the same ID produce duplicate-id error
    Given a backlog file "ISSUE-001-first.md" with frontmatter id "ISSUE-001" and title "First"
    And a backlog file "ISSUE-001-second.md" with frontmatter id "ISSUE-001" and title "Second"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:duplicate-id:ISSUE-001"
    And the finding with id "file-diagnostics:duplicate-id:ISSUE-001" has severity "error"
    And the finding with id "file-diagnostics:duplicate-id:ISSUE-001" has fix_type "prompted"
    And the finding with id "file-diagnostics:duplicate-id:ISSUE-001" has 2 file_paths

  Scenario: Duplicate IDs across backlog and roadmap produce error
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:duplicate-id:ISSUE-001"

  Scenario: Different IDs do not produce duplicate finding
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    And a backlog file "ISSUE-002-test.md" with frontmatter id "ISSUE-002"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:duplicate-id"

  # --- Missing fields ---

  Scenario: File with no id in frontmatter produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter missing id
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-id:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:missing-field-id:ISSUE-001-test.md" has severity "warning"

  Scenario: File with no title in frontmatter produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter missing title
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-title:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:missing-field-title:ISSUE-001-test.md" has severity "warning"

  Scenario: File with no type in frontmatter produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter missing type
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-type:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:missing-field-type:ISSUE-001-test.md" has severity "warning"
    And the finding with id "file-diagnostics:missing-field-type:ISSUE-001-test.md" has fix_type "prompted"

  Scenario: File with no status in frontmatter produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter missing status
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-status:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:missing-field-status:ISSUE-001-test.md" has severity "warning"
    And the finding with id "file-diagnostics:missing-field-status:ISSUE-001-test.md" has fix_type "prompted"

  # --- Unknown status ---

  Scenario: File with unrecognized status produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter status "invented"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:unknown-status:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:unknown-status:ISSUE-001-test.md" has severity "warning"

  Scenario: File with valid status "active" produces no unknown-status finding
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "active"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-status"

  Scenario: File with valid status "done" produces no unknown-status finding
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-status"

  Scenario: Status with parenthetical suffix is parsed correctly
    Given a backlog file "ISSUE-001-test.md" with frontmatter status "active(in review)"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-status"

  Scenario: Status with em-dash suffix is parsed correctly
    Given a backlog file "ISSUE-001-test.md" with frontmatter status "done—shipped"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-status"

  Scenario: Uppercase status is normalized and accepted
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "Active"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-status"

  # --- Unknown type ---

  Scenario: File with unrecognized type produces warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter type "invented-type"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:unknown-type:ISSUE-001-test.md"
    And the finding with id "file-diagnostics:unknown-type:ISSUE-001-test.md" has severity "warning"

  Scenario: File with valid type "story" produces no unknown-type finding
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and type "story"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-type"

  Scenario: Mixed-case type is normalized and accepted
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and type "Story"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics:unknown-type"

  Scenario: Type with parenthetical suffix is flagged as unknown
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and type "story(core)"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:unknown-type:ISSUE-001-test.md"

  # --- Exclusions ---

  Scenario: INDEX.md is excluded from file diagnostics
    Given a backlog file "INDEX.md" with content "No frontmatter"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics"

  Scenario: MIGRATION-MAP.md is excluded from file diagnostics
    Given a backlog file "MIGRATION-MAP.md" with content "No frontmatter"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics"

  Scenario: Files ending in -INDEX.md are excluded
    Given a backlog file "STORY-INDEX.md" with content "No frontmatter"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics"

  Scenario: Files in archived/ directory are excluded
    Given a backlog file "archived/ISSUE-001-test.md" with content "No frontmatter"
    When check_file_diagnostics runs against the project state
    Then no finding has id prefix "file-diagnostics"

  # --- Empty frontmatter ---

  Scenario: Empty frontmatter block produces missing-field warnings
    Given a backlog file "ISSUE-001-test.md" with content "---\n---\n# Body"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-id:ISSUE-001-test.md"
    And no finding has id prefix "file-diagnostics:no-frontmatter"
    And no finding has id prefix "file-diagnostics:parse-error"

  # --- Roadmap scanning ---

  Scenario: Roadmap file with missing fields produces warnings
    Given a roadmap file "MS-001-launch.md" with frontmatter missing id
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:missing-field-id:MS-001-launch.md"

  # --- Interaction ---

  Scenario: Multiple field issues on same file produce multiple findings
    Given a backlog file "ISSUE-001-test.md" with frontmatter missing id, title, type, and status
    When check_file_diagnostics runs against the project state
    Then the result contains at least 4 findings
    And the findings include id "file-diagnostics:missing-field-id:ISSUE-001-test.md"
    And the findings include id "file-diagnostics:missing-field-title:ISSUE-001-test.md"
    And the findings include id "file-diagnostics:missing-field-type:ISSUE-001-test.md"
    And the findings include id "file-diagnostics:missing-field-status:ISSUE-001-test.md"

  Scenario: Parse error stops further field checks for that file
    Given a backlog file "ISSUE-001-test.md" with content "---\n{{bad: yaml\n---\n# Body"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:parse-error:ISSUE-001-test.md"
    And no finding has id prefix "file-diagnostics:missing-field"

  Scenario: No-frontmatter error stops further field checks for that file
    Given a backlog file "ISSUE-001-test.md" with content "No frontmatter here"
    When check_file_diagnostics runs against the project state
    Then the findings include id "file-diagnostics:no-frontmatter:ISSUE-001-test.md"
    And no finding has id prefix "file-diagnostics:missing-field"
