# WI-017 S3 — Execute the migration plan safely
# Apply the S2 dry-run plan to the project: relocate + re-id work items, write
# Tier A/B frontmatter, rewrite references, move paired .feature files, write a
# MIGRATION-MAP, all behind a snapshot with working rollback. Reuses the existing
# create_snapshot/rollback infrastructure; the execute path now applies the S2 plan.

Feature: Migration execution applies the S2 plan with snapshot and rollback
  As the SweetClaude migrator
  I want execute() to transform a typed-legacy/bespoke project into v4 layout
  exactly as the dry-run planned, behind a snapshot I can roll back
  So that a parked project can be migrated safely and reversibly

  Background:
    Given a project with typed-dir, top-level, and bespoke legacy work items
    And no unresolved real-duplicate conflicts

  Scenario: A snapshot is created before any write
    When the migration is executed
    Then a snapshot archive exists under the project's backups location
    And the snapshot was created before any product file was modified

  Scenario: Typed-dir work items are relocated and re-identified
    Given "backlog/stories/STORY-024-parallel-run.md" with frontmatter id "STORY-024" status "backlog"
    When the migration is executed
    Then "backlog/stories/STORY-024-parallel-run.md" no longer exists
    And a file exists under "backlog/" whose frontmatter id matches "ISSUE-\d+"
    And that file's frontmatter records legacy_id "STORY-024"
    And that file's frontmatter status is the remapped value (not "backlog")
    And no typed backlog subdirectory (stories/bugs/debt/chores) remains under backlog

  Scenario: Bespoke epics and their stories are migrated and re-linked
    Given "stories/EPIC-003/EPIC-003.md" with no frontmatter
    And "stories/EPIC-003/US-DM-002.md" with no frontmatter
    When the migration is executed
    Then a file with frontmatter id "EP-003" exists under "roadmap/epics/"
    And a migrated story file exists whose frontmatter id matches "ISSUE-\d+"
    And that story's frontmatter epic field equals "EP-003"
    And the synthesized story frontmatter has id, type, title, and status fields

  Scenario: A paired .feature file moves alongside its story
    Given "stories/EPIC-003/US-DM-002.md" and "stories/EPIC-003/US-DM-002.feature"
    When the migration is executed
    Then "stories/EPIC-003/US-DM-002.feature" no longer exists at its old path
    And a ".feature" file exists alongside the migrated story sharing its new id stem

  Scenario: References to old ids are rewritten everywhere
    Given a body in one file mentioning "US-DM-002"
    And a frontmatter epic field "EPIC-003" in another file
    When the migration is executed
    Then no migrated work-item file contains the old id "US-DM-002" outside legacy_id
    And the frontmatter epic reference now uses the new epic id

  Scenario: A migration map is written
    When the migration is executed
    Then a "MIGRATION-MAP.md" exists under the product base
    And it lists every migrated item as old id to new id

  Scenario: Milestones and sprints are untouched
    Given "milestones/MS-001-core.md" and "sprints/SP-001-x.md"
    When the migration is executed
    Then "milestones/MS-001-core.md" still exists unchanged
    And "sprints/SP-001-x.md" still exists unchanged

  Scenario: After migration the project is no longer a typed-legacy layout
    When the migration is executed
    Then characterizing the project reports no typed backlog dirs
    And characterizing the project reports zero old-prefix work items
    And characterizing the project reports no duplicate ids

  Scenario: Rollback restores the project byte-for-byte
    Given a content-hash snapshot of every file under the project before migration
    When the migration is executed
    And the migration is then rolled back from its snapshot
    Then every file under the project matches the pre-migration content hashes
    And no file created by the migration remains

  Scenario: Execution refuses when unresolved real duplicates exist
    Given two real files "backlog/stories/STORY-007-a.md" and "backlog/stories/STORY-007-b.md" both id "STORY-007"
    When the migration is executed
    Then the result is not ok
    And the unresolved duplicate "STORY-007" is reported
    And no product file was modified

  Scenario: Re-running execution on an already-migrated project is a safe no-op
    Given a project already migrated to v4 (only ISSUE/EP/MS/SP ids, no typed dirs)
    When the migration is executed again
    Then no work-item files are moved or modified
    And the result is ok

  Scenario: Post-execution integrity verification passes
    When the migration is executed
    Then every old id in the migration map resolves to exactly one new file
    And every migrated work-item id is unique
    And every migrated work item has present, canonical frontmatter
