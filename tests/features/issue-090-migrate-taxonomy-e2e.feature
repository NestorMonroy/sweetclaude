Feature: End-to-end migration
  Full pipeline from validate through verify on realistic corpus.

  Scenario: Full migration of a mixed-format corpus
    Given a project with:
      | file                          | format         | status    |
      | backlog/BL-001-foo.md         | markdown-bold  | done      |
      | backlog/BL-042-bar.md         | yaml           | active    |
      | backlog/BL-070-baz.md         | yaml           | new       |
      | backlog/BL-082-promoted.md    | markdown-bold  | promoted  |
      | backlog/done/STORY-015-a.md   | yaml           | done      |
      | backlog/done/STORY-016-b.md   | yaml           | done      |
      | issues/I-001-dup.md           | markdown-bold  | open      |
      | roadmap/RM-001-mvp.md         | markdown-bold  | achieved  |
      | milestones/MS-007-tracked.md  | markdown-bold  | active    |
      | backlog/EP-001-taxonomy.md    | yaml           | active    |
    And BL-042 has epic EP-001 and depends_on [BL-001]
    And BL-015 exists (collision with STORY-015)
    When the full pipeline runs: validate → plan → snapshot → execute → verify
    Then validate returns no errors
    And the plan contains:
      | old_id    | new_id    | action       | dest_dir              |
      | BL-001    | ISSUE-001 | migrate      | roadmap/issues/done/  |
      | BL-042    | ISSUE-042 | migrate      | roadmap/issues/       |
      | BL-070    | ISSUE-070 | migrate      | backlog/              |
      | BL-082    | ISSUE-082 | migrate      | backlog/              |
      | STORY-015 | ISSUE-87  | migrate      | roadmap/issues/done/  |
      | STORY-016 | ISSUE-016 | migrate      | roadmap/issues/done/  |
      | I-001     | I-001     | archive      | backlog/archived/     |
      | RM-001    | RM-001    | retire       | (deleted)             |
      | MS-007    | MS-007    | restructure  | roadmap/milestones/   |
      | EP-001    | EP-001    | restructure  | roadmap/epics/        |
    And STORY-015 collision is recorded in taxonomy-collision-map.yaml
    And execute completes with status "complete"
    And verify returns no errors
    And no BL/STORY/RM/I files remain in active directories
    And MS-007 has YAML frontmatter
    And ISSUE-042 frontmatter has depends_on ["ISSUE-001"]
    And ISSUE-082 frontmatter has status "superseded" and superseded_by "EP-009"
    And ISSUE-87 frontmatter has migrated_from "STORY-15"

  Scenario: Migration with spike reports and body refs
    Given a project with:
      | file                                      | format |
      | backlog/BL-027-thing.md                   | yaml   |
      | backlog/spike-reports/spike-BL-016-gs.md  | yaml   |
    And spike-BL-016 body contains "Actionable items: BL-027"
    When the full pipeline runs
    Then spike-BL-016 is migrated as type "spike"
    And its body has "BL-027" rewritten to "ISSUE-027"

  Scenario: Corpus with only I-N files (all archives, zero migrates)
    Given a project with only I-001.md and I-002.md in issues/
    When the full pipeline runs
    Then both are archived to backlog/archived/
    And MigrationResult.migrated is 0
    And MigrationResult.archived is 2
    And verify returns no errors

  Scenario: Interrupted migration resumes from last completed move
    Given a project with 5 BL files
    And migration was interrupted after completing 3 moves
    And migration-state.yaml records 3 completed dests
    When execute() is called again with the same plan
    Then only the remaining 2 moves are executed
    And migration-state.yaml ends with status "complete"

  Scenario: Rollback after failed migration restores original state
    Given a project with 5 BL files
    And migration fails mid-execution (e.g., hash mismatch on file 3)
    When rollback() is called with the snapshot path from migration-state
    Then all original files are restored
    And no partially-migrated files remain

  Scenario: Plan on partially-executed corpus uses locked collision map
    Given a project where migration completed 3 of 5 moves
    And taxonomy-collision-map.yaml is locked
    When plan() is called again
    Then the locked collision map is used
    And the plan contains only the 2 remaining unmigrated source files
    And a warning is emitted about reduced source count

  Scenario: Pipeline with persisted collision map from prior aborted run
    Given taxonomy-collision-map.yaml exists from a previous aborted migration
    And migration-state.yaml does not exist (was cleaned up)
    When the full pipeline runs: validate → plan → snapshot → execute → verify
    Then plan() reuses the persisted collision map
    And the migration completes successfully

  Scenario: Case-insensitive status and priority through full pipeline
    Given BL-084.md with bold-format Status "BACKLOG" and Priority "SPIKE"
    When the full pipeline runs
    Then ISSUE-084 frontmatter has status "new" and priority "P3"
