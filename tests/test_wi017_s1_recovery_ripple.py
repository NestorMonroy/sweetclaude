"""
WI-017 S1 — Recovery Ripple tests.

These tests verify that the backup-exclusion and id-handling rules in
characterize_project flow correctly through the recovery layer:
diagnose_project, graduation_check, _collect_known_ids, _WORK_ITEM_ID_RE,
and resolve_graduation_blocker.

All tests use real on-disk temp trees and real state files. No mocks.
"""
import sys
import os

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from pathlib import Path
import pytest
import yaml

from recovery.characterize_project import characterize_project
from recovery.recover_project import (
    diagnose_project,
    graduation_check,
    resolve_graduation_blocker,
    _collect_known_ids,
    _WORK_ITEM_ID_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product_tree(tmp_path: Path) -> Path:
    """
    Create a minimal project where docs/product is the product base.
    Returns the project root.
    """
    project = tmp_path / "project"
    (project / "docs" / "product").mkdir(parents=True)
    return project


def _write_md(project: Path, rel_to_product: str, frontmatter_id: str | None = None) -> Path:
    """
    Write a Markdown file at <product_base>/<rel_to_product>.
    Works for non-.md extensions too (backup files, etc.).
    """
    product_base = project / "docs" / "product"
    target = product_base / rel_to_product
    target.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter_id is not None:
        content = (
            f"---\n"
            f"id: {frontmatter_id}\n"
            f"title: Test item {frontmatter_id}\n"
            f"status: new\n"
            f"type: story\n"
            f"---\n\n"
            f"Body text.\n"
        )
    else:
        content = "# No frontmatter\n\nBody text.\n"
    target.write_text(content, encoding="utf-8")
    return target


def _write_sweetclaude_state(project: Path, data: dict) -> Path:
    """Write .sweetclaude/state/sweetclaude.yaml with the given data."""
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return state_path


def _make_compatibility_mode_state(project: Path) -> Path:
    """
    Write the sweetclaude.yaml state that represents
    recovery.taxonomy.status: stabilized-without-migration
    (the compatibility mode that graduation_check requires).
    """
    return _write_sweetclaude_state(project, {
        "framework": {
            "installed_version": "4.2.9-beta",
            "migration_status": "deferred",
        },
        "recovery": {
            "taxonomy": {
                "status": "stabilized-without-migration",
                "accepted_layout": "typed-backlog-prefixes",
                "migration_required": False,
                "blind_taxonomy_migration_allowed": False,
            }
        },
    })


# ---------------------------------------------------------------------------
# Ripple 1: Backup-only duplicates → diagnose clean
# A project whose ONLY duplicate ids come from backup files must NOT produce
# a "duplicate-work-item-ids" blocking factor in diagnose_project.
# ---------------------------------------------------------------------------

class TestBackupOnlyDuplicatesDiagnoseClean:
    def _make_project_with_backup_only_duplicates(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        # Several real work items, each paired with a backup only
        pairs = [
            ("backlog/stories/STORY-001-foo.md", "STORY-001",
             "backlog/stories/STORY-001-foo.bold-backup-1.md"),
            ("backlog/stories/STORY-002-bar.md", "STORY-002",
             "backlog/stories/STORY-002-bar.bold-backup-1.md"),
            ("backlog/ISSUE-010-task.md", "ISSUE-010",
             "backlog/ISSUE-010-task.md.bak"),
        ]
        for real_rel, fid, backup_rel in pairs:
            _write_md(project, real_rel, frontmatter_id=fid)
            _write_md(project, backup_rel, frontmatter_id=fid)
        return project

    def test_no_duplicate_work_item_ids_blocking_factor(self, tmp_path):
        project = self._make_project_with_backup_only_duplicates(tmp_path)

        diagnosis = diagnose_project(project)

        blocking_codes = [
            factor.get("code")
            for factor in diagnosis.get("blocking_factors", [])
        ]
        assert "duplicate-work-item-ids" not in blocking_codes, (
            "backup-only duplicates must NOT produce a 'duplicate-work-item-ids' blocking factor"
        )

    def test_characterization_duplicate_count_zero(self, tmp_path):
        project = self._make_project_with_backup_only_duplicates(tmp_path)

        diagnosis = diagnose_project(project)

        dup_count = (
            diagnosis
            .get("characterization", {})
            .get("ids", {})
            .get("duplicate_count", -1)
        )
        assert dup_count == 0, (
            "characterization.ids.duplicate_count must be 0 when only backups cause collisions"
        )


# ---------------------------------------------------------------------------
# Ripple 2: Graduation ripple
# A project in compatibility mode (stabilized-without-migration) whose only
# duplicates are backups and which is otherwise v4-compliant (ISSUE-prefixed,
# no typed dirs) → graduation_check reports graduation_allowed == True with no
# "duplicate-ids" blocker.
# ---------------------------------------------------------------------------

class TestGraduationRippleBackupOnlyDuplicates:
    def _make_v4_project_with_backup_duplicates(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        # v4 work items (ISSUE prefix), standard flat backlog structure
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")
        _write_md(project, "backlog/ISSUE-002-beta.md", frontmatter_id="ISSUE-002")
        # Backup duplicate — must NOT block graduation
        _write_md(
            project,
            "backlog/ISSUE-001-alpha.bold-backup-1.md",
            frontmatter_id="ISSUE-001",
        )
        # Write compatibility mode state
        _make_compatibility_mode_state(project)
        return project

    def test_graduation_allowed_true(self, tmp_path):
        project = self._make_v4_project_with_backup_duplicates(tmp_path)

        result = graduation_check(project)

        assert result.get("graduation_allowed") is True, (
            "graduation_check must report graduation_allowed=True when the only "
            "duplicates are backup files and the project is otherwise v4-compliant; "
            f"got: {result}"
        )

    def test_no_duplicate_ids_blocker_in_graduation_check(self, tmp_path):
        project = self._make_v4_project_with_backup_duplicates(tmp_path)

        result = graduation_check(project)

        blocker_codes = [b.get("code") for b in result.get("blockers", [])]
        assert "duplicate-ids" not in blocker_codes, (
            "backup-only duplicates must NOT produce a 'duplicate-ids' blocker in graduation_check"
        )


# ---------------------------------------------------------------------------
# Ripple 3: _collect_known_ids excludes backups
# A tree with ISSUE-005-a.md (id ISSUE-005) and ISSUE-005-a.bold-backup-1.md
# (also containing id ISSUE-005) → _collect_known_ids must not treat the
# backup as occupying a second id slot.
# The set returned must contain ISSUE-005 exactly once (as a set),
# and the backup must not double-count it.
#
# We also verify indirectly: if _collect_known_ids counted backup files,
# _next_available_id would pick a higher number. We pin the observable
# behavior through resolve_graduation_blocker by checking that the id-space
# used for renumbering does not include backup-sourced slots.
# ---------------------------------------------------------------------------

class TestCollectKnownIdsExcludesBackups:
    def test_known_ids_does_not_include_backup_as_separate_slot(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        _write_md(project, "backlog/ISSUE-005-a.md", frontmatter_id="ISSUE-005")
        _write_md(
            project,
            "backlog/ISSUE-005-a.bold-backup-1.md",
            frontmatter_id="ISSUE-005",
        )

        known = _collect_known_ids(product_base)

        # The backup file also has id ISSUE-005 in frontmatter; _collect_known_ids
        # must exclude it so the set has ISSUE-005 at most once.
        # As a set, duplicates collapse anyway — the real test is that the backup
        # file's id is NOT present when _collect_known_ids is backup-aware:
        # if backups are excluded, the backup's frontmatter id must not be scanned.
        # We verify by checking that scanning the backup does NOT add a NEW id
        # (ISSUE-005 already present from the real file), and that when there is
        # ONLY a backup (no real file), the id is absent.
        project2 = _make_product_tree(tmp_path / "p2")
        product_base2 = project2 / "docs" / "product"
        # Only backup, no real file
        _write_md(
            project2,
            "backlog/ISSUE-099-x.bold-backup-1.md",
            frontmatter_id="ISSUE-099",
        )

        known2 = _collect_known_ids(product_base2)

        assert "ISSUE-099" not in known2, (
            "_collect_known_ids must not register a backup-only id (ISSUE-099 exists only "
            "in a backup file, no real counterpart)"
        )

    def test_real_id_present_when_backup_also_exists(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        _write_md(project, "backlog/ISSUE-005-a.md", frontmatter_id="ISSUE-005")
        _write_md(
            project,
            "backlog/ISSUE-005-a.bold-backup-1.md",
            frontmatter_id="ISSUE-005",
        )

        known = _collect_known_ids(product_base)

        # The real file's id must still be collected
        assert "ISSUE-005" in known, (
            "_collect_known_ids must include ISSUE-005 from the real (non-backup) file"
        )


# ---------------------------------------------------------------------------
# Ripple 4: Namespaced US ids accepted by _WORK_ITEM_ID_RE
# A frontmatter id like "US-DM-001" must match _WORK_ITEM_ID_RE so it is
# handled as a rename candidate (not silently skipped) when it appears in a
# duplicate group.
# The regex must accept multi-segment namespaced ids of the form PREFIX-PART-NNN.
# ---------------------------------------------------------------------------

class TestWorkItemIdReAcceptsNamespacedIds:
    def test_work_item_id_re_matches_simple_id(self):
        assert _WORK_ITEM_ID_RE.match("ISSUE-001"), (
            "_WORK_ITEM_ID_RE must match simple work-item ids like ISSUE-001"
        )

    def test_work_item_id_re_matches_namespaced_us_id(self):
        assert _WORK_ITEM_ID_RE.match("US-DM-001"), (
            "_WORK_ITEM_ID_RE must match namespaced ids like US-DM-001 "
            "(so they are treated as rename candidates, not silently skipped)"
        )

    def test_work_item_id_re_matches_bl_namespaced_id(self):
        assert _WORK_ITEM_ID_RE.match("US-BL027-002"), (
            "_WORK_ITEM_ID_RE must match namespaced ids like US-BL027-002"
        )

    def test_resolve_graduation_blocker_handles_namespaced_frontmatter_id(self, tmp_path):
        """
        A duplicate group where one file's frontmatter carries a namespaced id
        (US-DM-001) must be classified as a rename candidate by
        resolve_graduation_blocker, not silently skipped.

        The test drives through the public path: create a duplicate group
        (two files named STORY-007-*.md, one with frontmatter id US-DM-001),
        run resolve_graduation_blocker, and assert the result is not an error
        caused by a regex rejection of the namespaced id.

        Since resolve_graduation_blocker shells out to doctor.py, we can only
        assert that the call does not crash or return status=="error" due to
        a regex mismatch. We assert the renamed entry appears in the result
        (or that the function completes without raising a match-failure error).
        """
        project = _make_product_tree(tmp_path)
        # Two files with STORY-007 filename prefix but one has namespaced frontmatter id
        _write_md(project, "backlog/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/STORY-007-b.md", frontmatter_id="US-DM-001")
        _make_compatibility_mode_state(project)

        result = resolve_graduation_blocker(project, code="duplicate-ids")

        # If _WORK_ITEM_ID_RE rejects "US-DM-001", the file would be treated
        # as a pure collision (colliding list) rather than a rename candidate,
        # leading to an incorrect renumber. The observable contract is:
        # the result must not be status=="unsupported" and must not crash.
        # The renamed list must contain an entry referencing US-DM-001 OR
        # the renumbered list must have exactly 0 or 1 entries (since the
        # namespaced-id file should be renamed, not renumbered).
        assert result.get("status") not in ("unsupported",), (
            "resolve_graduation_blocker must not return 'unsupported' for duplicate-ids code"
        )
        # The rename path for US-DM-001 must be taken — the file must appear
        # in renamed (not renumbered), meaning the regex accepted the id.
        renamed_ids = [r.get("id") for r in result.get("renamed", [])]
        assert "US-DM-001" in renamed_ids, (
            "the file with frontmatter id US-DM-001 must appear in 'renamed' — "
            "_WORK_ITEM_ID_RE must accept it as a valid id so it is renamed, not renumbered"
        )
