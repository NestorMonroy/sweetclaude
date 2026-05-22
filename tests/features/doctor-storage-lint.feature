Feature: Doctor storage_lint checks
  The check_storage_lint function validates SweetClaude product artifact storage:
  cross-location duplicate IDs, counter drift, v3 file remnants, done/status
  mismatches in backlog and roadmap, and epic completion criteria.

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no storage_lint findings
    When check_storage_lint runs against the project state
    Then the result contains 0 findings

  # --- Cross-location duplicate IDs ---

  Scenario: Same ID in both backlog and roadmap produces error
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:cross-location-duplicate-id:ISSUE-001"
    And the finding with id "storage-lint:cross-location-duplicate-id:ISSUE-001" has severity "error"
    And the finding with id "storage-lint:cross-location-duplicate-id:ISSUE-001" has fix_type "report-only"

  Scenario: Different IDs in backlog and roadmap produce no duplicate finding
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-002-other.md" with frontmatter id "ISSUE-002"
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:cross-location-duplicate-id"

  Scenario: INDEX.md files are excluded from duplicate ID scan
    Given a backlog file "INDEX.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:cross-location-duplicate-id"

  Scenario: MIGRATION-MAP.md files are excluded from duplicate ID scan
    Given a backlog file "MIGRATION-MAP.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:cross-location-duplicate-id"

  Scenario: File with malformed frontmatter excluded from duplicate ID scan
    Given a backlog file "ISSUE-001-broken.md" with content "no frontmatter here"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:cross-location-duplicate-id"

  # --- Counter drift ---

  Scenario: Counter drift raises DependencyMissing when cache.py absent
    Given a backlog file "ISSUE-005-test.md" with frontmatter id "ISSUE-005"
    And scripts/cache.py does not exist
    When check_storage_lint runs against the project state
    Then the check raises DependencyMissing

  Scenario: No backlog issue files with cache.py absent does not raise
    Given scripts/cache.py does not exist
    When check_storage_lint runs against the project state
    Then the result contains 0 findings

  Scenario: Counter drift detected when file max exceeds cache max
    Given a backlog file "ISSUE-010-test.md" with frontmatter id "ISSUE-010"
    And cache.py next-id returns "ISSUE-005"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:counter-drift:issue"
    And the finding with id "storage-lint:counter-drift:issue" has severity "warning"
    And the finding with id "storage-lint:counter-drift:issue" has fix_type "auto"
    And the finding with id "storage-lint:counter-drift:issue" fix_recipe action is "rebuild_cache"

  Scenario: No drift when cache max matches or exceeds file max
    Given a backlog file "ISSUE-003-test.md" with frontmatter id "ISSUE-003"
    And cache.py next-id returns "ISSUE-010"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:counter-drift:issue"

  Scenario: Counter drift exact boundary — file max equals cache max
    Given a backlog file "ISSUE-005-test.md" with frontmatter id "ISSUE-005"
    And cache.py next-id returns "ISSUE-006"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:counter-drift:issue"

  Scenario: Subprocess exception during counter drift silently suppresses drift
    Given a backlog file "ISSUE-010-test.md" with frontmatter id "ISSUE-010"
    And cache.py subprocess will raise an exception
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:counter-drift:issue"

  # --- V3 file remnants ---

  Scenario: BL-prefixed files on v4 produce warning
    Given a backlog file "BL-001-old.md" with content "# Old item"
    And sweetclaude.yaml has framework installed_version "4.0.8-beta"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:v3-files-present:backlog"
    And the finding with id "storage-lint:v3-files-present:backlog" has severity "warning"
    And the finding with id "storage-lint:v3-files-present:backlog" has fix_type "prompted"

  Scenario: BL-prefixed files on v3 do not produce warning
    Given a backlog file "BL-001-old.md" with content "# Old item"
    And sweetclaude.yaml has framework installed_version "3.2.1"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:v3-files-present:backlog"

  Scenario: sweetclaude.yaml absent with BL-files does not flag v3 remnants
    Given a backlog file "BL-001-old.md" with content "# Old item"
    And sweetclaude.yaml does not exist
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:v3-files-present:backlog"

  Scenario: BL-file in subdirectory not detected by non-recursive glob
    Given a backlog file "done/BL-001-old.md" with content "# Old item"
    And sweetclaude.yaml has framework installed_version "4.0.8-beta"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:v3-files-present:backlog"

  # --- Done/status mismatch: backlog done/ directory ---

  Scenario: File in done/ without done status produces mismatch warning
    Given a backlog file "done/ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "active"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:done-status-mismatch:ISSUE-001-test.md"
    And the finding with id "storage-lint:done-status-mismatch:ISSUE-001-test.md" has severity "warning"
    And the finding with id "storage-lint:done-status-mismatch:ISSUE-001-test.md" has fix_type "prompted"

  Scenario: File in done/ with status "done" produces no mismatch
    Given a backlog file "done/ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  Scenario: File in done/ with status "abandoned" produces no mismatch
    Given a backlog file "done/ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "abandoned"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  # --- Done/status mismatch: backlog root (reverse) ---

  Scenario: File in backlog root with done status produces mismatch warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:done-status-mismatch:ISSUE-001-test.md"
    And the finding with id "storage-lint:done-status-mismatch:ISSUE-001-test.md" fix_recipe action is "prompt"
    And the finding with id "storage-lint:done-status-mismatch:ISSUE-001-test.md" fix_recipe type is "file_move"

  Scenario: File in backlog root with active status produces no mismatch
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "active"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  Scenario: File in backlog root with abandoned status produces mismatch warning
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "abandoned"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:done-status-mismatch:ISSUE-001-test.md"
    And the finding with id "storage-lint:done-status-mismatch:ISSUE-001-test.md" fix_recipe type is "file_move"

  Scenario: File in archived/ directory with done status not flagged
    Given a backlog file "archived/ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  # --- Done/status mismatch: roadmap issues ---

  Scenario: Roadmap issue with done status outside done/ produces mismatch
    Given a roadmap issues file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  Scenario: Roadmap issue in done/ directory is not flagged
    Given a roadmap issues file "done/ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "done"
    When check_storage_lint runs against the project state
    Then no finding has id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  Scenario: Roadmap issue with abandoned status outside done/ produces mismatch
    Given a roadmap issues file "ISSUE-001-test.md" with frontmatter id "ISSUE-001" and status "abandoned"
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:done-status-mismatch:ISSUE-001-test.md"

  # --- Epic missing completion criteria ---

  Scenario: Active epic without completion_criteria produces info finding
    Given a roadmap epic file "EP-001-test.md" with type "epic" and status "active" and no completion_criteria
    When check_storage_lint runs against the project state
    Then the findings include id "storage-lint:epic-missing-criteria:EP-001"
    And the finding with id "storage-lint:epic-missing-criteria:EP-001" has severity "info"
    And the finding with id "storage-lint:epic-missing-criteria:EP-001" has fix_type "report-only"

  Scenario: Done epic without completion_criteria is not flagged
    Given a roadmap epic file "EP-001-test.md" with type "epic" and status "done" and no completion_criteria
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:epic-missing-criteria"

  Scenario: Active epic with completion_criteria produces no finding
    Given a roadmap epic file "EP-001-test.md" with type "epic" and status "active" and completion_criteria present
    When check_storage_lint runs against the project state
    Then no finding has id prefix "storage-lint:epic-missing-criteria"

  # --- Interaction: multiple check blocks fire together ---

  Scenario: Duplicate ID and v3 file findings accumulate
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    And a roadmap file "ISSUE-001-dup.md" with frontmatter id "ISSUE-001"
    And a backlog file "BL-001-old.md" with content "# Old item"
    And sweetclaude.yaml has framework installed_version "4.0.8-beta"
    When check_storage_lint runs against the project state
    Then the result contains at least 2 findings
    And the findings include id "storage-lint:cross-location-duplicate-id:ISSUE-001"
    And the findings include id "storage-lint:v3-files-present:backlog"
