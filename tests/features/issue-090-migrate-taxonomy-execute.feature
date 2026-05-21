Feature: Migration execution
  Execute the plan with atomic writes, crash safety, and idempotency.

  Background:
    Given a project directory with legacy taxonomy files
    And a valid MigrationPlan
    And a snapshot has been created

  # --- Happy path ---

  Scenario: Dry run prints plan without side effects
    When execute() is called with dry_run=True
    Then no files are written to disk
    And no files are deleted
    And no migration-state.yaml is created
    And taxonomy-collision-map.yaml is not locked
    And MigrationResult has zero counts

  Scenario: Dry run against partially-completed state prints full plan
    Given migration-state.yaml records 3 completed dests
    When execute() is called with dry_run=True
    Then the full plan is printed (all moves, not just remaining)
    And no files are written or deleted

  Scenario: Full execution migrates all files
    Given 3 BL files, 1 STORY file, 1 I file, 1 RM file, 1 MS file
    When execute() is called
    Then 3 ISSUE files are created from BL sources
    And 1 ISSUE file is created from the STORY source
    And 1 file is archived in backlog/archived/
    And 1 RM file is deleted (retired)
    And 1 MS file is restructured with YAML frontmatter
    And all source files are removed
    And migration-state.yaml has status "complete"

  Scenario: Dest file frontmatter matches plan's PlannedMove.frontmatter
    Given BL-042.md with depends_on [BL-040, STORY-015]
    And collision map has STORY-15 -> ISSUE-87
    And the plan remaps depends_on to ["ISSUE-040", "ISSUE-087"]
    When execute() is called
    Then ISSUE-042-*.md frontmatter depends_on is ["ISSUE-040", "ISSUE-087"]
    And the written frontmatter matches PlannedMove.frontmatter exactly

  Scenario: Dest file preserves body content
    Given BL-042.md with body "Build the widget."
    When execute() is called
    Then ISSUE-042-*.md body contains "Build the widget."

  # --- Directory creation ---

  Scenario: Execute creates target directories before writing
    Given no roadmap/issues/done/ directory exists
    And the plan routes BL-050 to roadmap/issues/done/
    When execute() is called
    Then roadmap/issues/done/ is created
    And ISSUE-050 is written there successfully

  # --- Retire action ---

  Scenario: Retire action deletes source with no dest file
    Given RM-001.md in the plan with action "retire"
    When execute() processes this move
    Then RM-001.md is deleted
    And no dest file is created
    And MigrationResult.retired is incremented

  # --- Atomic writes ---

  Scenario: Atomic write uses temp file in same directory as dest
    Given BL-042.md in the plan
    When execute() writes ISSUE-042-widget-builder.md
    Then the temp file is created in the same directory as the dest
    And the temp file is renamed to the final path

  # --- Crash safety: persist-before-delete ordering ---

  Scenario: Crash after write but before persist — rerun re-executes safely
    Given BL-042 dest file exists (written before simulated crash)
    But migration-state.yaml does not record it as complete
    When execute() is called
    Then the move is re-executed (dest overwritten with same content)
    And state is persisted
    And source is deleted

  Scenario: Crash after persist but before delete — rerun skips with leftover source
    Given migration-state.yaml records ISSUE-042 as complete
    And the source BL-042.md still exists (delete didn't happen before crash)
    When execute() is called
    Then the ISSUE-042 move is skipped
    And BL-042.md remains as a harmless leftover

  # --- Idempotency ---

  Scenario: Rerun skips already-completed moves by dest path
    Given migration-state.yaml records ISSUE-042 dest as complete
    And the dest file exists on disk
    When execute() is called with a plan containing ISSUE-042
    Then the ISSUE-042 move is skipped
    And no file is written or deleted for it

  # --- Hash verification ---

  Scenario: Source file changed since plan aborts the entire run
    Given BL-042.md was modified after plan() was called
    And the source_hash in PlannedMove no longer matches
    When execute() processes this move
    Then it aborts the entire run (not just this move)
    And no subsequent moves are processed
    And migration-state.yaml status is set to "failed"

  Scenario: rewrite-refs verifies pre-write content when dest exists
    Given MS-007 was restructured in a prior move in this run
    And a rewrite-refs PlannedMove exists for MS-007
    When execute() processes the rewrite-refs move
    Then it reads the current dest content for verification
    And proceeds with the rewrite

  Scenario: rewrite-refs falls back to source hash when dest does not exist
    Given an MS-007 rewrite-refs move where no prior restructure ran in this session
    And the dest file does not exist yet
    When execute() processes the rewrite-refs move
    Then it verifies the source file hash instead
    And proceeds with writing directly

  Scenario: rewrite-refs source hash fallback aborts on mismatch
    Given an MS-007 rewrite-refs move where dest does not exist
    And the source file has been modified since plan time
    When execute() processes the rewrite-refs move
    Then it aborts the entire run

  # --- Collision map ---

  Scenario: Collision map is locked when execute begins
    Given taxonomy-collision-map.yaml exists without locked flag
    When execute() begins
    Then taxonomy-collision-map.yaml is updated with "locked: true"

  Scenario: Execute aborts if collision map file is missing
    Given taxonomy-collision-map.yaml was deleted after plan() completed
    When execute() attempts to lock the collision map
    Then it aborts with an error about missing collision map

  # --- Migration state ---

  Scenario: Snapshot path recorded in migration state
    Given snapshot at ".sweetclaude/state/backups/snap-001.tar.gz"
    When execute() begins
    Then migration-state.yaml contains the snapshot path

  Scenario: last_updated advances between moves
    Given a plan with 3 moves
    When execute() processes all 3 moves
    Then migration-state.yaml last_updated is different after move 3 than after move 1

  Scenario: completed_moves does not include retire moves
    Given a plan with 2 migrate moves and 1 retire move
    When execute() completes
    Then completed_moves has 2 entries (not 3)
    And MigrationResult.retired is 1

  Scenario: MigrationResult built from in-memory data
    Given 5 migrate, 2 archive, 1 retire, 1 restructure, 2 rewrite-refs moves
    When execute() completes
    Then MigrationResult.migrated is 5
    And MigrationResult.archived is 2
    And MigrationResult.retired is 1
    And MigrationResult.restructured is 1
    And MigrationResult.refs_rewritten is 2
    And MigrationResult.state_path points to migration-state.yaml on disk

  # --- Plan/project mismatch ---

  Scenario: Execute rejects plan with dest paths outside current project
    Given a plan built for project A
    When execute() is called in project B
    Then it aborts because dest paths are not relative to project B
