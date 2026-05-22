Feature: Doctor auto-fix pipeline
  Tests covering E5-S03 (auto-fix recipes), E5-S04 (content-based backups),
  E5-S05 (post-fix rescan), and E5-S06 (archive integrity).

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # ==========================================================================
  # E5-S03: Auto-fix tests — recipe types, idempotency, partial failure
  # ==========================================================================

  # --- write_field recipe ---

  Scenario: write_field recipe updates a YAML field
    Given a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the actions list contains 1 entry with action "auto-fix"
    And session-state.yaml now has key "phase_schema_version" with value 2

  Scenario: write_field recipe records before and after hashes
    Given a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the first action entry has a non-empty "before_hash" starting with "sha256:"
    And the first action entry has a non-empty "after_hash"
    And "before_hash" differs from "after_hash"

  Scenario: write_field precondition skips when value already correct
    Given session-state.yaml already has key "phase_schema_version" set to 2
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the first action entry has "before_hash" equal to "after_hash"

  # --- create_dir recipe ---

  Scenario: create_dir recipe creates a missing directory
    Given the plans directory does not exist
    And a finding with fix_type "auto" and recipe action "create_dir" targeting the plans directory
    When auto_fix runs with the finding against an archive
    Then the plans directory now exists
    And the actions list contains 1 entry with action "auto-fix"

  Scenario: create_dir precondition skips when directory already exists
    And a finding with fix_type "auto" and recipe action "create_dir" targeting the plans directory
    When auto_fix runs with the finding against an archive
    Then the first action entry has "before_hash" equal to "after_hash"

  # --- delete_file recipe ---

  Scenario: delete_file recipe removes target file
    Given a temporary marker file "pending-drift-decision.yaml" exists in .sweetclaude/state/
    And a finding with fix_type "auto" and recipe action "delete_file" targeting ".sweetclaude/state/pending-drift-decision.yaml"
    When auto_fix runs with the finding against an archive
    Then the file ".sweetclaude/state/pending-drift-decision.yaml" no longer exists
    And the actions list contains 1 entry with action "auto-fix"

  Scenario: delete_file precondition skips when file already absent
    And a finding with fix_type "auto" and recipe action "delete_file" targeting ".sweetclaude/state/pending-drift-decision.yaml"
    When auto_fix runs with the finding against an archive
    Then the first action entry has "before_hash" equal to "after_hash"

  # --- rebuild_cache recipe ---

  Scenario: rebuild_cache recipe runs cache.py --rebuild
    Given a stub cache.py script that exits 0
    And a finding with fix_type "auto" and recipe action "rebuild_cache"
    When auto_fix runs with the finding against an archive
    Then the actions list contains 1 entry with action "auto-fix"
    And the first action entry has "success" as true

  Scenario: rebuild_cache recipe records failure when cache.py missing
    Given cache.py does not exist
    And a finding with fix_type "auto" and recipe action "rebuild_cache"
    When auto_fix runs with the finding against an archive
    Then the actions list contains 1 entry with action "auto-fix-failed"
    And the first action entry has a non-empty "error"

  # --- run_script recipe ---

  Scenario: run_script recipe runs allowlisted script
    Given a stub generate-session-state.sh script that exits 0
    And a finding with fix_type "auto" and recipe action "run_script" with cmd ["bash", "scripts/generate-session-state.sh"]
    When auto_fix runs with the finding against an archive
    Then the actions list contains 1 entry with action "auto-fix"

  Scenario: run_script recipe rejects non-allowlisted script
    And a finding with fix_type "auto" and recipe action "run_script" with cmd ["python3", "scripts/evil.py"]
    When auto_fix runs with the finding against an archive
    Then the actions list contains 1 entry with action "auto-fix-failed"
    And the first action entry "error" contains "not in allowlist"

  # --- Filtering ---

  Scenario: auto_fix skips findings with fix_type "report-only"
    Given a finding with fix_type "report-only"
    When auto_fix runs with the finding against an archive
    Then the actions list contains 0 entries

  Scenario: auto_fix skips findings with fix_type "prompted" by default
    Given a finding with fix_type "prompted" and recipe action "write_field" targeting session-state.yaml key "x" value "y"
    When auto_fix runs with the finding against an archive
    Then the actions list contains 0 entries

  Scenario: auto_fix includes prompted findings when include_prompted is true
    Given a finding with fix_type "prompted" and recipe action "write_field" targeting session-state.yaml key "x" value "y"
    When auto_fix runs with include_prompted true against an archive
    Then the actions list contains 1 entry with action "auto-fix"

  Scenario: auto_fix skips prompted findings whose recipe action is "prompt"
    Given a finding with fix_type "prompted" and recipe action "prompt"
    When auto_fix runs with include_prompted true against an archive
    Then the actions list contains 0 entries

  # --- Idempotency ---

  Scenario: Running auto_fix twice produces zero non-no-op actions on second run
    Given a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    And auto_fix runs again with the same finding against a fresh archive
    Then the second run actions list has all entries with "before_hash" equal to "after_hash"

  # --- Partial failure ---

  Scenario: One recipe fails while others succeed
    Given a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    And a finding with fix_type "auto" and recipe action "rebuild_cache"
    And cache.py does not exist
    When auto_fix runs with both findings against an archive
    Then the actions list contains 2 entries
    And one action has action "auto-fix" and another has action "auto-fix-failed"
    And the write_field change persists on disk

  # --- post_fix_categories ---

  Scenario: auto_fix returns changed categories in post_fix_categories
    Given a finding with fix_type "auto" category "env_wiring" and recipe action "create_dir" targeting the plans directory
    And the plans directory does not exist
    When auto_fix runs with the finding against an archive
    Then post_fix_categories contains "env_wiring"

  Scenario: No-op fixes do not appear in post_fix_categories
    Given a finding with fix_type "auto" category "env_wiring" and recipe action "create_dir" targeting the plans directory
    When auto_fix runs with the finding against an archive
    Then post_fix_categories is empty

  # --- actions.json persistence ---

  Scenario: auto_fix writes actions.json to archive directory
    Given a finding with fix_type "auto" and recipe action "create_dir" targeting the plans directory
    And the plans directory does not exist
    When auto_fix runs with the finding against an archive
    Then the archive directory contains an "actions.json" file
    And the actions.json file is valid JSON containing a list

  # ==========================================================================
  # E5-S04: Content-based backup tests
  # ==========================================================================

  Scenario: After write_field fix, before/ contains original file content
    Given session-state.yaml has content "phase_schema_version: 1\nfoo: bar\n"
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the archive before/ directory contains a backup of session-state.yaml
    And the backup content is byte-identical to the original "phase_schema_version: 1\nfoo: bar\n"

  Scenario: After write_field fix, diffs/ contains a valid unified diff
    Given session-state.yaml has content "phase_schema_version: 1\n"
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the archive diffs/ directory contains a diff file for session-state.yaml
    And the diff file starts with "---" and contains "+++"

  Scenario: After delete_file fix, before/ contains the deleted file content
    Given a temporary marker file "pending-drift-decision.yaml" exists in .sweetclaude/state/ with content "decision: pending\n"
    And a finding with fix_type "auto" and recipe action "delete_file" targeting ".sweetclaude/state/pending-drift-decision.yaml"
    When auto_fix runs with the finding against an archive
    Then the archive before/ directory contains a backup of "pending-drift-decision.yaml"
    And the backup content is byte-identical to the original "decision: pending\n"

  Scenario: No-op fix (precondition met) writes no backup or diff
    Given session-state.yaml already has key "phase_schema_version" set to 2
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the archive before/ directory is empty
    And the archive diffs/ directory is empty

  # ==========================================================================
  # E5-S05: Post-fix rescan tests
  # ==========================================================================

  Scenario: Post-fix rescan returns empty when all problems are fixed
    Given the plans directory does not exist
    And a finding for "env-wiring:missing:plans-directory" in category "env_wiring"
    When auto_fix creates the plans directory
    And post_fix_rescan runs for category "env_wiring" with the original finding IDs
    Then the rescan returns 0 findings

  Scenario: Post-fix rescan filters out original finding IDs
    Given global settings has no plansDirectory key
    When post_fix_rescan runs for category "env_wiring" with original finding IDs including "env-wiring:plans-directory-unset:settings_global"
    Then the rescan result does not contain finding "env-wiring:plans-directory-unset:settings_global"

  Scenario: Post-fix rescan returns genuinely new findings
    Given the project has a condition that produces finding A in category "env_wiring"
    And the project also has a latent condition that produces finding B in category "env_wiring"
    When post_fix_rescan runs for category "env_wiring" with original finding IDs containing only A
    Then the rescan result contains finding B but not finding A

  Scenario: Categories not requested are not rescanned
    Given the project has a condition that produces a finding in category "state_integrity"
    When post_fix_rescan runs for category "env_wiring" only
    Then the rescan returns 0 findings from category "state_integrity"

  # ==========================================================================
  # E5-S06: Archive integrity tests
  # ==========================================================================

  Scenario: Archive directory has correct structure after create_archive
    When create_archive runs against the project
    Then the archive directory exists
    And the archive directory contains a "before" subdirectory
    And the archive directory contains a "diffs" subdirectory
    And the archive directory name matches ISO 8601 format "YYYYMMDDTHHMMSSZ"

  Scenario: Manifest actions list matches before/ and diffs/ contents after auto-fix
    Given session-state.yaml has content "phase_schema_version: 1\n"
    And a finding with fix_type "auto" and recipe action "write_field" targeting session-state.yaml key "phase_schema_version" value 2
    When auto_fix runs with the finding against an archive
    Then the number of files in before/ matches the number of auto-fix actions with changed hashes
    And the number of files in diffs/ matches the number of auto-fix actions with changed hashes

  Scenario: record_action appends to pending-actions.jsonl
    Given an archive directory
    When record_action is called with action {"action": "prompted-fix", "finding_id": "test-1"}
    And record_action is called again with action {"action": "skip", "finding_id": "test-2"}
    Then the pending-actions.jsonl file contains 2 lines
    And each line is valid JSON

  Scenario: persist assembles manifest from both auto-fix and prompted actions
    Given an archive directory with actions.json containing 1 auto-fix action
    And a pending-actions.jsonl containing 1 prompted-fix action and 1 skip action
    When persist runs with the archive
    Then the manifest.json "actions" list has 3 entries
    And the manifest summary has "auto_fixed" equal to 1
    And the manifest summary has "user_fixed" equal to 1
    And the manifest summary has "skipped" equal to 1

  Scenario: persist writes last-doctor-run.json with correct fields
    Given an archive directory with actions.json containing 1 auto-fix action
    When persist runs with menu_preference "proceed" and scan findings
    Then last-doctor-run.json exists
    And last-doctor-run.json contains key "timestamp"
    And last-doctor-run.json contains key "version"
    And last-doctor-run.json contains key "summary"
    And last-doctor-run.json contains key "findings"
    And last-doctor-run.json contains "menu_preference" with value "proceed"

  Scenario: persist records safety_branch in manifest
    Given an archive directory
    When persist runs with safety_branch "doctor/run-20260522T120000Z"
    Then the manifest.json contains "safety_branch" with value "doctor/run-20260522T120000Z"
