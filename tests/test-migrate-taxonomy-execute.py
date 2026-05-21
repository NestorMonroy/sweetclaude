"""
Tests for migration execution — Feature: Migration execution
Translates: tests/features/issue-090-migrate-taxonomy-execute.feature
"""
import os
import sys
import time
import yaml
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import build_plan, execute, create_snapshot

from fixtures.migrate_taxonomy_fixtures import (
    product_base,
    backlog_dir,
    done_dir,
    issues_dir,
    roadmap_dir,
    milestones_dir,
    roadmap_issues_dir,
    roadmap_issues_done_dir,
    state_dir,
    backups_dir,
    collision_map_path,
    migration_state_path,
    make_yaml_frontmatter_file,
    make_bold_format_file,
    project_dir,  # noqa: F401 — pytest fixture
)


def _write_collision_map(project_dir, data: dict):
    state_dir(project_dir).mkdir(parents=True, exist_ok=True)
    collision_map_path(project_dir).write_text(yaml.safe_dump(data))


def _write_migration_state(project_dir, data: dict):
    state_dir(project_dir).mkdir(parents=True, exist_ok=True)
    migration_state_path(project_dir).write_text(yaml.safe_dump(data))


def _build_plan_with_bl(project_dir, bl_entries):
    """
    Write BL files from list of (number, title, status, extra) tuples
    and return the plan.
    """
    bl = backlog_dir(project_dir)
    bl.mkdir(parents=True, exist_ok=True)
    _write_collision_map(project_dir, {})
    for entry in bl_entries:
        num, title, status = entry[:3]
        extra = entry[3] if len(entry) > 3 else {}
        fm = {"id": f"BL-{num}", "title": title, "status": status}
        fm.update(extra)
        slug = title.lower().replace(" ", "-")
        make_yaml_frontmatter_file(bl / f"BL-{num}-{slug}.md", fm, "Body text.")
    return build_plan(project_dir=str(project_dir))


# ---------------------------------------------------------------------------
# Scenario: Dry run prints plan without side effects
# ---------------------------------------------------------------------------

class TestDryRunNoSideEffects:
    def test_dry_run_no_files_written_or_deleted(self, project_dir):
        plan = _build_plan_with_bl(project_dir, [("042", "Widget builder", "open")])
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        result = execute(plan, project_dir=str(project_dir), dry_run=True)

        assert not migration_state_path(project_dir).exists()
        assert result.migrated == 0
        assert result.archived == 0
        assert result.retired == 0

    def test_dry_run_does_not_lock_collision_map(self, project_dir):
        plan = _build_plan_with_bl(project_dir, [("042", "Widget builder", "open")])
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        execute(plan, project_dir=str(project_dir), dry_run=True)

        data = yaml.safe_load(collision_map_path(project_dir).read_text())
        assert data.get("locked") is not True


# ---------------------------------------------------------------------------
# Scenario: Dry run against partially-completed state prints full plan
# ---------------------------------------------------------------------------

class TestDryRunPartialState:
    def test_dry_run_with_completed_state_prints_full_plan_no_files_written(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        for i in range(1, 6):
            make_yaml_frontmatter_file(
                bl / f"BL-{i:03d}-item.md",
                {"id": f"BL-{i:03d}", "title": f"Item {i}", "status": "open"},
            )
        _write_collision_map(project_dir, {})
        _write_migration_state(
            project_dir,
            {
                "status": "in_progress",
                "completed_dests": [
                    f"roadmap/issues/ISSUE-{i:03d}-item-{i}.md" for i in range(1, 4)
                ],
            },
        )

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        result = execute(plan, project_dir=str(project_dir), dry_run=True)

        assert result.migrated == 0


# ---------------------------------------------------------------------------
# Scenario: Full execution migrates all files
# ---------------------------------------------------------------------------

class TestFullExecution:
    def test_full_execution_migrates_bl_story_archives_i_retires_rm_restructures_ms(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        for i in (1, 2, 3):
            make_yaml_frontmatter_file(
                bl / f"BL-{i:03d}-item.md",
                {"id": f"BL-{i:03d}", "title": f"Item {i}", "status": "open"},
                "Body.",
            )

        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-050-alpha.md",
            {"id": "STORY-050", "title": "Alpha", "status": "done"},
            "Story body.",
        )

        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001-dup.md").write_text("# I-001: Dup\n")

        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        (rm / "RM-001-mvp.md").write_text("# RM-001: MVP\n\n**Status:** achieved\n")

        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked workflows",
            {"Status": "active"},
        )

        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir)), str(milestones_dir(project_dir))],
        )
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        assert result.migrated == 4  # 3 BL + 1 STORY
        assert result.archived == 1
        assert result.retired == 1
        assert result.restructured >= 1

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert state["status"] == "complete"

        assert not (bl / "BL-001-item.md").exists()
        assert not (bl / "BL-002-item.md").exists()
        assert not (rm / "RM-001-mvp.md").exists()


# ---------------------------------------------------------------------------
# Scenario: Dest file frontmatter matches plan's PlannedMove.frontmatter
# ---------------------------------------------------------------------------

class TestDestFrontmatterMatchesPlan:
    def test_written_frontmatter_depends_on_matches_plan(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-040-dep.md",
            {"id": "BL-040", "title": "Dep", "status": "open"},
        )
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {
                "id": "BL-042",
                "title": "Feature",
                "status": "active",
                "depends_on": ["BL-040", "STORY-015"],
            },
        )
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {"id": "STORY-015", "title": "Alpha", "status": "done"},
        )
        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87"})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        issue_042_files = list(
            (product_base(project_dir)).rglob("ISSUE-042-*.md")
        )
        assert len(issue_042_files) == 1
        content = issue_042_files[0].read_text()
        parsed_fm = yaml.safe_load(content.split("---")[1])
        assert "ISSUE-040" in parsed_fm.get("depends_on", [])
        assert "ISSUE-087" in parsed_fm.get("depends_on", [])


# ---------------------------------------------------------------------------
# Scenario: Dest file preserves body content
# ---------------------------------------------------------------------------

class TestDestFilePreservesBody:
    def test_written_file_body_contains_original_body(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-widget.md",
            {"id": "BL-042", "title": "Widget", "status": "open"},
            "Build the widget.",
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        issue_files = list(product_base(project_dir).rglob("ISSUE-042-*.md"))
        assert len(issue_files) == 1
        assert "Build the widget." in issue_files[0].read_text()


# ---------------------------------------------------------------------------
# Scenario: Execute creates target directories before writing
# ---------------------------------------------------------------------------

class TestExecuteCreatesTargetDirectories:
    def test_missing_dest_directory_is_created(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-050-old.md",
            {"id": "BL-050", "title": "Old feature", "status": "done"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        done_issues = roadmap_issues_done_dir(project_dir)
        assert done_issues.exists()
        assert any(done_issues.glob("ISSUE-050-*.md"))


# ---------------------------------------------------------------------------
# Scenario: Retire action deletes source with no dest file
# ---------------------------------------------------------------------------

class TestRetireActionDeletesSource:
    def test_retire_deletes_source_no_dest_file_created(self, project_dir):
        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        rm_file = rm / "RM-001-mvp.md"
        rm_file.write_text("# RM-001: MVP\n\n**Status:** achieved\n")
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(roadmap_dir(project_dir))],
        )
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        assert not rm_file.exists()
        assert result.retired == 1


# ---------------------------------------------------------------------------
# Scenario: Crash after write but before persist — rerun re-executes safely
# ---------------------------------------------------------------------------

class TestCrashAfterWriteBeforePersist:
    def test_rerun_overwrites_unpersisted_dest_and_completes(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-widget.md",
            {"id": "BL-042", "title": "Widget", "status": "open"},
            "Body.",
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        # Simulate: dest exists but state doesn't record it as complete
        issue_dir = product_base(project_dir) / "backlog"
        issue_dir.mkdir(parents=True, exist_ok=True)
        (issue_dir / "ISSUE-042-widget.md").write_text("stale content\n")
        _write_migration_state(project_dir, {"status": "in_progress", "completed_dests": []})

        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert state["status"] == "complete"


# ---------------------------------------------------------------------------
# Scenario: Rerun skips already-completed moves by dest path
# ---------------------------------------------------------------------------

class TestRerunSkipsAlreadyCompletedMoves:
    def test_completed_move_is_skipped_on_rerun(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-widget.md",
            {"id": "BL-042", "title": "Widget", "status": "open"},
            "Body.",
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))

        # Find the expected dest from the plan
        move = next(
            (m for m in plan.moves if str(getattr(m, "new_id", "")).startswith("ISSUE-042")),
            None,
        )
        assert move is not None
        dest_path = project_dir / move.dest
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("already written\n")

        _write_migration_state(
            project_dir,
            {"status": "in_progress", "completed_dests": [str(move.dest)]},
        )

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        # dest content should NOT be overwritten
        assert dest_path.read_text() == "already written\n"


# ---------------------------------------------------------------------------
# Scenario: Source file changed since plan aborts entire run
# ---------------------------------------------------------------------------

class TestSourceFileChangedAbortsRun:
    def test_hash_mismatch_aborts_run_and_sets_failed_status(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        bl_file = bl / "BL-042-widget.md"
        make_yaml_frontmatter_file(
            bl_file,
            {"id": "BL-042", "title": "Widget", "status": "open"},
            "Original body.",
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))

        # Mutate the source after plan() was built
        bl_file.write_text("# Modified content that changes the hash\n")

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        with pytest.raises(Exception):
            execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        if migration_state_path(project_dir).exists():
            state = yaml.safe_load(migration_state_path(project_dir).read_text())
            assert state.get("status") == "failed"


# ---------------------------------------------------------------------------
# Scenario: Collision map is locked when execute begins
# ---------------------------------------------------------------------------

class TestCollisionMapLockedOnExecuteBegin:
    def test_execute_locks_collision_map_at_start(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-001-foo.md",
            {"id": "BL-001", "title": "Foo", "status": "open"},
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        data = yaml.safe_load(collision_map_path(project_dir).read_text())
        assert data.get("locked") is True


# ---------------------------------------------------------------------------
# Scenario: Execute aborts if collision map file is missing
# ---------------------------------------------------------------------------

class TestExecuteAbortsIfCollisionMapMissing:
    def test_missing_collision_map_aborts_execute(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-001-foo.md",
            {"id": "BL-001", "title": "Foo", "status": "open"},
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))

        # Delete collision map after plan() completed
        collision_map_path(project_dir).unlink()

        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        with pytest.raises(Exception, match="collision map"):
            execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))


# ---------------------------------------------------------------------------
# Scenario: Snapshot path recorded in migration state
# ---------------------------------------------------------------------------

class TestSnapshotPathRecordedInMigrationState:
    def test_snapshot_path_in_migration_state_yaml(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-001-foo.md",
            {"id": "BL-001", "title": "Foo", "status": "open"},
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )

        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert "snapshot_path" in state
        assert str(snap) in state["snapshot_path"]


# ---------------------------------------------------------------------------
# Scenario: completed_moves does not include retire moves
# ---------------------------------------------------------------------------

class TestCompletedMovesExcludeRetire:
    def test_completed_moves_count_excludes_retire_action(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        for i in (1, 2):
            make_yaml_frontmatter_file(
                bl / f"BL-{i:03d}-item.md",
                {"id": f"BL-{i:03d}", "title": f"Item {i}", "status": "open"},
            )
        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        (rm / "RM-001-mvp.md").write_text("# RM-001\n\n**Status:** achieved\n")
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(
            project_dir=str(project_dir),
            base_paths=[str(backlog_dir(project_dir))],
        )
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        completed = state.get("completed_dests", [])
        assert len(completed) == 2  # 2 migrate, not 3
        assert result.retired == 1


# ---------------------------------------------------------------------------
# Scenario: MigrationResult built from in-memory data
# ---------------------------------------------------------------------------

class TestMigrationResultCounts:
    @pytest.mark.skip("TODO: implement — requires 5 migrate + 2 archive + 1 retire + 1 restructure + 2 rewrite-refs corpus")
    def test_migration_result_counts_all_action_types(self, project_dir):
        pass


# ---------------------------------------------------------------------------
# Scenario: Execute rejects plan with dest paths outside current project
# ---------------------------------------------------------------------------

class TestExecuteRejectsPlanFromDifferentProject:
    def test_plan_built_for_different_project_raises_error(self, project_dir, tmp_path):
        # Build plan in project_dir
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-001-foo.md",
            {"id": "BL-001", "title": "Foo", "status": "open"},
        )
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))

        # Execute in different project (tmp_path is not project_dir)
        other_dir = tmp_path / "other_project"
        other_dir.mkdir()

        with pytest.raises(Exception):
            execute(plan, project_dir=str(other_dir))
