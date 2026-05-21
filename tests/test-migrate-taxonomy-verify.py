"""
Tests for post-migration verification — Feature: Post-migration verification
Translates: tests/features/issue-090-migrate-taxonomy-verify.feature
"""
import os
import sys
import warnings
import yaml
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import verify

from fixtures.migrate_taxonomy_fixtures import (
    product_base,
    backlog_dir,
    done_dir,
    issues_dir,
    roadmap_dir,
    milestones_dir,
    roadmap_issues_dir,
    roadmap_issues_done_dir,
    roadmap_milestones_dir,
    roadmap_epics_dir,
    backlog_archived_dir,
    state_dir,
    migration_state_path,
    collision_map_path,
    make_yaml_frontmatter_file,
    project_dir,  # noqa: F401 — pytest fixture
)


_REQUIRED_FIELDS = ["id", "title", "type", "status", "created"]


def _write_valid_issue(dest_dir, number: str, slug: str, extra: dict = None):
    """Write a valid ISSUE file with all required frontmatter fields."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": f"ISSUE-{number}",
        "title": f"Issue {number}",
        "type": "enhancement",
        "status": "active",
        "created": "2026-05-01",
    }
    if extra:
        fm.update(extra)
    make_yaml_frontmatter_file(dest_dir / f"ISSUE-{number}-{slug}.md", fm)


def _write_valid_ep(dest_dir, ep_id: str):
    dest_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": ep_id,
        "title": f"Epic {ep_id}",
        "type": "epic",
        "status": "active",
        "created": "2026-05-01",
    }
    make_yaml_frontmatter_file(dest_dir / f"{ep_id}-slug.md", fm)


def _write_valid_ms(dest_dir, ms_id: str):
    dest_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": ms_id,
        "title": f"Milestone {ms_id}",
        "type": "milestone",
        "status": "active",
        "created": "2026-05-01",
    }
    make_yaml_frontmatter_file(dest_dir / f"{ms_id}-slug.md", fm)


def _write_state(project_dir, expected_dest_count: int):
    state_dir(project_dir).mkdir(parents=True, exist_ok=True)
    migration_state_path(project_dir).write_text(
        yaml.safe_dump({
            "status": "complete",
            "expected_dest_count": expected_dest_count,
        })
    )


# ---------------------------------------------------------------------------
# Scenario: Clean migration passes all checks
# ---------------------------------------------------------------------------

class TestCleanMigrationPassesAllChecks:
    def test_clean_migration_returns_empty_error_list(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        _write_valid_issue(ri, "042", "widget")
        re_ = roadmap_epics_dir(project_dir)
        _write_valid_ep(re_, "EP-001")
        rm_ = roadmap_milestones_dir(project_dir)
        _write_valid_ms(rm_, "MS-007")
        _write_state(project_dir, expected_dest_count=3)

        errors = verify(project_dir=str(project_dir))

        assert errors == []


# ---------------------------------------------------------------------------
# Scenario: Missing required frontmatter field fails verification
# ---------------------------------------------------------------------------

class TestMissingRequiredFrontmatterField:
    def test_missing_type_field_returns_error_about_issue_042(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {"id": "ISSUE-042", "title": "Widget", "status": "active", "created": "2026-05-01"},
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined
        assert "type" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Required frontmatter fields are id, title, type, status, created
# ---------------------------------------------------------------------------

class TestRequiredFieldsPassValidation:
    def test_issue_with_all_required_fields_passes(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        _write_valid_issue(ri, "042", "widget")
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        error_msgs = [str(e) for e in errors]
        assert not any("ISSUE-042" in m and "missing" in m.lower() for m in error_msgs)


# ---------------------------------------------------------------------------
# Scenario: EP files validated for required frontmatter
# ---------------------------------------------------------------------------

class TestEPFilesValidatedForFrontmatter:
    def test_ep_missing_title_returns_error(self, project_dir):
        re_ = roadmap_epics_dir(project_dir)
        re_.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            re_ / "EP-001-taxonomy.md",
            {"id": "EP-001", "type": "epic", "status": "active", "created": "2026-05-01"},
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "EP-001" in combined
        assert "title" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: MS files validated for required frontmatter
# ---------------------------------------------------------------------------

class TestMSFilesValidatedForFrontmatter:
    def test_ms_missing_status_returns_error(self, project_dir):
        rm_ = roadmap_milestones_dir(project_dir)
        rm_.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            rm_ / "MS-007-tracked.md",
            {"id": "MS-007", "title": "Tracked", "type": "milestone", "created": "2026-05-01"},
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "MS-007" in combined
        assert "status" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Null created field fails verification
# ---------------------------------------------------------------------------

class TestNullCreatedFieldFails:
    def test_null_created_field_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": None,
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined
        assert "created" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Frontmatter id must match filename
# ---------------------------------------------------------------------------

class TestFrontmatterIdMustMatchFilename:
    def test_id_frontmatter_mismatch_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-040",  # mismatch
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined or "mismatch" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Non-standard priority value produces warning
# ---------------------------------------------------------------------------

class TestNonStandardPriorityProducesWarning:
    def test_critical_priority_produces_warning(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
                "priority": "critical",
            },
        )
        _write_state(project_dir, 1)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            errors = verify(project_dir=str(project_dir))

        assert any("priority" in str(w.message).lower() for w in caught)


# ---------------------------------------------------------------------------
# Scenario: Duplicate ID across directories fails verification
# ---------------------------------------------------------------------------

class TestDuplicateIdAcrossDirectories:
    def test_same_id_in_two_dirs_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        _write_valid_issue(ri, "042", "widget-a")

        bl = backlog_dir(project_dir)
        _write_valid_issue(bl, "042", "widget-b")

        _write_state(project_dir, 2)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined
        assert "duplicate" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: depends_on pointing to nonexistent ID fails
# ---------------------------------------------------------------------------

class TestDependsOnNonexistentId:
    def test_unresolved_depends_on_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
                "depends_on": ["ISSUE-999"],
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-999" in combined or "depends_on" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: depends_on still showing legacy STORY-N reference fails
# ---------------------------------------------------------------------------

class TestDependsOnLegacyReferenceFailsVerification:
    def test_legacy_story_ref_in_depends_on_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
                "depends_on": ["STORY-015"],
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "STORY-015" in combined or "legacy" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Epic reference pointing to nonexistent EP fails
# ---------------------------------------------------------------------------

class TestEpicRefNonexistentFails:
    def test_nonexistent_ep_in_epic_field_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
                "epic": "EP-999",
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "EP-999" in combined


# ---------------------------------------------------------------------------
# Scenario: Milestone reference pointing to nonexistent MS fails
# ---------------------------------------------------------------------------

class TestMilestoneRefNonexistentFails:
    def test_nonexistent_ms_in_milestone_field_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        ri.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            ri / "ISSUE-042-widget.md",
            {
                "id": "ISSUE-042",
                "title": "Widget",
                "type": "enhancement",
                "status": "active",
                "created": "2026-05-01",
                "milestone": "MS-999",
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "MS-999" in combined


# ---------------------------------------------------------------------------
# Scenario: superseded_by pointing to nonexistent ID fails
# ---------------------------------------------------------------------------

class TestSupersededByNonexistentFails:
    def test_nonexistent_superseded_by_returns_error(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "ISSUE-082-promoted.md",
            {
                "id": "ISSUE-082",
                "title": "Promoted",
                "type": "enhancement",
                "status": "superseded",
                "created": "2026-05-01",
                "superseded_by": "EP-999",
            },
        )
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "EP-999" in combined


# ---------------------------------------------------------------------------
# Scenario: superseded_by pointing to valid ISSUE-NNN passes
# ---------------------------------------------------------------------------

class TestSupersededByValidIssuePasses:
    def test_valid_superseded_by_no_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        _write_valid_issue(ri, "090", "migration")

        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "ISSUE-082-promoted.md",
            {
                "id": "ISSUE-082",
                "title": "Promoted",
                "type": "enhancement",
                "status": "superseded",
                "created": "2026-05-01",
                "superseded_by": "ISSUE-090",
            },
        )
        _write_state(project_dir, 2)

        errors = verify(project_dir=str(project_dir))

        error_msgs = [str(e) for e in errors]
        assert not any("ISSUE-082" in m and "superseded_by" in m for m in error_msgs)


# ---------------------------------------------------------------------------
# Scenario: Remaining BL file in active directory fails verification
# ---------------------------------------------------------------------------

class TestRemainingBLFileFails:
    def test_leftover_bl_file_returns_legacy_file_error(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-042.md").write_text("# BL-042\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "BL-042" in combined


# ---------------------------------------------------------------------------
# Scenario: Remaining STORY file fails verification
# ---------------------------------------------------------------------------

class TestRemainingStoryFileFails:
    def test_leftover_story_file_returns_legacy_file_error(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "STORY-015.md").write_text("# STORY-015\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "STORY-015" in combined


# ---------------------------------------------------------------------------
# Scenario: Remaining RM file fails verification
# ---------------------------------------------------------------------------

class TestRemainingRMFileFails:
    def test_leftover_rm_file_returns_legacy_file_error(self, project_dir):
        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        (rm / "RM-001.md").write_text("# RM-001\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "RM-001" in combined


# ---------------------------------------------------------------------------
# Scenario: CHORE, BUG, DEBT files in active directories fail
# ---------------------------------------------------------------------------

class TestChoreBugDebtFilesFail:
    def test_chore_file_in_backlog_returns_legacy_file_error(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "CHORE-010.md").write_text("# CHORE-010\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "CHORE-010" in combined


# ---------------------------------------------------------------------------
# Scenario: Legacy file check is recursive under active directories
# ---------------------------------------------------------------------------

class TestLegacyFileCheckIsRecursive:
    def test_bl_in_subdir_returns_legacy_file_error(self, project_dir):
        sub = backlog_dir(project_dir) / "some-subdir"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "BL-001.md").write_text("# BL-001\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors)
        assert "BL-001" in combined


# ---------------------------------------------------------------------------
# Scenario: Archived I-N files in backlog/archived/ are allowed
# ---------------------------------------------------------------------------

class TestArchivedIFilesAllowed:
    def test_i_file_in_archived_no_error(self, project_dir):
        arch = backlog_archived_dir(project_dir)
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "I-001.md").write_text("# I-001\n")
        _write_state(project_dir, 1)

        errors = verify(project_dir=str(project_dir))

        error_msgs = [str(e) for e in errors]
        assert not any("I-001" in m and "legacy" in m.lower() for m in error_msgs)


# ---------------------------------------------------------------------------
# Scenario: issues/ directory must be empty after archival
# ---------------------------------------------------------------------------

class TestIssuesDirMustBeEmptyAfterArchival:
    def test_i_file_in_issues_not_archived_returns_error(self, project_dir):
        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001.md").write_text("# I-001\n")
        _write_state(project_dir, 0)

        errors = verify(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors).lower()
        assert "issues" in combined


# ---------------------------------------------------------------------------
# Scenario: File count matches plan expectations
# ---------------------------------------------------------------------------

class TestFileCountMatchesPlanExpectations:
    def test_correct_file_count_no_file_count_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        for i in range(1, 9):
            _write_valid_issue(ri, f"{i:03d}", f"item-{i}")

        arch = backlog_archived_dir(project_dir)
        for i in (1, 2):
            arch.mkdir(parents=True, exist_ok=True)
            (arch / f"I-{i:03d}.md").write_text(f"# I-{i:03d}\n")

        rm_ = roadmap_milestones_dir(project_dir)
        _write_valid_ms(rm_, "MS-007")

        _write_state(project_dir, expected_dest_count=11)

        errors = verify(project_dir=str(project_dir))

        error_msgs = [str(e) for e in errors]
        assert not any("count" in m.lower() for m in error_msgs)


# ---------------------------------------------------------------------------
# Scenario: File count mismatch fails verification
# ---------------------------------------------------------------------------

class TestFileCountMismatch:
    def test_fewer_files_than_expected_returns_error(self, project_dir):
        ri = roadmap_issues_dir(project_dir)
        for i in range(1, 9):
            _write_valid_issue(ri, f"{i:03d}", f"item-{i}")

        _write_state(project_dir, expected_dest_count=10)

        errors = verify(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors).lower()
        assert "count" in combined or "mismatch" in combined


# ---------------------------------------------------------------------------
# Scenario: verify() called without prior execute (no state file)
# ---------------------------------------------------------------------------

class TestVerifyWithoutPriorExecute:
    def test_no_state_file_still_errors_on_legacy_files(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001.md").write_text("# BL-001\n")

        errors = verify(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors)
        assert "BL-001" in combined


# ---------------------------------------------------------------------------
# Scenario: Zero ISSUE files after all-retire corpus
# ---------------------------------------------------------------------------

class TestZeroIssueFilesAfterAllRetire:
    def test_empty_dirs_after_all_retire_returns_warning_not_false_pass(
        self, project_dir
    ):
        _write_state(project_dir, expected_dest_count=0)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            errors = verify(project_dir=str(project_dir))

        assert errors == [] or any("zero" in str(w.message).lower() for w in caught)
        assert any("zero" in str(w.message).lower() or "no migrated" in str(w.message).lower() for w in caught)
