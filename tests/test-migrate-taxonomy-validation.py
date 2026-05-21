"""
Tests for migration validation — Feature: Migration validation
Translates: tests/features/issue-090-migrate-taxonomy-validation.feature
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

# This import WILL FAIL until the implementation exists — that is expected.
from migrate.migrate_taxonomy import validate

from fixtures.migrate_taxonomy_fixtures import (
    product_base,
    backlog_dir,
    done_dir,
    roadmap_issues_dir,
    state_dir,
    artifact_privacy_path,
    migration_state_path,
    collision_map_path,
    make_yaml_frontmatter_file,
    make_bold_format_file,
    project_dir,  # noqa: F401 — pytest fixture
)


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------

def _write_artifact_privacy(project_dir, base_path=".sweetclaude/product"):
    ap = artifact_privacy_path(project_dir)
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(yaml.safe_dump({"product": {"base_path": base_path}}))


def _write_migration_state(project_dir, status: str):
    state = state_dir(project_dir)
    state.mkdir(parents=True, exist_ok=True)
    migration_state_path(project_dir).write_text(
        yaml.safe_dump({"status": status})
    )


# ---------------------------------------------------------------------------
# Scenario: Valid project passes validation
# ---------------------------------------------------------------------------

class TestValidProjectPassesValidation:
    def test_valid_project_returns_empty_error_list(self, project_dir):
        bl_path = backlog_dir(project_dir) / "BL-001-foo.md"
        bl_path.parent.mkdir(parents=True, exist_ok=True)
        bl_path.write_text("# BL-001: Foo\n\n**Status:** Open\n")

        errors = validate(project_dir=str(project_dir))

        assert errors == []


# ---------------------------------------------------------------------------
# Scenario: Empty project fails validation
# ---------------------------------------------------------------------------

class TestEmptyProjectFailsValidation:
    def test_no_source_files_returns_error_containing_no_source_files_found(
        self, project_dir
    ):
        errors = validate(project_dir=str(project_dir))

        assert len(errors) >= 1
        messages = " ".join(str(e) for e in errors).lower()
        assert "no source files found" in messages


# ---------------------------------------------------------------------------
# Scenario: Single pre-existing ISSUE file at target path fails validation
# ---------------------------------------------------------------------------

class TestSinglePreExistingIssueFileFails:
    def test_preexisting_issue_file_returns_error_with_issue_id_and_already_exists(
        self, project_dir
    ):
        bl = backlog_dir(project_dir) / "BL-042-widget-builder.md"
        bl.parent.mkdir(parents=True, exist_ok=True)
        bl.write_text("# BL-042: Widget builder\n\n**Status:** Open\n")

        roadmap_issues = roadmap_issues_dir(project_dir)
        roadmap_issues.mkdir(parents=True, exist_ok=True)
        (roadmap_issues / "ISSUE-042-widget-builder.md").write_text(
            "# ISSUE-042: Widget builder\n"
        )

        errors = validate(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined
        assert "already exists" in combined.lower()


# ---------------------------------------------------------------------------
# Scenario: Multiple pre-existing ISSUE files produce multiple errors
# ---------------------------------------------------------------------------

class TestMultiplePreExistingIssueFilesProduceMultipleErrors:
    def test_two_preexisting_issue_files_return_two_errors(self, project_dir):
        bl_dir = backlog_dir(project_dir)
        bl_dir.mkdir(parents=True, exist_ok=True)
        (bl_dir / "BL-042-widget-builder.md").write_text(
            "# BL-042: Widget builder\n\n**Status:** Open\n"
        )
        (bl_dir / "BL-043-other-thing.md").write_text(
            "# BL-043: Other thing\n\n**Status:** Open\n"
        )

        roadmap_issues = roadmap_issues_dir(project_dir)
        roadmap_issues.mkdir(parents=True, exist_ok=True)
        (roadmap_issues / "ISSUE-042-widget-builder.md").write_text("# ISSUE-042\n")

        (bl_dir / "ISSUE-043-other-thing.md").write_text("# ISSUE-043\n")

        errors = validate(project_dir=str(project_dir))

        assert len(errors) == 2
        combined = " ".join(str(e) for e in errors)
        assert "ISSUE-042" in combined
        assert "ISSUE-043" in combined


# ---------------------------------------------------------------------------
# Scenario: Failed migration state blocks validation
# ---------------------------------------------------------------------------

class TestFailedMigrationStateBlocksValidation:
    def test_failed_state_returns_error_containing_previous_migration_failed(
        self, project_dir
    ):
        bl = backlog_dir(project_dir) / "BL-001-foo.md"
        bl.write_text("# BL-001: Foo\n\n**Status:** Open\n")
        _write_migration_state(project_dir, "failed")

        errors = validate(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors).lower()
        assert "previous migration failed" in combined

    def test_failed_state_error_mentions_rollback(self, project_dir):
        bl = backlog_dir(project_dir) / "BL-001-foo.md"
        bl.write_text("# BL-001: Foo\n\n**Status:** Open\n")
        _write_migration_state(project_dir, "failed")

        errors = validate(project_dir=str(project_dir))

        combined = " ".join(str(e) for e in errors).lower()
        assert "rollback" in combined


# ---------------------------------------------------------------------------
# Scenario: In-progress migration state blocks validation
# ---------------------------------------------------------------------------

class TestInProgressMigrationStateBlocksValidation:
    def test_in_progress_state_returns_error_containing_migration_already_in_progress(
        self, project_dir
    ):
        bl = backlog_dir(project_dir) / "BL-001-foo.md"
        bl.write_text("# BL-001: Foo\n\n**Status:** Open\n")
        _write_migration_state(project_dir, "in_progress")

        errors = validate(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors).lower()
        assert "migration already in progress" in combined


# ---------------------------------------------------------------------------
# Scenario: Completed migration state passes validation
# ---------------------------------------------------------------------------

class TestCompletedMigrationStatePassesValidation:
    def test_complete_state_returns_empty_error_list(self, project_dir):
        bl = backlog_dir(project_dir) / "BL-001-foo.md"
        bl.write_text("# BL-001: Foo\n\n**Status:** Open\n")
        _write_migration_state(project_dir, "complete")

        errors = validate(project_dir=str(project_dir))

        assert errors == []


# ---------------------------------------------------------------------------
# Scenario: Product base escaping project root fails validation
# ---------------------------------------------------------------------------

class TestProductBaseEscapingRootFailsValidation:
    def test_absolute_product_base_raises_value_error_with_escapes_project_root(
        self, project_dir
    ):
        _write_artifact_privacy(project_dir, base_path="/etc/shadow")

        with pytest.raises(ValueError, match="escapes project root"):
            validate(project_dir=str(project_dir))


# ---------------------------------------------------------------------------
# Scenario: Missing artifact-privacy.yaml uses default product base
# ---------------------------------------------------------------------------

class TestMissingArtifactPrivacyUsesDefault:
    def test_missing_artifact_privacy_resolves_to_default_product_base(
        self, tmp_path
    ):
        # No artifact-privacy.yaml written — bare project dir
        bl_dir = tmp_path / ".sweetclaude" / "product" / "backlog"
        bl_dir.mkdir(parents=True)
        (bl_dir / "BL-001-foo.md").write_text("# BL-001: Foo\n\n**Status:** Open\n")

        # validate should not raise and should use default base
        errors = validate(project_dir=str(tmp_path))

        # No "escapes project root" errors — the default was used
        for e in errors:
            assert "escapes project root" not in str(e).lower()


# ---------------------------------------------------------------------------
# Scenario: Empty artifact-privacy.yaml uses default product base
# ---------------------------------------------------------------------------

class TestEmptyArtifactPrivacyUsesDefault:
    def test_empty_artifact_privacy_resolves_to_default_product_base(
        self, project_dir
    ):
        artifact_privacy_path(project_dir).write_bytes(b"")

        bl_dir = backlog_dir(project_dir)
        bl_dir.mkdir(parents=True, exist_ok=True)
        (bl_dir / "BL-001-foo.md").write_text("# BL-001: Foo\n\n**Status:** Open\n")

        errors = validate(project_dir=str(project_dir))

        for e in errors:
            assert "escapes project root" not in str(e).lower()


# ---------------------------------------------------------------------------
# Scenario: Symlink source file pointing outside project root fails validation
# ---------------------------------------------------------------------------

class TestSymlinkSourceFileOutsideRootFails:
    def test_symlink_to_outside_root_returns_error_about_source_path_escaping(
        self, project_dir
    ):
        bl_dir = backlog_dir(project_dir)
        bl_dir.mkdir(parents=True, exist_ok=True)
        symlink = bl_dir / "BL-099-evil.md"
        symlink.symlink_to("/etc/passwd")

        errors = validate(project_dir=str(project_dir))

        assert len(errors) >= 1
        combined = " ".join(str(e) for e in errors).lower()
        assert "source" in combined or "path" in combined
        assert "escap" in combined or "outside" in combined or "project root" in combined
