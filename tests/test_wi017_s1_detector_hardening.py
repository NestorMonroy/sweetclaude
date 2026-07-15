"""
WI-017 S1 — Detector Hardening tests.

Covers every scenario in tests/features/wi-017-s1-detector-hardening.feature.
All tests call characterize_project() with real on-disk file trees; no mocks.

New output keys defined here (the implementer contract):
  ids["derived_files"]          — list of relative paths excluded as tool/editor/VCS backups;
                                  present and empty when no backups exist, populated otherwise.
  documents["supporting"]       — list of relative paths classified as supporting docs
                                  (PRD/brief/FOUNDATION/index/personas); excluded from
                                  work-item counting.
  items["epics"]                — list of dicts {id, path} for bespoke EPIC-NNN/EPIC-NNN.md
                                  items (EPIC-NNN.md living inside an EPIC-NNN/ directory).
  items["stories"]              — list of dicts {id, path, parent_epic, feature_file|None}
                                  for bespoke US-* story items living inside EPIC-NNN/ dirs.
"""
import sys
import os

# Make scripts/ importable (mirrors conftest.py convention)
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from pathlib import Path
import pytest

from recovery.characterize_project import characterize_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product_tree(tmp_path: Path) -> Path:
    """
    Create a minimal project where docs/product is the product base.
    Resolution uses the DEFAULT_PRODUCT_BASES fallback — no config files needed.
    Returns the project root (not docs/product).
    """
    project = tmp_path / "project"
    (project / "docs" / "product").mkdir(parents=True)
    return project


def _write_md(project: Path, rel_to_product: str, frontmatter_id: str | None = None) -> Path:
    """
    Write a Markdown file at <product_base>/<rel_to_product>.
    If frontmatter_id is given the file has YAML frontmatter with that id.
    Works for any path including backup-suffix paths like foo.md.bak or foo.md~.
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


def _write_feature(project: Path, rel_to_product: str) -> Path:
    """Write a bare .feature file at <product_base>/<rel_to_product>."""
    product_base = project / "docs" / "product"
    target = product_base / rel_to_product
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "Feature: placeholder\n  Scenario: placeholder\n    Given nothing\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Scenario: Tool backups are excluded from work-item and duplicate counting
# Gherkin line: "Given a product file 'milestones/MS-001-core.md' with frontmatter id 'MS-001'"
#               "And a product file 'milestones/MS-001-core.bold-backup-20260614-113230.md'..."
#               "Then the duplicate id count is 0"
#               "And 'MS-001-core.bold-backup-*.md' is not counted as a work item"
#               "And the backup file is reported under an excluded/derived-files inventory"
# ---------------------------------------------------------------------------

class TestBoldBackupExclusion:
    def test_bold_backup_does_not_inflate_duplicate_count(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "milestones/MS-001-core.md", frontmatter_id="MS-001")
        _write_md(
            project,
            "milestones/MS-001-core.bold-backup-20260614-113230.md",
            frontmatter_id="MS-001",
        )

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 0, (
            "bold-backup file must not be counted as a duplicate work item"
        )

    def test_bold_backup_not_counted_in_prefix_work_items(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "milestones/MS-001-core.md", frontmatter_id="MS-001")
        _write_md(
            project,
            "milestones/MS-001-core.bold-backup-20260614-113230.md",
            frontmatter_id="MS-001",
        )

        result = characterize_project(project)

        # Only the canonical file should count; bold-backup must be excluded
        assert result["counts"]["prefixes"].get("MS", 0) == 1, (
            "bold-backup file must not be counted in prefix work-item totals"
        )

    def test_bold_backup_reported_in_derived_files_inventory(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "milestones/MS-001-core.md", frontmatter_id="MS-001")
        backup_rel = "milestones/MS-001-core.bold-backup-20260614-113230.md"
        _write_md(project, backup_rel, frontmatter_id="MS-001")

        result = characterize_project(project)

        # NEW KEY: ids["derived_files"] — list of relative paths excluded as tool/editor/VCS
        # backups. Must exist on every characterize_project() call.
        assert "derived_files" in result["ids"], (
            "result['ids'] must contain a 'derived_files' key"
        )
        derived = result["ids"]["derived_files"]
        assert backup_rel in derived, (
            f"bold-backup path '{backup_rel}' must appear in ids['derived_files']"
        )


# ---------------------------------------------------------------------------
# Scenario Outline: Editor and VCS backup variants are excluded
# Gherkin: STORY-024-x.md (real) + each backup variant (same id STORY-024)
#          => duplicate_count == 0, variant not counted as work item,
#             variant listed in ids["derived_files"]
#
# Note: .md.bak / .md~ / .md.orig files are not picked up by the current
# WORK_ITEM_RE (which requires suffix .md), so the duplicate/prefix assertions
# already pass by accident.  The derived_files assertion is the S1 contract —
# the implementation must explicitly classify and record these paths.
# ---------------------------------------------------------------------------

class TestEditorAndVcsBackupVariants:
    @pytest.mark.parametrize("backup_rel", [
        "backlog/stories/STORY-024-x.md.bak",
        "backlog/stories/STORY-024-x.md~",
        "backlog/stories/STORY-024-x.md.orig",
        "backlog/stories/STORY-024-x.bold-backup-1.md",
    ])
    def test_backup_variant_does_not_cause_duplicate(self, tmp_path, backup_rel):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-024-x.md", frontmatter_id="STORY-024")
        _write_md(project, backup_rel, frontmatter_id="STORY-024")

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 0, (
            f"backup variant '{backup_rel}' must not inflate duplicate_count"
        )

    @pytest.mark.parametrize("backup_rel", [
        "backlog/stories/STORY-024-x.md.bak",
        "backlog/stories/STORY-024-x.md~",
        "backlog/stories/STORY-024-x.md.orig",
        "backlog/stories/STORY-024-x.bold-backup-1.md",
    ])
    def test_backup_variant_not_counted_as_work_item(self, tmp_path, backup_rel):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-024-x.md", frontmatter_id="STORY-024")
        _write_md(project, backup_rel, frontmatter_id="STORY-024")

        result = characterize_project(project)

        # Prefix count must be 1 (the real file only)
        assert result["counts"]["prefixes"].get("STORY", 0) == 1, (
            f"backup variant '{backup_rel}' must not increment prefix count"
        )

    @pytest.mark.parametrize("backup_rel", [
        "backlog/stories/STORY-024-x.md.bak",
        "backlog/stories/STORY-024-x.md~",
        "backlog/stories/STORY-024-x.md.orig",
        "backlog/stories/STORY-024-x.bold-backup-1.md",
    ])
    def test_backup_variant_listed_in_derived_files(self, tmp_path, backup_rel):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-024-x.md", frontmatter_id="STORY-024")
        _write_md(project, backup_rel, frontmatter_id="STORY-024")

        result = characterize_project(project)

        # NEW KEY: ids["derived_files"] must explicitly list every excluded backup path.
        # The implementation must detect all backup patterns, not just the ones that happen
        # to be excluded by virtue of not being .md files.
        assert "derived_files" in result["ids"], (
            "result['ids'] must contain a 'derived_files' key"
        )
        assert backup_rel in result["ids"]["derived_files"], (
            f"backup variant '{backup_rel}' must be listed in ids['derived_files']"
        )


# ---------------------------------------------------------------------------
# Scenario: Genuine duplicates (no backup involved) are still flagged
# Gherkin: STORY-007-a.md + STORY-007-b.md (both id STORY-007)
#          => duplicate_count == 1, both files listed in the duplicate group
# ---------------------------------------------------------------------------

class TestGenuineDuplicatesStillFlagged:
    def test_genuine_duplicate_is_counted(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/stories/STORY-007-b.md", frontmatter_id="STORY-007")

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 1, (
            "genuine duplicate (two real .md files, same id) must be counted"
        )

    def test_genuine_duplicate_group_lists_both_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/stories/STORY-007-b.md", frontmatter_id="STORY-007")

        result = characterize_project(project)

        duplicates = {entry["id"]: entry["files"] for entry in result["ids"]["duplicates"]}
        assert "STORY-007" in duplicates, "STORY-007 must appear in duplicates list"
        group = duplicates["STORY-007"]
        assert "backlog/stories/STORY-007-a.md" in group, "first real file must be in group"
        assert "backlog/stories/STORY-007-b.md" in group, "second real file must be in group"


# ---------------------------------------------------------------------------
# Scenario: Supporting documents are not counted as migratable work items
# Gherkin: FOUNDATION.md, BACKLOG-INDEX.md, epic-034-prd-draft-v1.0-20260525.md,
#          test-harness-user-personas-draft-v1.0.md — all with no frontmatter
#          => none counted as work items, all reported under documents inventory
#
# Note: these filenames never matched WORK_ITEM_RE (no known prefix), so prefix/id
# count assertions already pass.  The documents["supporting"] key is the new S1
# contract — the implementation must classify and record them explicitly.
# ---------------------------------------------------------------------------

class TestSupportingDocumentsExcluded:
    SUPPORTING_DOCS = [
        "FOUNDATION.md",
        "backlog/BACKLOG-INDEX.md",
        "epic-034-prd-draft-v1.0-20260525.md",
        "test-harness-user-personas-draft-v1.0.md",
    ]

    def _make_project_with_docs(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        for rel in self.SUPPORTING_DOCS:
            _write_md(project, rel, frontmatter_id=None)
        return project

    def test_supporting_docs_not_counted_as_work_items_in_prefix_counts(self, tmp_path):
        project = self._make_project_with_docs(tmp_path)

        result = characterize_project(project)

        total_prefixes = sum(result["counts"]["prefixes"].values())
        assert total_prefixes == 0, (
            "supporting documents must not contribute to prefix work-item counts"
        )

    def test_supporting_docs_appear_in_documents_inventory(self, tmp_path):
        project = self._make_project_with_docs(tmp_path)

        result = characterize_project(project)

        # NEW KEY: result["documents"]["supporting"] — list of relative paths classified as
        # supporting documents (PRD/brief/FOUNDATION/index/personas).  Must exist even when
        # empty; when populated, each supporting doc's relative path must appear in it.
        assert "documents" in result, (
            "result must contain a 'documents' key"
        )
        assert "supporting" in result["documents"], (
            "result['documents'] must contain a 'supporting' key"
        )
        supporting = result["documents"]["supporting"]
        for doc in self.SUPPORTING_DOCS:
            assert doc in supporting, (
                f"'{doc}' must appear in documents['supporting']"
            )

    def test_supporting_docs_not_in_work_item_ids(self, tmp_path):
        project = self._make_project_with_docs(tmp_path)

        result = characterize_project(project)

        assert result["ids"]["unique_count"] == 0, (
            "supporting documents must not contribute to ids['unique_count']"
        )

    def test_documents_key_exists_even_without_supporting_docs(self, tmp_path):
        # Regression guard: the documents key must be present even on a project
        # that has no supporting documents at all.
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-task.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        # NEW KEY: documents must always be present
        assert "documents" in result, (
            "result must always contain a 'documents' key"
        )
        assert "supporting" in result["documents"], (
            "result['documents'] must always contain a 'supporting' key"
        )
        assert result["documents"]["supporting"] == [], (
            "documents['supporting'] must be empty when no supporting docs exist"
        )


# ---------------------------------------------------------------------------
# Scenario: Bespoke epic/story tree is recognized
# Gherkin: stories/EPIC-003/EPIC-003.md (no frontmatter)
#          stories/EPIC-003/US-DM-002.md (no frontmatter)
#          stories/EPIC-003/US-DM-002.feature
#          => EPIC-003 is epic-shaped, US-DM-002 is story-shaped with parent EPIC-003,
#             US-DM-002 records paired feature file
# ---------------------------------------------------------------------------

class TestBespokeEpicStoryTreeRecognized:
    def _make_epic_tree(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/US-DM-002.md", frontmatter_id=None)
        _write_feature(project, "stories/EPIC-003/US-DM-002.feature")
        return project

    def test_items_key_exists(self, tmp_path):
        project = self._make_epic_tree(tmp_path)

        result = characterize_project(project)

        # NEW KEY: result["items"] — top-level container for bespoke shape recognition
        assert "items" in result, "result must contain an 'items' key"

    def test_epic_003_recognized_as_epic_shaped(self, tmp_path):
        project = self._make_epic_tree(tmp_path)

        result = characterize_project(project)

        # NEW KEY: result["items"]["epics"] — list of {id, path} for EPIC-NNN shapes
        assert "items" in result, "result must contain an 'items' key"
        assert "epics" in result["items"], "result['items'] must contain an 'epics' key"
        epic_ids = [e["id"] for e in result["items"]["epics"]]
        assert "EPIC-003" in epic_ids, "EPIC-003 must be recognized as an epic-shaped item"

    def test_us_dm_002_recognized_as_story_shaped(self, tmp_path):
        project = self._make_epic_tree(tmp_path)

        result = characterize_project(project)

        # NEW KEY: result["items"]["stories"] — list of {id, path, parent_epic, feature_file}
        assert "items" in result, "result must contain an 'items' key"
        assert "stories" in result["items"], "result['items'] must contain a 'stories' key"
        story_ids = [s["id"] for s in result["items"]["stories"]]
        assert "US-DM-002" in story_ids, "US-DM-002 must be recognized as a story-shaped item"

    def test_us_dm_002_has_parent_epic_set_to_epic_003(self, tmp_path):
        project = self._make_epic_tree(tmp_path)

        result = characterize_project(project)

        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-DM-002" in stories, "US-DM-002 must appear in items['stories']"
        assert stories["US-DM-002"]["parent_epic"] == "EPIC-003", (
            "US-DM-002 parent_epic must be 'EPIC-003' (the containing EPIC-NNN directory name)"
        )

    def test_us_dm_002_records_paired_feature_file(self, tmp_path):
        project = self._make_epic_tree(tmp_path)

        result = characterize_project(project)

        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-DM-002" in stories, "US-DM-002 must appear in items['stories']"
        feature_file = stories["US-DM-002"].get("feature_file")
        assert feature_file is not None, (
            "US-DM-002 must record its paired .feature file path (not None)"
        )
        assert "US-DM-002.feature" in feature_file, (
            "feature_file must contain the .feature filename"
        )

    def test_story_without_paired_feature_has_feature_file_none(self, tmp_path):
        # Guard: a US-* story with no matching .feature must record feature_file=None
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-005/EPIC-005.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-005/US-AB-001.md", frontmatter_id=None)
        # no .feature file written

        result = characterize_project(project)

        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-AB-001" in stories, "US-AB-001 must appear in items['stories']"
        assert stories["US-AB-001"]["feature_file"] is None, (
            "feature_file must be None when no paired .feature exists"
        )


# ---------------------------------------------------------------------------
# Scenario: A project whose only duplicates are backups characterizes as clean
# Gherkin: every duplicate id is caused only by a backup file
#          => duplicate_count == 0, v4_compliance.no_duplicates is True
# ---------------------------------------------------------------------------

class TestBackupOnlyDuplicatesCharacterizeAsClean:
    def test_backup_only_collisions_yield_zero_duplicates(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/MS-010-feature.md", frontmatter_id="MS-010")
        _write_md(
            project,
            "backlog/MS-010-feature.bold-backup-20260614-090000.md",
            frontmatter_id="MS-010",
        )
        _write_md(project, "backlog/ISSUE-055-task.md", frontmatter_id="ISSUE-055")
        _write_md(project, "backlog/ISSUE-055-task.md.bak", frontmatter_id="ISSUE-055")

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 0, (
            "when every id collision involves only a backup file, duplicate_count must be 0"
        )

    def test_backup_only_collisions_set_v4_no_duplicates_true(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/MS-010-feature.md", frontmatter_id="MS-010")
        _write_md(
            project,
            "backlog/MS-010-feature.bold-backup-20260614-090000.md",
            frontmatter_id="MS-010",
        )

        result = characterize_project(project)

        assert result["v4_compliance"]["no_duplicates"] is True, (
            "v4_compliance.no_duplicates must be True when only backups cause id collisions"
        )


# ---------------------------------------------------------------------------
# Scenario: Backup exclusion does not change counts when there are no backups
# Gherkin: product tree with no backup or derived files
#          => work-item and duplicate counts identical to pre-change behavior
# ---------------------------------------------------------------------------

class TestNoOpRegressionWithoutBackups:
    def test_clean_tree_prefix_counts_unaffected(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")
        _write_md(project, "backlog/ISSUE-002-beta.md", frontmatter_id="ISSUE-002")
        _write_md(project, "backlog/MS-001-milestone.md", frontmatter_id="MS-001")

        result = characterize_project(project)

        assert result["counts"]["prefixes"] == {"ISSUE": 2, "MS": 1}, (
            "prefix counts must be unchanged when no backup files are present"
        )

    def test_clean_tree_duplicate_count_zero(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")
        _write_md(project, "backlog/ISSUE-002-beta.md", frontmatter_id="ISSUE-002")

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 0, (
            "duplicate_count must remain 0 on a clean tree with no backups"
        )

    def test_clean_tree_derived_files_list_is_empty(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        # NEW KEY: ids["derived_files"] must always be present; must be empty here
        assert "derived_files" in result["ids"], (
            "ids['derived_files'] must exist even when there are no backup files"
        )
        assert result["ids"]["derived_files"] == [], (
            "ids['derived_files'] must be [] when no backup files are present"
        )


# ===========================================================================
# NEW TESTS — Agreed resolving rules from QA review
# ===========================================================================

# ---------------------------------------------------------------------------
# Rule 1 / Rule 3: Backup suffix-anchoring and classification precedence
# A project with only one ISSUE file: all new keys must be present and empty.
# ---------------------------------------------------------------------------

class TestEmptyNewKeysOnIssueOnlyProject:
    """
    items.epics == [], items.stories == [], documents.supporting == [],
    ids.derived_files == [] when the product tree has only
    backlog/ISSUE-001-alpha.md (no epic dirs, no docs, no backups).
    """

    def test_items_epics_empty(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        # Fails on missing key until items key is implemented
        assert "items" in result, "result must have an 'items' key"
        assert result["items"]["epics"] == [], (
            "items.epics must be [] when no EPIC-NNN dirs exist"
        )

    def test_items_stories_empty(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        assert "items" in result, "result must have an 'items' key"
        assert result["items"]["stories"] == [], (
            "items.stories must be [] when no US-* files in EPIC dirs exist"
        )

    def test_documents_supporting_empty(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        assert "documents" in result, "result must have a 'documents' key"
        assert "supporting" in result["documents"], "result['documents'] must have 'supporting'"
        assert result["documents"]["supporting"] == [], (
            "documents.supporting must be [] when no supporting docs exist"
        )

    def test_ids_derived_files_empty(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")

        result = characterize_project(project)

        assert "derived_files" in result["ids"], "ids must have 'derived_files' key"
        assert result["ids"]["derived_files"] == [], (
            "ids.derived_files must be [] when no backups exist"
        )


# ---------------------------------------------------------------------------
# Rule 6: path is product-base-RELATIVE and points to the FILE
# ---------------------------------------------------------------------------

class TestRelativeFilePaths:
    def _make_tree(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/US-DM-002.md", frontmatter_id=None)
        return project

    def test_epic_path_is_relative_file_path(self, tmp_path):
        project = self._make_tree(tmp_path)

        result = characterize_project(project)

        # Fails until items key and correct path value are implemented
        assert "items" in result, "result must have an 'items' key"
        assert "epics" in result["items"], "result['items'] must have 'epics'"
        epics = {e["id"]: e for e in result["items"]["epics"]}
        assert "EPIC-003" in epics, "EPIC-003 must be in items.epics"
        assert epics["EPIC-003"]["path"] == "stories/EPIC-003/EPIC-003.md", (
            "epic path must be product-base-relative and point to EPIC-003.md file"
        )

    def test_story_path_is_relative_file_path(self, tmp_path):
        project = self._make_tree(tmp_path)

        result = characterize_project(project)

        assert "items" in result, "result must have an 'items' key"
        assert "stories" in result["items"], "result['items'] must have 'stories'"
        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-DM-002" in stories, "US-DM-002 must be in items.stories"
        assert stories["US-DM-002"]["path"] == "stories/EPIC-003/US-DM-002.md", (
            "story path must be product-base-relative and point to the US-*.md file"
        )


# ---------------------------------------------------------------------------
# Rule 2: Backups excluded BEFORE counting
# Real MS-001 + backup MS-001 → unique_count counts MS-001 once.
# Backup-only id → absent from ids entirely, unique_count unaffected.
# ---------------------------------------------------------------------------

class TestBackupExcludedBeforeCounting:
    def test_real_plus_backup_unique_count_is_one(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "milestones/MS-001-core.md", frontmatter_id="MS-001")
        _write_md(
            project,
            "milestones/MS-001-core.bold-backup-20260601.md",
            frontmatter_id="MS-001",
        )

        result = characterize_project(project)

        # The key contract here is that the backup is excluded BEFORE counting:
        # unique_count == 1, AND prefix MS == 1 (not 2).
        assert result["ids"]["unique_count"] == 1, (
            "unique_count must count MS-001 exactly once when paired with a backup"
        )
        # This is the tight assertion: backup must not inflate prefix count
        assert result["counts"]["prefixes"].get("MS", 0) == 1, (
            "prefix count for MS must be 1 (backup excluded before counting)"
        )

    def test_backup_only_id_absent_from_ids(self, tmp_path):
        project = _make_product_tree(tmp_path)
        # No real MS-099 file — only a backup
        _write_md(
            project,
            "milestones/MS-099-x.bold-backup-20260601.md",
            frontmatter_id="MS-099",
        )

        result = characterize_project(project)

        # MS-099 backup must be in derived_files and must NOT register as a real id
        assert "derived_files" in result["ids"], "ids must have 'derived_files' key"
        assert result["ids"]["unique_count"] == 0, (
            "a backup-only id must not register in unique_count"
        )
        assert result["counts"]["prefixes"].get("MS", 0) == 0, (
            "a backup-only file must not contribute to prefix counts"
        )


# ---------------------------------------------------------------------------
# Rule 1 over-reach guard: markers mid-slug are NOT backup suffixes
# The test pins that derived_files key exists AND the over-reach files are absent.
# ---------------------------------------------------------------------------

class TestBackupMarkerMidSlugIsNotBackup:
    def test_story_with_backup_in_slug_counted_as_work_item(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "backlog/stories/STORY-041-backup-and-restore.md",
            frontmatter_id="STORY-041",
        )

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("STORY", 0) == 1, (
            "STORY-041-backup-and-restore.md must be counted as a real work item"
        )

    def test_story_with_backup_in_slug_not_in_derived_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "backlog/stories/STORY-041-backup-and-restore.md",
            frontmatter_id="STORY-041",
        )

        result = characterize_project(project)

        # The key must exist (not just absent); then the file must not be in it.
        assert "derived_files" in result["ids"], (
            "ids['derived_files'] key must exist — over-reach guard requires the key to be implemented"
        )
        assert "backlog/stories/STORY-041-backup-and-restore.md" not in result["ids"]["derived_files"], (
            "STORY-041-backup-and-restore.md must NOT be in derived_files — marker mid-slug is not a backup suffix"
        )

    def test_ms_with_orig_in_slug_counted_as_work_item(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "milestones/MS-007-rollback-orig-api.md",
            frontmatter_id="MS-007",
        )

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("MS", 0) == 1, (
            "MS-007-rollback-orig-api.md must be counted as a real work item"
        )

    def test_ms_with_orig_in_slug_not_in_derived_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "milestones/MS-007-rollback-orig-api.md",
            frontmatter_id="MS-007",
        )

        result = characterize_project(project)

        # Key must exist; then the file must be absent from it.
        assert "derived_files" in result["ids"], (
            "ids['derived_files'] key must exist"
        )
        assert "milestones/MS-007-rollback-orig-api.md" not in result["ids"]["derived_files"], (
            "MS-007-rollback-orig-api.md must NOT be in derived_files — 'orig' mid-slug is not a backup suffix"
        )


# ---------------------------------------------------------------------------
# Mixed collision: real-a + real-b + backup → duplicate_count==1,
# group lists exactly the two real files, backup in derived_files.
# ---------------------------------------------------------------------------

class TestMixedCollisionRealPlusBackup:
    def test_mixed_collision_duplicate_count_is_one(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/stories/STORY-007-b.md", frontmatter_id="STORY-007")
        _write_md(
            project,
            "backlog/stories/STORY-007-a.bold-backup-1.md",
            frontmatter_id="STORY-007",
        )

        result = characterize_project(project)

        # With current code the backup counts as a third real entry, still yielding
        # duplicate_count==1, so this assertion must also demand prefix count == 2.
        assert result["ids"]["duplicate_count"] == 1, (
            "duplicate_count must be 1: two real files collide; the backup does not count"
        )
        # Tight assertion: only 2 STORY prefix entries (backup excluded)
        assert result["counts"]["prefixes"].get("STORY", 0) == 2, (
            "prefix count for STORY must be 2 (the two real files; backup excluded)"
        )

    def test_mixed_collision_group_lists_only_real_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/stories/STORY-007-b.md", frontmatter_id="STORY-007")
        _write_md(
            project,
            "backlog/stories/STORY-007-a.bold-backup-1.md",
            frontmatter_id="STORY-007",
        )

        result = characterize_project(project)

        duplicates = {entry["id"]: entry["files"] for entry in result["ids"]["duplicates"]}
        assert "STORY-007" in duplicates, "STORY-007 must appear in duplicates"
        group = duplicates["STORY-007"]
        assert "backlog/stories/STORY-007-a.md" in group, "real file a must be in group"
        assert "backlog/stories/STORY-007-b.md" in group, "real file b must be in group"
        assert "backlog/stories/STORY-007-a.bold-backup-1.md" not in group, (
            "backup must NOT appear in the duplicate group"
        )

    def test_mixed_collision_backup_in_derived_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-007-a.md", frontmatter_id="STORY-007")
        _write_md(project, "backlog/stories/STORY-007-b.md", frontmatter_id="STORY-007")
        backup_rel = "backlog/stories/STORY-007-a.bold-backup-1.md"
        _write_md(project, backup_rel, frontmatter_id="STORY-007")

        result = characterize_project(project)

        assert "derived_files" in result["ids"], "ids must have 'derived_files' key"
        assert backup_rel in result["ids"]["derived_files"], (
            "backup must be listed in ids.derived_files even when real duplicates exist"
        )


# ---------------------------------------------------------------------------
# Rule 3: Backup of a document → derived_files, NOT documents.supporting
# ---------------------------------------------------------------------------

class TestBackupOfDocumentGoesToDerivedNotSupporting:
    def test_doc_bak_in_derived_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        bak = product_base / "FOUNDATION.md.bak"
        bak.parent.mkdir(parents=True, exist_ok=True)
        bak.write_text("# stale backup\n", encoding="utf-8")

        result = characterize_project(project)

        assert "derived_files" in result["ids"], "ids must have 'derived_files' key"
        assert "FOUNDATION.md.bak" in result["ids"]["derived_files"], (
            "FOUNDATION.md.bak must be listed in ids.derived_files"
        )

    def test_doc_bak_not_in_documents_supporting(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        bak = product_base / "FOUNDATION.md.bak"
        bak.parent.mkdir(parents=True, exist_ok=True)
        bak.write_text("# stale backup\n", encoding="utf-8")

        result = characterize_project(project)

        # Must require key to exist, then check absence
        assert "documents" in result, "result must have a 'documents' key"
        assert "supporting" in result["documents"], "result['documents'] must have 'supporting'"
        assert "FOUNDATION.md.bak" not in result["documents"]["supporting"], (
            "FOUNDATION.md.bak must NOT appear in documents.supporting"
        )


# ---------------------------------------------------------------------------
# Rule 4: Bespoke epic file = exactly EPIC-<NNN>.md
# EPIC-NNN-index.md is a document, not an epic, duplicate_count == 0
# ---------------------------------------------------------------------------

class TestEpicIndexIsDocument:
    def test_epic_index_not_in_items_epics(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/EPIC-003-index.md", frontmatter_id=None)

        result = characterize_project(project)

        # Fails on missing key until items key is implemented
        assert "items" in result, "result must have 'items' key"
        assert "epics" in result["items"], "result['items'] must have 'epics'"
        epic_ids = [e["id"] for e in result["items"]["epics"]]
        for eid in epic_ids:
            assert "index" not in eid.lower(), (
                f"EPIC-003-index.md must not produce an epic entry; got epic id '{eid}'"
            )

    def test_epic_003_still_in_epics(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/EPIC-003-index.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "items" in result, "result must have 'items' key"
        assert "epics" in result["items"], "result['items'] must have 'epics'"
        epic_ids = [e["id"] for e in result["items"]["epics"]]
        assert "EPIC-003" in epic_ids, (
            "EPIC-003.md must still appear in items.epics alongside EPIC-003-index.md"
        )

    def test_epic_index_in_documents_supporting(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/EPIC-003-index.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "documents" in result, "result must have 'documents' key"
        assert "supporting" in result["documents"], "result['documents'] must have 'supporting'"
        supporting = result["documents"]["supporting"]
        assert "stories/EPIC-003/EPIC-003-index.md" in supporting, (
            "EPIC-003-index.md must appear in documents.supporting (it is a document, not an epic)"
        )

    def test_epic_index_does_not_create_duplicate(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/EPIC-003-index.md", frontmatter_id=None)

        result = characterize_project(project)

        assert result["ids"]["duplicate_count"] == 0, (
            "EPIC-003 + EPIC-003-index.md must NOT produce a duplicate_count > 0"
        )


# ---------------------------------------------------------------------------
# Rule 3: Dual-classification — work item with doc keywords in slug
# A file with a valid work-item id must be a work item, not a supporting doc.
# The tight assertion: documents key exists AND the file is absent from it.
# ---------------------------------------------------------------------------

class TestDualClassificationWorkItemWinsOverDoc:
    def test_issue_with_prd_in_slug_counted_as_work_item(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "backlog/ISSUE-001-prd-brief.md",
            frontmatter_id="ISSUE-001",
        )

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("ISSUE", 0) == 1, (
            "ISSUE-001-prd-brief.md with valid work-item id must be counted as a work item"
        )

    def test_issue_with_prd_in_slug_not_in_documents_supporting(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "backlog/ISSUE-001-prd-brief.md",
            frontmatter_id="ISSUE-001",
        )

        result = characterize_project(project)

        # Must require key to exist, then assert absence
        assert "documents" in result, "result must have a 'documents' key"
        assert "supporting" in result["documents"], "result['documents'] must have 'supporting'"
        assert "backlog/ISSUE-001-prd-brief.md" not in result["documents"]["supporting"], (
            "a file with a valid work-item id must NOT be classified as a supporting document"
        )


# ---------------------------------------------------------------------------
# Rule 5: parent_epic = nearest ANCESTOR dir matching ^(EPIC|BL)-\d+$
# US under BL dir: backlog/stories/BL-027/US-BL027-002-x.md → parent_epic == "BL-027"
# ---------------------------------------------------------------------------

class TestParentEpicBLDirectory:
    def test_us_under_bl_dir_has_parent_epic_bl(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(
            project,
            "backlog/stories/BL-027/US-BL027-002-x.md",
            frontmatter_id=None,
        )

        result = characterize_project(project)

        assert "items" in result, "result must have 'items' key"
        assert "stories" in result["items"], "result['items'] must have 'stories'"
        stories = {s["id"]: s for s in result["items"]["stories"]}
        matching = [sid for sid in stories if sid.startswith("US-BL027-002")]
        assert matching, (
            "a story with id starting with 'US-BL027-002' must appear in items.stories"
        )
        story = stories[matching[0]]
        assert story["parent_epic"] == "BL-027", (
            f"story under BL-027/ must have parent_epic == 'BL-027', got {story['parent_epic']!r}"
        )


# ---------------------------------------------------------------------------
# Rule 5: Orphan epic dir — EPIC-007 dir with a story but no EPIC-007.md
# → "EPIC-007" not in items.epics ids; story's parent_epic == "EPIC-007"
# ---------------------------------------------------------------------------

class TestOrphanEpicDirectory:
    def test_orphan_epic_dir_not_in_epics(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-007/US-AB-001.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "items" in result, "result must have 'items' key"
        assert "epics" in result["items"], "result['items'] must have 'epics'"
        epic_ids = [e["id"] for e in result["items"]["epics"]]
        assert "EPIC-007" not in epic_ids, (
            "EPIC-007 must not appear in items.epics when EPIC-007.md does not exist"
        )

    def test_story_in_orphan_epic_dir_has_parent_epic_set(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-007/US-AB-001.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "items" in result, "result must have 'items' key"
        assert "stories" in result["items"], "result['items'] must have 'stories'"
        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-AB-001" in stories, "US-AB-001 must appear in items.stories"
        assert stories["US-AB-001"]["parent_epic"] == "EPIC-007", (
            "story in EPIC-007/ must have parent_epic == 'EPIC-007' even when EPIC-007.md is absent"
        )


# ---------------------------------------------------------------------------
# Rule 5: Nested US — stories/EPIC-003/done/US-DM-050.md → parent_epic == "EPIC-003"
# ---------------------------------------------------------------------------

class TestNestedStoryParentEpic:
    def test_nested_us_has_correct_parent_epic(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/done/US-DM-050.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "items" in result, "result must have 'items' key"
        assert "stories" in result["items"], "result['items'] must have 'stories'"
        stories = {s["id"]: s for s in result["items"]["stories"]}
        assert "US-DM-050" in stories, "US-DM-050 must appear in items.stories"
        assert stories["US-DM-050"]["parent_epic"] == "EPIC-003", (
            "nested story under stories/EPIC-003/done/ must have parent_epic == 'EPIC-003'"
        )


# ---------------------------------------------------------------------------
# Orphan .feature: stories/EPIC-003/US-DM-099.feature with no matching .md
# → no story record with id US-DM-099; characterize_project does not raise
# ---------------------------------------------------------------------------

class TestOrphanFeatureFile:
    def test_orphan_feature_does_not_raise(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_feature(project, "stories/EPIC-003/US-DM-099.feature")

        result = characterize_project(project)

        # Requires items key to exist (making it RED until implemented)
        assert "items" in result, "result must contain an 'items' key"
        assert isinstance(result, dict), "characterize_project must return a dict"

    def test_orphan_feature_does_not_produce_story_record(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_feature(project, "stories/EPIC-003/US-DM-099.feature")

        result = characterize_project(project)

        # Requires items key; then checks US-DM-099 absent
        assert "items" in result, "result must contain an 'items' key"
        story_ids = [s["id"] for s in result["items"].get("stories", [])]
        assert "US-DM-099" not in story_ids, (
            "an orphan .feature with no matching .md must not produce a story record"
        )


# ---------------------------------------------------------------------------
# Type-scope guards:
# .yaml files → not counted in prefix counts
# .feature files → counted in product_files but not markdown_files, not in any prefix
# ---------------------------------------------------------------------------

class TestTypeScopeGuards:
    def test_yaml_file_not_counted_in_issue_prefix(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        yaml_file = product_base / "backlog" / "ISSUE-007-task.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text("id: ISSUE-007\ntitle: task\n", encoding="utf-8")

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("ISSUE", 0) == 0, (
            "a .yaml file must not be counted in prefix work-item counts"
        )

    def test_feature_file_counted_in_product_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_feature(project, "stories/EPIC-003/US-DM-010.feature")

        result = characterize_project(project)

        # product_files includes both .md and .feature
        # Currently passes; kept here as regression guard for the type-scope contract
        assert result["counts"]["product_files"] >= 2, (
            ".feature files must be counted in counts.product_files (need at least 2: the .md and the .feature)"
        )

    def test_feature_file_not_counted_in_markdown_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_feature(project, "stories/EPIC-003/US-DM-010.feature")
        product_base = project / "docs" / "product"
        (product_base / "stories" / "EPIC-003").mkdir(parents=True, exist_ok=True)

        result = characterize_project(project)

        assert result["counts"]["markdown_files"] == 0, (
            ".feature files must NOT be counted in counts.markdown_files"
        )

    def test_feature_file_not_in_prefix_counts(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_feature(project, "backlog/ISSUE-007.feature")

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("ISSUE", 0) == 0, (
            "a .feature file must not be counted in prefix counts"
        )


# ---------------------------------------------------------------------------
# Loose docs: docs/product/epic-034-stories.md (lowercase, no frontmatter)
# → documents.supporting
# ---------------------------------------------------------------------------

class TestLooseDocsInSupportingDocuments:
    def test_lowercase_loose_doc_in_supporting(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "docs/product/epic-034-stories.md", frontmatter_id=None)

        result = characterize_project(project)

        assert "documents" in result, "result must have 'documents' key"
        assert "supporting" in result["documents"], "result['documents'] must have 'supporting'"
        supporting = result["documents"]["supporting"]
        assert "docs/product/epic-034-stories.md" in supporting, (
            "docs/product/epic-034-stories.md (lowercase, no frontmatter) must appear in documents.supporting"
        )


# ---------------------------------------------------------------------------
# Determinism: two calls yield identical sorted lists for all new keys
# ---------------------------------------------------------------------------

class TestDeterminism:
    def _make_mixed_tree(self, tmp_path: Path) -> Path:
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/ISSUE-001-alpha.md", frontmatter_id="ISSUE-001")
        _write_md(project, "backlog/ISSUE-002-beta.md", frontmatter_id="ISSUE-002")
        _write_md(
            project,
            "backlog/ISSUE-001-alpha.bold-backup-1.md",
            frontmatter_id="ISSUE-001",
        )
        _write_md(project, "FOUNDATION.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/EPIC-003.md", frontmatter_id=None)
        _write_md(project, "stories/EPIC-003/US-DM-002.md", frontmatter_id=None)
        return project

    def test_derived_files_deterministic(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = characterize_project(project)
        r2 = characterize_project(project)

        # Fails if key absent or not sorted
        assert "derived_files" in r1["ids"], "ids must have 'derived_files' key"
        assert r1["ids"]["derived_files"] == r2["ids"]["derived_files"], (
            "ids.derived_files must be identical across two calls"
        )
        assert r1["ids"]["derived_files"] == sorted(r1["ids"]["derived_files"]), (
            "ids.derived_files must be sorted"
        )

    def test_supporting_documents_deterministic(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = characterize_project(project)
        r2 = characterize_project(project)

        assert "documents" in r1, "result must have 'documents' key"
        assert r1["documents"]["supporting"] == r2["documents"]["supporting"], (
            "documents.supporting must be identical across two calls"
        )
        assert r1["documents"]["supporting"] == sorted(r1["documents"]["supporting"]), (
            "documents.supporting must be sorted"
        )

    def test_items_epics_deterministic(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = characterize_project(project)
        r2 = characterize_project(project)

        assert "items" in r1, "result must have 'items' key"
        ids1 = [e["id"] for e in r1["items"]["epics"]]
        ids2 = [e["id"] for e in r2["items"]["epics"]]
        assert ids1 == ids2, "items.epics ids must be identical across two calls"
        assert ids1 == sorted(ids1), "items.epics must be sorted by id"

    def test_items_stories_deterministic(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = characterize_project(project)
        r2 = characterize_project(project)

        assert "items" in r1, "result must have 'items' key"
        ids1 = [s["id"] for s in r1["items"]["stories"]]
        ids2 = [s["id"] for s in r2["items"]["stories"]]
        assert ids1 == ids2, "items.stories ids must be identical across two calls"
        assert ids1 == sorted(ids1), "items.stories must be sorted by id"


# ---------------------------------------------------------------------------
# Rule 1: Case-insensitive backup detection
# STORY-024-x.md.BAK (uppercase) → in derived_files
# ---------------------------------------------------------------------------

class TestCaseInsensitiveBackupDetection:
    def test_uppercase_bak_suffix_in_derived_files(self, tmp_path):
        project = _make_product_tree(tmp_path)
        _write_md(project, "backlog/stories/STORY-024-x.md", frontmatter_id="STORY-024")
        product_base = project / "docs" / "product"
        bak_file = product_base / "backlog" / "stories" / "STORY-024-x.md.BAK"
        bak_file.parent.mkdir(parents=True, exist_ok=True)
        bak_file.write_text("backup content\n", encoding="utf-8")

        result = characterize_project(project)

        assert "derived_files" in result["ids"], "ids must have 'derived_files' key"
        assert "backlog/stories/STORY-024-x.md.BAK" in result["ids"]["derived_files"], (
            "STORY-024-x.md.BAK (uppercase .BAK) must be detected as a backup and listed in derived_files"
        )

    def test_uppercase_bak_not_counted_as_work_item(self, tmp_path):
        project = _make_product_tree(tmp_path)
        product_base = project / "docs" / "product"
        bak_file = product_base / "backlog" / "stories" / "STORY-024-x.md.BAK"
        bak_file.parent.mkdir(parents=True, exist_ok=True)
        bak_file.write_text("backup content\n", encoding="utf-8")

        result = characterize_project(project)

        assert result["counts"]["prefixes"].get("STORY", 0) == 0, (
            ".md.BAK must not contribute to prefix counts"
        )
