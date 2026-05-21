Feature: Snapshot and rollback
  Extracted snapshot lifecycle for safe migration with recovery.

  Scenario: Snapshot creates tarball of migration-relevant paths
    Given a project directory with files in backlog/ and milestones/
    When create_snapshot() is called with those base paths
    Then a tarball is created in .sweetclaude/state/backups/
    And it contains the files from the specified paths

  Scenario: Snapshot creates backups directory if it does not exist
    Given .sweetclaude/state/backups/ does not exist
    When create_snapshot() is called
    Then the directory is created
    And the tarball is written there

  Scenario: Snapshot with non-existent base_path skips it gracefully
    Given base_paths includes a directory that does not exist
    When create_snapshot() is called
    Then it skips the missing path with a warning
    And the tarball contains only the existing paths

  Scenario: Snapshot path is recorded in migration state by execute
    Given execute() has been called with a snapshot path
    Then migration-state.yaml contains the snapshot_path field

  Scenario: verify_snapshot returns True for valid tarball
    Given a valid snapshot tarball
    When verify_snapshot() is called
    Then it returns True

  Scenario: verify_snapshot returns False for corrupted tarball
    Given a truncated snapshot tarball
    When verify_snapshot() is called
    Then it returns False

  Scenario: Rollback restores from snapshot
    Given a snapshot tarball exists
    And migration has partially executed (some files moved)
    When rollback() is called with the snapshot path
    Then the original file structure is restored
    And the return value is True

  Scenario: Rollback with corrupted snapshot fails gracefully
    Given a corrupted snapshot tarball
    When rollback() is called
    Then it returns False
    And no files are modified

  Scenario: Old snapshots are pruned to retain most recent 5
    Given 6 snapshot tarballs already exist with distinct timestamps
    When create_snapshot() is called
    Then only 5 snapshots remain
    And the oldest tarball by timestamp is the one deleted
