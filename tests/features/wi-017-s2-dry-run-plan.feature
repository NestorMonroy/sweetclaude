# WI-017 S2 — Dry-run plan engine
# Extend the migrator's plan so it recognizes typed-backlog dirs, top-level
# old-prefix files, and the bespoke EPIC-NNN/US-* tree, and emits a complete,
# human-approvable plan with ZERO writes to the project tree.

Feature: Migration dry-run produces a complete approvable plan for all legacy shapes
  As the SweetClaude migrator
  I want a dry-run that maps every legacy work item to its v4 id and location,
  records legacy ids, lists reference edits, and a migration map — writing nothing
  So that a typed-legacy / bespoke project can be migrated safely and reviewably

  Background:
    Given a project whose product base contains a mix of legacy shapes
    And the dry-run is invoked (no files may be written)

  Scenario: Typed backlog dirs are planned for migration
    Given "backlog/stories/STORY-024-parallel-run.md" with frontmatter id "STORY-024"
    And "backlog/debt/DEBT-001-creds.md" with frontmatter id "DEBT-001" type "tech-debt"
    When the dry-run plan is built
    Then the plan contains a move for "STORY-024" with a new id matching "ISSUE-\d+"
    And the plan contains a move for "DEBT-001" with a new id matching "ISSUE-\d+"
    And each such move records legacy_id equal to the original id
    And each destination is under the standard v4 backlog layout, not a typed subdir

  Scenario: Top-level old-prefix files are planned for migration
    Given "BL-005-product-brief.md" with frontmatter id "BL-005" at the product base root
    When the dry-run plan is built
    Then the plan contains a move for "BL-005" with a new id matching "ISSUE-\d+"

  Scenario: Bespoke epics map to EP with number preserved
    Given "stories/EPIC-003/EPIC-003.md" with no frontmatter
    When the dry-run plan is built
    Then the plan maps "EPIC-003" to "EP-003"
    And the move records legacy_id "EPIC-003"

  Scenario: Bespoke user stories map to ISSUE and re-link to their epic's new id
    Given "stories/EPIC-003/EPIC-003.md" with no frontmatter
    And "stories/EPIC-003/US-DM-002.md" with no frontmatter
    When the dry-run plan is built
    Then the plan maps "US-DM-002" to a new id matching "ISSUE-\d+"
    And the planned frontmatter for that story sets epic to the new epic id "EP-003"

  Scenario: Milestones and sprints are left unchanged
    Given "milestones/MS-001-core.md" with frontmatter id "MS-001"
    And "sprints/SP-001-hardening.md" with frontmatter id "SP-001"
    When the dry-run plan is built
    Then there is no id remap entry that changes "MS-001"
    And there is no id remap entry that changes "SP-001"

  Scenario: The id remap is bijective and deterministic
    Given a product base with several typed-dir, top-level, and bespoke work items
    When the dry-run plan is built twice
    Then both runs produce identical id remaps
    And every new ISSUE/EP id is unique across the plan
    And no two legacy ids map to the same new id

  Scenario: New ISSUE numbers continue past existing ISSUE ids
    Given an existing "backlog/ISSUE-050-existing.md" with frontmatter id "ISSUE-050"
    And a typed-dir "backlog/stories/STORY-001-x.md" with id "STORY-001"
    When the dry-run plan is built
    Then the new id assigned to "STORY-001" is greater than "ISSUE-050"
    And "ISSUE-050" is not remapped

  Scenario: Reference edits are listed for old-id mentions
    Given "stories/EPIC-003/EPIC-003.md" whose body mentions "US-DM-002"
    And "stories/EPIC-003/US-DM-002.md" with no frontmatter
    When the dry-run plan is built
    Then the plan lists a reference edit in "stories/EPIC-003/EPIC-003.md" replacing "US-DM-002" with its new id

  Scenario: A migration map (old -> new) is included in the plan
    When the dry-run plan is built
    Then the plan includes a migration map entry for every remapped work item
    And each entry has the original id, the new id, and the source path

  Scenario: Real duplicates are surfaced, backups are not blockers
    Given two real files "backlog/stories/STORY-007-a.md" and "backlog/stories/STORY-007-b.md" both id "STORY-007"
    And a backup "backlog/stories/STORY-007-a.bold-backup-1.md" id "STORY-007"
    When the dry-run plan is built
    Then the plan flags "STORY-007" as a real duplicate requiring a decision
    And the backup file is not part of the plan

  Scenario: Low-confidence Tier B inferences are flagged
    Given "stories/EPIC-009/US-XX-005.md" with no frontmatter and no H1 title
    When the dry-run plan is built
    Then the planned story entry for "US-XX-005" is flagged as a low-confidence inference

  Scenario: The dry-run writes nothing to the project tree
    Given a snapshot of every file path and content hash under the product base
    When the dry-run plan is built
    Then the product base is byte-for-byte identical to the snapshot
    And no new files exist anywhere under the project directory except under an allowed plan-output location in .sweetclaude/
