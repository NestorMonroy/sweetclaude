Feature: Post-migration verification
  Validate the migrated file structure for correctness and completeness.

  Background:
    Given a project directory after migration execution

  Scenario: Clean migration passes all checks
    Given all ISSUE files have valid frontmatter
    And all EP and MS files have valid frontmatter
    And no duplicate IDs exist
    And all cross-references resolve
    And no legacy files remain in active directories
    When verify() is called
    Then it returns an empty error list

  # --- Frontmatter validation ---

  Scenario: Missing required frontmatter field fails verification
    Given ISSUE-042.md exists with frontmatter missing "type"
    When verify() is called
    Then it returns an error about ISSUE-042 missing required field "type"

  Scenario: Required frontmatter fields are id, title, type, status, created
    Given ISSUE-042.md with only id, title, type, status, created in frontmatter
    When verify() is called
    Then ISSUE-042 passes frontmatter validation

  Scenario: EP files are also validated for required frontmatter
    Given EP-001.md exists with frontmatter missing "title"
    When verify() is called
    Then it returns an error about EP-001 missing required field "title"

  Scenario: MS files are also validated for required frontmatter
    Given MS-007.md exists with frontmatter missing "status"
    When verify() is called
    Then it returns an error about MS-007 missing required field "status"

  Scenario: Null created field fails verification
    Given ISSUE-042.md with frontmatter created: null
    When verify() is called
    Then it returns an error about ISSUE-042 having null required field "created"

  Scenario: Frontmatter id must match filename
    Given ISSUE-042-widget.md with frontmatter id "ISSUE-040"
    When verify() is called
    Then it returns an error about id/filename mismatch for ISSUE-042-widget.md

  # --- Priority validation ---

  Scenario: Non-standard priority value produces warning
    Given ISSUE-042.md with priority "critical"
    When verify() is called
    Then it returns a warning about non-standard priority value

  # --- Duplicate IDs ---

  Scenario: Duplicate ID across directories fails verification
    Given ISSUE-042.md exists in both backlog/ and roadmap/issues/
    When verify() is called
    Then it returns an error about duplicate ID "ISSUE-042"

  # --- Cross-reference validation ---

  Scenario: depends_on pointing to nonexistent ID fails
    Given ISSUE-042.md has depends_on ["ISSUE-999"]
    And ISSUE-999 does not exist
    When verify() is called
    Then it returns an error about unresolved depends_on reference

  Scenario: depends_on still showing legacy STORY-N reference fails
    Given ISSUE-042.md has depends_on ["STORY-015"]
    When verify() is called
    Then it returns an error about unrewritten legacy reference

  Scenario: Epic reference pointing to nonexistent EP fails
    Given ISSUE-042.md has epic "EP-999"
    And EP-999 does not exist
    When verify() is called
    Then it returns an error about unresolved epic reference

  Scenario: Milestone reference pointing to nonexistent MS fails
    Given ISSUE-042.md has milestone "MS-999"
    And MS-999 does not exist
    When verify() is called
    Then it returns an error about unresolved milestone reference

  Scenario: superseded_by pointing to nonexistent ID fails
    Given ISSUE-082.md has superseded_by "EP-999"
    And EP-999 does not exist
    When verify() is called
    Then it returns an error about unresolved superseded_by reference

  Scenario: superseded_by pointing to valid ISSUE-NNN passes
    Given ISSUE-082.md has superseded_by "ISSUE-090"
    And ISSUE-090 exists
    When verify() is called
    Then no error is reported for ISSUE-082 superseded_by

  # --- Legacy file cleanup ---

  Scenario: Remaining BL file in active directory fails verification
    Given BL-042.md still exists in backlog/
    When verify() is called
    Then it returns an error about legacy file "BL-042.md"

  Scenario: Remaining STORY file fails verification
    Given STORY-015.md still exists in backlog/done/
    When verify() is called
    Then it returns an error about legacy file "STORY-015.md"

  Scenario: Remaining RM file fails verification
    Given RM-001.md still exists in roadmap/
    When verify() is called
    Then it returns an error about legacy file "RM-001.md"

  Scenario: CHORE, BUG, DEBT files in active directories fail
    Given CHORE-010.md exists in backlog/
    When verify() is called
    Then it returns an error about legacy file "CHORE-010.md"

  Scenario: Legacy file check is recursive under active directories
    Given BL-001.md exists in backlog/some-subdir/
    When verify() is called
    Then it returns an error about legacy file "BL-001.md"

  Scenario: Archived I-N files in backlog/archived/ are allowed
    Given I-001.md exists in backlog/archived/
    When verify() is called
    Then no error is reported for I-001.md

  Scenario: issues/ directory must be empty after archival
    Given I-001.md still exists in issues/ (not moved to archived)
    When verify() is called
    Then it returns an error about non-empty issues directory

  # --- File count ---

  Scenario: File count matches plan expectations
    Given the plan expected 8 migrated + 2 archived + 1 restructured = 11 dest files
    And 3 RM files were retired
    And 11 dest files exist on disk (including archived)
    When verify() is called
    Then no file count error is reported

  Scenario: File count mismatch fails verification
    Given the plan expected 10 dest files
    But only 8 exist on disk
    When verify() is called
    Then it returns an error about file count mismatch

  # --- Path containment ---

  Scenario: Dest file outside project root fails verification
    Given a dest file somehow ended up outside project_dir
    When verify() is called
    Then it returns an error about path containment

  # --- CHORE/BUG refs not in id_map ---

  Scenario: Unrewritten CHORE ref in body produces warning not error
    Given MS-007.md body contains "CHORE-999" which was not in id_map
    And CHORE-999 was not a scan_sources target
    When verify() is called
    Then it returns a warning about unrewritten legacy reference
    And it does not return an error

  # --- Edge cases ---

  Scenario: verify() called without prior execute (no state file)
    Given no migration-state.yaml exists
    And legacy BL files still exist
    When verify() is called
    Then it returns errors about remaining legacy files

  Scenario: Zero ISSUE files after all-retire corpus
    Given only RM files existed and all were retired
    When verify() is called
    Then it does not false-pass on empty directories
    And it returns a warning about zero migrated files
