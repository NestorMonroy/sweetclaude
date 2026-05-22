Feature: Doctor integration tests
  Tests covering E5-S10 (graceful degradation), E5-S11 (early exit),
  E5-S12 (happy-path), and E5-S13 (manifest completeness).

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # ==========================================================================
  # E5-S10: Graceful degradation tests
  # ==========================================================================

  Scenario: Missing cache.py skips storage_lint counter-drift but other storage rules run
    Given cache.py does not exist
    And the project has a storage-lint condition (e.g., duplicate IDs across files)
    When _scan runs against the project state
    Then skipped_categories does not contain "storage_lint"
    And the findings include a storage-lint finding (non-counter-drift)

  Scenario: Missing migration runner skips migration_currency schema drift
    Given migration runner does not exist
    When _scan runs against the project state
    Then skipped_categories contains an entry for "migration_currency"

  Scenario: Missing migrate_taxonomy.py skips taxonomy drift check
    Given migrate_taxonomy.py does not exist
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:taxonomy-drift"

  Scenario: Missing migrate-v3-to-v4.py skips orphan scan
    Given migrate-v3-to-v4.py does not exist
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:orphans"

  Scenario: Scan completes and returns valid JSON despite all dependency scripts missing
    Given cache.py, migration runner, migrate_taxonomy.py, and migrate-v3-to-v4.py all do not exist
    When _scan runs against the project state
    Then the scan returns a dict with keys "findings", "skipped_categories", "suppressions_resolved", "project_state_summary"

  Scenario: DependencyMissing from a check populates skipped_categories with category and reason
    Given migration runner does not exist
    When _scan runs against the project state
    Then skipped_categories contains an entry with "category" equal to "migration_currency"
    And that entry has a non-empty "reason" string

  # ==========================================================================
  # E5-S11: Early exit test
  # ==========================================================================

  Scenario: Project with no sweetclaude.yaml returns not-configured error
    Given sweetclaude.yaml does not exist
    When the scan CLI subcommand runs against the project
    Then the JSON output contains "error" with value "not-configured"
    And the JSON output contains "message"
    And the CLI exit code is 0

  Scenario: Not-configured output has no findings or skipped_categories
    Given sweetclaude.yaml does not exist
    When the scan CLI subcommand runs against the project
    Then the JSON output does not contain key "findings"
    And the JSON output does not contain key "skipped_categories"

  # ==========================================================================
  # E5-S12: Happy-path test
  # ==========================================================================

  Scenario: Healthy fixture produces zero findings and zero skipped categories
    When _scan runs against the project state
    Then the scan returns 0 findings
    And skipped_categories is empty

  Scenario: Healthy fixture has populated project_state_summary
    When _scan runs against the project state
    Then project_state_summary contains key "backlog_count"
    And project_state_summary contains key "roadmap_count"
    And project_state_summary contains key "hook_count"
    And project_state_summary contains key "has_sweetclaude_yaml"
    And project_state_summary "has_sweetclaude_yaml" is true

  Scenario: Full pipeline on healthy fixture: scan, auto-fix (no-op), persist produces zero-action manifest
    When _scan runs against the project state and returns 0 findings
    And auto_fix runs with the empty findings against an archive
    And persist runs with the archive
    Then the manifest.json "actions" list is empty
    And the manifest summary has "auto_fixed" equal to 0
    And the manifest summary has "user_fixed" equal to 0
    And the manifest summary has "skipped" equal to 0
    And the manifest summary has "failed" equal to 0

  # ==========================================================================
  # E5-S13: Manifest completeness test
  # ==========================================================================

  Scenario: Manifest after mixed actions contains all entries with correct types
    Given an archive with actions.json containing:
      | action         | finding_id  |
      | auto-fix       | fix-success |
      | auto-fix-failed| fix-fail    |
    And a pending-actions.jsonl containing:
      | action       | finding_id   |
      | prompted-fix | prompt-accept|
      | skip         | prompt-skip  |
    When persist runs with the archive
    Then the manifest.json "actions" list has 4 entries
    And the manifest summary has "auto_fixed" equal to 1
    And the manifest summary has "user_fixed" equal to 1
    And the manifest summary has "skipped" equal to 1
    And the manifest summary has "failed" equal to 1

  Scenario: Each action entry has finding_id and timestamp
    Given an archive with actions.json containing 1 auto-fix entry with finding_id "test-fix-1"
    When persist runs with the archive
    Then every action in the manifest has a "finding_id" key
    And every action in the manifest has a "timestamp" key

  Scenario: Success action entries have before_hash and after_hash
    Given an archive with actions.json containing 1 auto-fix entry with before_hash and after_hash
    When persist runs with the archive
    Then the auto-fix action in the manifest has "before_hash"
    And the auto-fix action in the manifest has "after_hash"

  Scenario: Failure action entries have error field
    Given an archive with actions.json containing 1 auto-fix-failed entry with error "cache.py not found"
    When persist runs with the archive
    Then the failed action in the manifest has "error" equal to "cache.py not found"

  Scenario: Summary counts match the action list
    Given an archive with 3 auto-fix actions, 1 auto-fix-failed, 2 prompted-fix, 1 skip
    When persist runs with the archive
    Then the manifest summary "auto_fixed" equals 3
    And the manifest summary "failed" equals 1
    And the manifest summary "user_fixed" equals 2
    And the manifest summary "skipped" equals 1
    And the total actions count is 7
