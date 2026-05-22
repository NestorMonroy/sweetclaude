Feature: Doctor lifecycle tests
  Tests covering E5-S07 (retention/pruning), E5-S08 (suppression),
  and E5-S09 (dry-run simulation).

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # ==========================================================================
  # E5-S07: Retention / prune tests
  # ==========================================================================

  Scenario: With 3 archives all within 30 days, none are pruned
    Given 3 archive directories with timestamps within the last 7 days
    When prune_archives runs against the project
    Then the pruned list is empty
    And all 3 archive directories still exist

  Scenario: With 7 archives and 3 older than 30 days, 2 oldest are pruned (keep 5)
    Given 7 archive directories, 3 older than 30 days and 4 recent
    When prune_archives runs against the project
    Then the pruned list contains 2 entries
    And exactly 5 archive directories remain

  Scenario: With 10 archives and 8 older than 30 days, 5 oldest are pruned (keep 5)
    Given 10 archive directories, 8 older than 30 days and 2 recent
    When prune_archives runs against the project
    Then the pruned list contains 5 entries
    And exactly 5 archive directories remain

  Scenario: With 6 archives and 1 older than 30 days, 1 is pruned (keep 5)
    Given 6 archive directories, 1 older than 30 days and 5 recent
    When prune_archives runs against the project
    Then the pruned list contains 1 entry
    And exactly 5 archive directories remain

  Scenario: Pruning uses directory name timestamp, not mtime
    Given 6 archive directories with names older than 30 days but mtime is recent
    When prune_archives runs against the project
    Then the pruned list contains 1 entry

  Scenario: No doctor-runs directory returns empty list
    Given no doctor-runs directory exists
    When prune_archives runs against the project
    Then the pruned list is empty

  Scenario: Non-timestamp directory names are skipped during pruning
    Given 6 archive directories with valid timestamps and 1 directory named "temp"
    When prune_archives runs against the project
    Then the "temp" directory still exists

  # ==========================================================================
  # E5-S08: Suppression tests
  # ==========================================================================

  Scenario: Suppressed finding is excluded from scan output
    Given a project state that produces finding "file-diagnostics:unknown-status:ISSUE-001-test.md"
    And the suppression file contains entry for "file-diagnostics:unknown-status:ISSUE-001-test.md"
    When _scan runs against the project state
    Then the scan result does not include finding "file-diagnostics:unknown-status:ISSUE-001-test.md"

  Scenario: Resolved finding has its suppression entry auto-removed
    Given the suppression file contains entry for "env-wiring:missing:plans-directory"
    And the project state does not produce finding "env-wiring:missing:plans-directory"
    When _scan runs against the project state
    Then "env-wiring:missing:plans-directory" appears in suppressions_resolved
    And the suppression file no longer contains "env-wiring:missing:plans-directory"

  Scenario: Auto-removed suppression ID appears in suppressions_resolved
    Given the suppression file contains entries for "finding-A" and "finding-B"
    And the project state produces only "finding-B" (not "finding-A")
    When auto_cleanup_suppressions runs with current finding IDs {"finding-B"}
    Then the result contains "finding-A"
    And the suppression file retains only "finding-B"

  Scenario: Re-emerged finding has previously_suppressed set to true
    Given the suppression file contains entry for "env-wiring:missing:plans-directory"
    And the project state produces finding "env-wiring:missing:plans-directory"
    When _scan runs against the project state
    Then finding "env-wiring:missing:plans-directory" is excluded from active findings (still suppressed)

  Scenario: load_suppressions returns empty list for missing file
    Given no suppression file exists
    When load_suppressions runs
    Then the result is an empty list

  Scenario: load_suppressions returns empty list for malformed file
    Given the suppression file contains "not a list"
    When load_suppressions runs
    Then the result is an empty list

  Scenario: save_suppressions creates parent directories if needed
    Given the state directory does not exist
    When save_suppressions writes entries
    Then the suppression file exists with the written entries

  # ==========================================================================
  # E5-S09: Dry-run simulation tests
  # ==========================================================================

  Scenario: Dry-run of write_field shows before/after values
    Given session-state.yaml has content "phase_schema_version: 1\n"
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When dry_run runs with the finding
    Then the simulations list contains 1 entry
    And the simulation entry has "before" containing "phase_schema_version: 1"
    And the simulation entry has "after" containing "phase_schema_version: 2"

  Scenario: Dry-run of rebuild_cache shows requires-execution note
    Given a finding with fix_type "auto" and recipe action "rebuild_cache"
    When dry_run runs with the finding
    Then the simulations list contains 1 entry
    And the simulation entry has "note" containing "requires real execution"

  Scenario: Dry-run of run_script shows requires-execution note
    Given a finding with fix_type "auto" and recipe action "run_script" with cmd ["bash", "scripts/generate-session-state.sh"]
    When dry_run runs with the finding
    Then the simulations list contains 1 entry
    And the simulation entry has "note" containing "requires real execution"

  Scenario: Dry-run of prompted finding shows approval note
    Given a finding with fix_type "prompted" and recipe action "write_field" targeting session-state.yaml key "x" value "y"
    When dry_run runs with the finding
    Then the simulations list contains 1 entry
    And the simulation entry has "note" equal to "Will be presented for your approval"

  Scenario: Dry-run produces zero side effects
    Given session-state.yaml has content "phase_schema_version: 1\n"
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When dry_run runs with the finding
    Then session-state.yaml still has content "phase_schema_version: 1\n"
    And no archive directory was created

  Scenario: Dry-run of create_dir shows description
    Given the plans directory does not exist
    And a finding with fix_type "auto" and recipe action "create_dir" targeting the plans directory
    When dry_run runs with the finding
    Then the simulations list contains 1 entry
    And the simulation entry has "description" containing "create_dir"

  Scenario: Dry-run of report-only finding produces no simulation entry
    Given a finding with fix_type "report-only"
    When dry_run runs with the finding
    Then the simulations list contains 0 entries
