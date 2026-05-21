"""
Tests for snapshot and rollback — Feature: Snapshot and rollback
Translates: tests/features/issue-090-migrate-taxonomy-snapshot.feature
"""
import os
import sys
import tarfile
import time
import yaml
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import create_snapshot, verify_snapshot, rollback

from fixtures.migrate_taxonomy_fixtures import (
    backlog_dir,
    milestones_dir,
    state_dir,
    backups_dir,
    migration_state_path,
    project_dir,  # noqa: F401 — pytest fixture
)


# ---------------------------------------------------------------------------
# Scenario: Snapshot creates tarball of migration-relevant paths
# ---------------------------------------------------------------------------

class TestSnapshotCreatesTarball:
    def test_snapshot_creates_tarball_in_backups_dir(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n")
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        (ms / "MS-007.md").write_text("# MS-007\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl), str(ms)],
        )

        assert snap is not None
        snap_path = project_dir / snap if not os.path.isabs(str(snap)) else snap
        assert str(snap_path).endswith(".tar.gz") or str(snap).endswith(".tar.gz")

    def test_snapshot_tarball_contains_source_files(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        snap_path = str(snap)
        with tarfile.open(snap_path, "r:gz") as tf:
            names = tf.getnames()
        assert any("BL-001-foo.md" in n for n in names)


# ---------------------------------------------------------------------------
# Scenario: Snapshot creates backups directory if it does not exist
# ---------------------------------------------------------------------------

class TestSnapshotCreatesBackupsDirectory:
    def test_snapshot_creates_backups_dir_if_missing(self, project_dir):
        backups = backups_dir(project_dir)
        assert not backups.exists()

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        assert backups.exists()
        assert backups.is_dir()

    def test_snapshot_tarball_is_written_in_backups_dir(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        snap_path = str(snap)
        assert str(backups_dir(project_dir)) in snap_path


# ---------------------------------------------------------------------------
# Scenario: Snapshot with non-existent base_path skips it gracefully
# ---------------------------------------------------------------------------

class TestSnapshotSkipsMissingBasePath:
    def test_missing_base_path_skips_with_warning(self, project_dir):
        import warnings

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        nonexistent = project_dir / "does-not-exist"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            snap = create_snapshot(
                project_dir=str(project_dir),
                base_paths=[str(bl), str(nonexistent)],
            )

        assert snap is not None
        assert any(
            "does-not-exist" in str(w.message) or "skip" in str(w.message).lower()
            for w in caught
        )

    def test_tarball_contains_only_existing_paths(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        nonexistent = project_dir / "does-not-exist"

        import warnings
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            snap = create_snapshot(
                project_dir=str(project_dir),
                base_paths=[str(bl), str(nonexistent)],
            )

        snap_path = str(snap)
        with tarfile.open(snap_path, "r:gz") as tf:
            names = tf.getnames()
        assert any("BL-001" in n for n in names)


# ---------------------------------------------------------------------------
# Scenario: Snapshot path is recorded in migration state by execute
# ---------------------------------------------------------------------------

class TestSnapshotPathRecordedByExecute:
    def test_execute_records_snapshot_path_in_migration_state(self, project_dir):
        from migrate.migrate_taxonomy import build_plan, execute
        from fixtures.migrate_taxonomy_fixtures import collision_map_path

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("---\nid: BL-001\ntitle: Foo\nstatus: open\n---\n")
        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_text(yaml.safe_dump({}))

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )
        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert "snapshot_path" in state


# ---------------------------------------------------------------------------
# Scenario: verify_snapshot returns True for valid tarball
# ---------------------------------------------------------------------------

class TestVerifySnapshotValidTarball:
    def test_valid_tarball_returns_true(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        assert verify_snapshot(str(snap)) is True


# ---------------------------------------------------------------------------
# Scenario: verify_snapshot returns False for corrupted tarball
# ---------------------------------------------------------------------------

class TestVerifySnapshotCorruptedTarball:
    def test_truncated_tarball_returns_false(self, project_dir):
        backups = backups_dir(project_dir)
        backups.mkdir(parents=True, exist_ok=True)
        corrupt = backups / "corrupt-snap.tar.gz"
        corrupt.write_bytes(b"PK not a valid gzip tarball \x00\x01\x02")

        assert verify_snapshot(str(corrupt)) is False


# ---------------------------------------------------------------------------
# Scenario: Rollback restores from snapshot
# ---------------------------------------------------------------------------

class TestRollbackRestoresFromSnapshot:
    def test_rollback_restores_original_file_structure(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        original_file = bl / "BL-001-foo.md"
        original_file.write_text("# BL-001: Foo\nOriginal content.\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        # Simulate partial migration: file moved/deleted
        original_file.unlink()

        result = rollback(str(snap), project_dir=str(project_dir))

        assert result is True
        assert original_file.exists()
        assert "Original content." in original_file.read_text()


# ---------------------------------------------------------------------------
# Scenario: Rollback with corrupted snapshot fails gracefully
# ---------------------------------------------------------------------------

class TestRollbackCorruptedSnapshot:
    def test_corrupted_snapshot_returns_false_no_files_modified(self, project_dir):
        backups = backups_dir(project_dir)
        backups.mkdir(parents=True, exist_ok=True)
        corrupt = backups / "corrupt-snap.tar.gz"
        corrupt.write_bytes(b"not a valid tarball at all")

        # Write a marker file to check it's not disturbed
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        marker = bl / "marker.md"
        marker.write_text("untouched\n")

        result = rollback(str(corrupt), project_dir=str(project_dir))

        assert result is False
        assert marker.exists()
        assert marker.read_text() == "untouched\n"


# ---------------------------------------------------------------------------
# Scenario: Old snapshots are pruned to retain most recent 5
# ---------------------------------------------------------------------------

class TestOldSnapshotsPruned:
    def test_six_snapshots_prunes_to_five_oldest_deleted(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        backups = backups_dir(project_dir)
        backups.mkdir(parents=True, exist_ok=True)

        # Create 6 existing snapshots with distinct timestamps
        existing_snaps = []
        for i in range(6):
            snap_name = f"snap-2026-05-{i + 1:02d}T000000.tar.gz"
            snap_path = backups / snap_name
            snap_path.write_bytes(b"placeholder")
            existing_snaps.append(snap_path)
            time.sleep(0.01)  # ensure distinct mtimes

        create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        remaining = list(backups.glob("*.tar.gz"))
        assert len(remaining) == 5

    def test_oldest_snapshot_is_deleted_not_newest(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        backups = backups_dir(project_dir)
        backups.mkdir(parents=True, exist_ok=True)

        oldest = backups / "snap-2026-01-01T000000.tar.gz"
        oldest.write_bytes(b"placeholder")

        # Create 5 more newer snapshots
        for i in range(2, 7):
            snap = backups / f"snap-2026-05-{i:02d}T000000.tar.gz"
            snap.write_bytes(b"placeholder")

        create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(bl)],
        )

        remaining = list(backups.glob("*.tar.gz"))
        remaining_names = [p.name for p in remaining]
        # The oldest (January) should be pruned
        assert oldest.name not in remaining_names
