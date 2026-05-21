"""
Tests for end-to-end migration — Feature: End-to-end migration
Translates: tests/features/issue-090-migrate-taxonomy-e2e.feature
"""
import os
import sys
import yaml
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import (
    validate,
    build_plan,
    create_snapshot,
    execute,
    verify,
)

from fixtures.migrate_taxonomy_fixtures import (
    product_base,
    backlog_dir,
    done_dir,
    spike_dir,
    issues_dir,
    roadmap_dir,
    milestones_dir,
    state_dir,
    collision_map_path,
    migration_state_path,
    make_yaml_frontmatter_file,
    make_bold_format_file,
    project_dir,  # noqa: F401 — pytest fixture
)


def _write_collision_map(project_dir, data: dict):
    state_dir(project_dir).mkdir(parents=True, exist_ok=True)
    collision_map_path(project_dir).write_text(yaml.safe_dump(data))


# ---------------------------------------------------------------------------
# Scenario: Full migration of a mixed-format corpus
# ---------------------------------------------------------------------------

class TestFullMigrationMixedFormatCorpus:
    def test_full_pipeline_validate_plan_snapshot_execute_verify(self, project_dir):
        # Write all source files
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)

        make_bold_format_file(
            bl / "BL-001-foo.md",
            "BL-001: Foo",
            {"Status": "DONE — 2026-05-01"},
        )
        make_yaml_frontmatter_file(
            bl / "BL-015-collision.md",
            {"id": "BL-015", "title": "Collision", "status": "open"},
        )
        make_yaml_frontmatter_file(
            bl / "BL-042-bar.md",
            {
                "id": "BL-042",
                "title": "Bar",
                "status": "active",
                "epic": "EP-001",
                "depends_on": ["BL-001"],
            },
        )
        make_yaml_frontmatter_file(
            bl / "BL-070-baz.md",
            {"id": "BL-070", "title": "Baz", "status": "new"},
        )
        make_bold_format_file(
            bl / "BL-082-promoted.md",
            "BL-082: Promoted",
            {"Status": "PROMOTED", "Promoted to": "EP-009 (v4.1)"},
        )
        make_yaml_frontmatter_file(
            bl / "EP-001-taxonomy.md",
            {"id": "EP-001", "title": "Taxonomy", "status": "active"},
        )

        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-a.md",
            {"id": "STORY-015", "title": "A", "status": "done"},
        )
        make_yaml_frontmatter_file(
            d / "STORY-016-b.md",
            {"id": "STORY-016", "title": "B", "status": "done"},
        )

        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001-dup.md").write_text("# I-001\n\n**Effort:** 3\n")

        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            rm / "RM-001-mvp.md",
            "RM-001: MVP",
            {"Status": "achieved"},
        )

        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked workflows",
            {"Status": "active"},
        )

        # --- Step 1: validate ---
        errors = validate(project_dir=str(project_dir))
        assert errors == [], f"validate() returned errors: {errors}"

        # --- Step 2: plan ---
        plan = build_plan(project_dir=str(project_dir))
        assert plan is not None

        new_ids = {getattr(m, "new_id", None) for m in plan.moves}
        assert "ISSUE-001" in new_ids
        assert "ISSUE-042" in new_ids
        assert "ISSUE-070" in new_ids
        assert "ISSUE-082" in new_ids
        assert "ISSUE-016" in new_ids

        # STORY-015 collides with BL-015, should be remapped to ISSUE-87
        assert "ISSUE-87" in new_ids or "ISSUE-087" in new_ids

        collision_map_file = collision_map_path(project_dir)
        assert collision_map_file.exists()
        data = yaml.safe_load(collision_map_file.read_text())
        assert "STORY-15" in data

        # --- Step 3: snapshot ---
        base_paths = [
            str(backlog_dir(project_dir)),
            str(milestones_dir(project_dir)),
            str(issues_dir(project_dir)),
            str(roadmap_dir(project_dir)),
        ]
        snap = create_snapshot(project_dir=str(project_dir), base_paths=base_paths)
        assert snap is not None

        # --- Step 4: execute ---
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert state["status"] == "complete"

        # Check no legacy files remain in active dirs
        for legacy in bl.rglob("BL-*.md"):
            assert False, f"Legacy BL file remains: {legacy}"
        for legacy in d.rglob("STORY-*.md"):
            assert False, f"Legacy STORY file remains: {legacy}"
        for legacy in rm.rglob("RM-*.md"):
            assert False, f"Legacy RM file remains: {legacy}"

        # Check MS-007 has YAML frontmatter
        ms_files = list(product_base(project_dir).rglob("MS-007-*.md"))
        assert len(ms_files) >= 1
        content = ms_files[0].read_text()
        assert content.startswith("---"), "MS-007 should have YAML frontmatter"

        # Check ISSUE-042 depends_on remapped
        issue_042_files = list(product_base(project_dir).rglob("ISSUE-042-*.md"))
        assert len(issue_042_files) == 1
        fm_text = issue_042_files[0].read_text().split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "ISSUE-001" in fm.get("depends_on", [])

        # Check ISSUE-082 has superseded status
        issue_082_files = list(product_base(project_dir).rglob("ISSUE-082-*.md"))
        assert len(issue_082_files) == 1
        fm_text = issue_082_files[0].read_text().split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm.get("status") == "superseded"
        assert fm.get("superseded_by") == "EP-009"

        # Check STORY-015 remapped to ISSUE-87 has migrated_from
        issue_87_files = list(product_base(project_dir).rglob("ISSUE-87-*.md")) + \
                         list(product_base(project_dir).rglob("ISSUE-087-*.md"))
        assert len(issue_87_files) >= 1
        fm_text = issue_87_files[0].read_text().split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm.get("migrated_from") in ("STORY-15", "STORY-015")

        # --- Step 5: verify ---
        verify_errors = verify(project_dir=str(project_dir))
        assert verify_errors == [], f"verify() returned errors: {verify_errors}"


# ---------------------------------------------------------------------------
# Scenario: Migration with spike reports and body refs
# ---------------------------------------------------------------------------

class TestMigrationWithSpikeReportsAndBodyRefs:
    def test_spike_bl_body_ref_rewritten_and_type_spike(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-027-thing.md",
            {"id": "BL-027", "title": "Thing", "status": "open"},
        )

        sd = spike_dir(project_dir)
        sd.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            sd / "spike-BL-016-gs.md",
            {"id": "spike-BL-016", "title": "GStack spike", "status": "done"},
            "Actionable items: BL-027",
        )

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(bl), str(sd)])
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        spike_files = list(product_base(project_dir).rglob("ISSUE-016-*.md"))
        assert len(spike_files) == 1

        content = spike_files[0].read_text()
        fm = yaml.safe_load(content.split("---")[1])
        assert fm.get("type") == "spike"
        assert "ISSUE-027" in content
        assert "BL-027" not in content


# ---------------------------------------------------------------------------
# Scenario: Corpus with only I-N files (all archives, zero migrates)
# ---------------------------------------------------------------------------

class TestCorpusOnlyIFiles:
    def test_only_i_files_archived_result_migrated_zero_archived_two(
        self, project_dir
    ):
        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001.md").write_text("# I-001\n")
        (iss / "I-002.md").write_text("# I-002\n")

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(iss)])
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        assert result.migrated == 0
        assert result.archived == 2

        arch = product_base(project_dir) / "backlog" / "archived"
        assert (arch / "I-001.md").exists()
        assert (arch / "I-002.md").exists()

        verify_errors = verify(project_dir=str(project_dir))
        assert verify_errors == []


# ---------------------------------------------------------------------------
# Scenario: Interrupted migration resumes from last completed move
# ---------------------------------------------------------------------------

class TestInterruptedMigrationResumes:
    def test_resume_executes_only_remaining_moves(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        for i in range(1, 6):
            make_yaml_frontmatter_file(
                bl / f"BL-{i:03d}-item.md",
                {"id": f"BL-{i:03d}", "title": f"Item {i}", "status": "open"},
                "Body.",
            )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(bl)])

        # Write state showing 3 already completed
        completed = []
        for m in plan.moves[:3]:
            dest_path = project_dir / m.dest
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text("---\nid: placeholder\ntitle: placeholder\ntype: enhancement\nstatus: active\ncreated: 2026-05-01\n---\n")
            completed.append(str(m.dest))

        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        migration_state_path(project_dir).write_text(
            yaml.safe_dump({
                "status": "in_progress",
                "completed_dests": completed,
                "snapshot_path": str(snap),
            })
        )

        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert state["status"] == "complete"
        assert result.migrated == 5


# ---------------------------------------------------------------------------
# Scenario: Rollback after failed migration restores original state
# ---------------------------------------------------------------------------

class TestRollbackAfterFailedMigration:
    def test_rollback_restores_all_original_files(self, project_dir):
        from migrate.migrate_taxonomy import rollback

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        original_files = {}
        for i in range(1, 6):
            f = bl / f"BL-{i:03d}-item.md"
            content = f"# BL-{i:03d}: Item {i}\nOriginal content {i}\n"
            f.write_text(content)
            original_files[f.name] = content

        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(bl)])

        # Simulate partial migration — move some files
        _write_collision_map(project_dir, {})
        plan = build_plan(project_dir=str(project_dir))
        for m in plan.moves[:3]:
            src = project_dir / m.source if hasattr(m, "source") else None
            if src and src.exists():
                src.unlink()

        rollback_result = rollback(str(snap), project_dir=str(project_dir))

        assert rollback_result is True
        for fname, content in original_files.items():
            restored = bl / fname
            assert restored.exists(), f"{fname} was not restored"


# ---------------------------------------------------------------------------
# Scenario: Plan on partially-executed corpus uses locked collision map
# ---------------------------------------------------------------------------

class TestPlanOnPartiallyExecutedCorpusUsesLockedMap:
    def test_locked_collision_map_used_and_warning_emitted(self, project_dir):
        import warnings

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        # Only 2 remaining (3 of 5 already migrated and deleted)
        for i in (4, 5):
            make_yaml_frontmatter_file(
                bl / f"BL-{i:03d}-item.md",
                {"id": f"BL-{i:03d}", "title": f"Item {i}", "status": "open"},
            )

        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87", "locked": True})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = build_plan(project_dir=str(project_dir))

        assert plan.collision_map["STORY-15"] == "ISSUE-87"
        assert any(
            "source count" in str(w.message).lower() or "reduced" in str(w.message).lower()
            for w in caught
        )


# ---------------------------------------------------------------------------
# Scenario: Pipeline with persisted collision map from prior aborted run
# ---------------------------------------------------------------------------

class TestPipelineWithPersistedCollisionMapFromAbortedRun:
    def test_plan_reuses_persisted_collision_map_and_completes(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-001-foo.md",
            {"id": "BL-001", "title": "Foo", "status": "open"},
        )

        # Persisted collision map from prior aborted run, no migration state
        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87"})
        # Ensure migration state does NOT exist
        if migration_state_path(project_dir).exists():
            migration_state_path(project_dir).unlink()

        errors = validate(project_dir=str(project_dir))
        assert errors == []

        plan = build_plan(project_dir=str(project_dir))
        assert plan.collision_map == {"STORY-15": "ISSUE-87"}

        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(bl)])
        result = execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        state = yaml.safe_load(migration_state_path(project_dir).read_text())
        assert state["status"] == "complete"

        verify_errors = verify(project_dir=str(project_dir))
        assert verify_errors == []


# ---------------------------------------------------------------------------
# Scenario: Case-insensitive status and priority through full pipeline
# ---------------------------------------------------------------------------

class TestCaseInsensiveStatusAndPriorityThroughFullPipeline:
    def test_backlog_status_and_spike_priority_remapped_in_final_frontmatter(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-084-case.md",
            "BL-084: Case test",
            {"Status": "BACKLOG", "Priority": "SPIKE"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))
        snap = create_snapshot(project_dir=str(project_dir), base_paths=[str(bl)])
        execute(plan, project_dir=str(project_dir), snapshot_path=str(snap))

        issue_084_files = list(product_base(project_dir).rglob("ISSUE-084-*.md"))
        assert len(issue_084_files) == 1

        content = issue_084_files[0].read_text()
        fm = yaml.safe_load(content.split("---")[1])
        assert fm.get("status") == "new"
        assert fm.get("priority") == "P3"
