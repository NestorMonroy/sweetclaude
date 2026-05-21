Feature: Migration validation
  Pre-migration checks that must pass before planning or execution.

  Background:
    Given a project directory with legacy taxonomy files
    And artifact-privacy.yaml has product base_path ".sweetclaude/product"

  Scenario: Valid project passes validation
    Given BL-001.md exists in backlog/
    And no ISSUE-NNN files exist in target directories
    And no migration-state.yaml exists
    When validate() is called
    Then it returns an empty error list

  Scenario: Empty project fails validation
    Given no source files exist in any scan location
    When validate() is called
    Then it returns an error containing "no source files found"

  Scenario: Single pre-existing ISSUE file at target path fails validation
    Given BL-042.md exists in backlog/ with title "Widget builder"
    And ISSUE-042-widget-builder.md already exists in roadmap/issues/
    When validate() is called
    Then it returns an error containing "ISSUE-042" and "already exists"

  Scenario: Multiple pre-existing ISSUE files produce multiple errors
    Given BL-042.md and BL-043.md exist in backlog/
    And ISSUE-042-widget-builder.md exists in roadmap/issues/
    And ISSUE-043-other-thing.md exists in backlog/
    When validate() is called
    Then it returns 2 errors
    And one mentions "ISSUE-042"
    And one mentions "ISSUE-043"

  Scenario: Failed migration state blocks validation
    Given migration-state.yaml exists with status "failed"
    When validate() is called
    Then it returns an error containing "previous migration failed"
    And the error mentions rollback

  Scenario: In-progress migration state blocks validation
    Given migration-state.yaml exists with status "in_progress"
    When validate() is called
    Then it returns an error containing "migration already in progress"

  Scenario: Completed migration state passes validation
    Given migration-state.yaml exists with status "complete"
    When validate() is called
    Then it returns an empty error list

  Scenario: Product base escaping project root fails validation
    Given artifact-privacy.yaml has product base_path "/etc/shadow"
    When validate() is called
    Then it raises ValueError containing "escapes project root"

  Scenario: Missing artifact-privacy.yaml uses default product base
    Given artifact-privacy.yaml does not exist
    When validate() is called
    Then the product base resolves to ".sweetclaude/product"

  Scenario: Empty artifact-privacy.yaml uses default product base
    Given artifact-privacy.yaml exists but is empty (zero bytes)
    When validate() is called
    Then the product base resolves to ".sweetclaude/product"

  Scenario: Symlink source file pointing outside project root fails validation
    Given backlog/BL-099-evil.md is a symlink to /etc/passwd
    When validate() is called
    Then it returns an error about source path escaping project root
