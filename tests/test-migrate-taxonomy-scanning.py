"""
Tests for source file scanning — Feature: Source file scanning
Translates: tests/features/issue-090-migrate-taxonomy-scanning.feature
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

from migrate.migrate_taxonomy import scan_sources

from fixtures.migrate_taxonomy_fixtures import (
    product_base,
    backlog_dir,
    done_dir,
    spike_dir,
    issues_dir,
    roadmap_dir,
    milestones_dir,
    artifact_privacy_path,
    project_dir,  # noqa: F401 — pytest fixture
)


# ---------------------------------------------------------------------------
# Scenario: Scan finds BL files in backlog
# ---------------------------------------------------------------------------

class TestScanFindsBLFiles:
    def test_scan_finds_two_bl_files_in_backlog(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n")
        (bl / "BL-042-bar.md").write_text("# BL-042: Bar\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 2
        for s in sources:
            assert s.entity_type == "BL"

    def test_scan_bl_files_includes_correct_entity_type(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-007-spy.md").write_text("# BL-007: Spy\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert any(s.entity_type == "BL" for s in sources)


# ---------------------------------------------------------------------------
# Scenario: Scan finds STORY files in done directory
# ---------------------------------------------------------------------------

class TestScanFindsSTORYFiles:
    def test_scan_finds_story_files_in_done_directory(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "STORY-015-alpha.md").write_text("# STORY-015: Alpha\n")
        (d / "STORY-016-beta.md").write_text("# STORY-016: Beta\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 2
        for s in sources:
            assert s.entity_type == "STORY"


# ---------------------------------------------------------------------------
# Scenario: Scan finds spike reports
# ---------------------------------------------------------------------------

class TestScanFindsSpikeReports:
    def test_scan_finds_spike_bl_files_in_spike_reports(self, project_dir):
        sd = spike_dir(project_dir)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "spike-BL-016-gstack.md").write_text("# Spike: gstack\n")
        (sd / "spike-BL-017-voice.md").write_text("# Spike: voice\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 2
        for s in sources:
            assert s.entity_type == "spike-BL"


# ---------------------------------------------------------------------------
# Scenario: Scan finds I-N files in issues directory
# ---------------------------------------------------------------------------

class TestScanFindsIFiles:
    def test_scan_finds_i_file_in_issues_directory(self, project_dir):
        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001-duplicate.md").write_text("# I-001: Duplicate\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 1
        assert sources[0].entity_type == "I"


# ---------------------------------------------------------------------------
# Scenario: Scan finds RM files in roadmap
# ---------------------------------------------------------------------------

class TestScanFindsRMFiles:
    def test_scan_finds_rm_file_in_roadmap(self, project_dir):
        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        (rm / "RM-001-mvp.md").write_text("# RM-001: MVP\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 1
        assert sources[0].entity_type == "RM"


# ---------------------------------------------------------------------------
# Scenario: Scan finds MS files in milestones
# ---------------------------------------------------------------------------

class TestScanFindsMSFiles:
    def test_scan_finds_ms_file_in_milestones(self, project_dir):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        (ms / "MS-007-tracked-workflows.md").write_text("# MS-007: Tracked\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 1
        assert sources[0].entity_type == "MS"


# ---------------------------------------------------------------------------
# Scenario: Scan finds EP files in backlog
# ---------------------------------------------------------------------------

class TestScanFindsEPFiles:
    def test_scan_finds_ep_file_in_backlog(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "EP-001-taxonomy.md").write_text("# EP-001: Taxonomy\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 1
        assert sources[0].entity_type == "EP"


# ---------------------------------------------------------------------------
# Scenario: Non-matching files are ignored
# ---------------------------------------------------------------------------

class TestNonMatchingFilesAreIgnored:
    def test_readme_and_already_migrated_issue_file_not_scanned(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "README.md").write_text("# README\n")
        (bl / "ISSUE-090-already-migrated.md").write_text("# ISSUE-090\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 0


# ---------------------------------------------------------------------------
# Scenario: Index files are not scanned
# ---------------------------------------------------------------------------

class TestIndexFilesNotScanned:
    def test_index_files_are_not_included_in_sources(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BACKLOG-INDEX.md").write_text("# Backlog Index\n")

        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "ISSUES-INDEX.md").write_text("# Issues Index\n")

        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        (ms / "MILESTONES-INDEX.md").write_text("# Milestones Index\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 0


# ---------------------------------------------------------------------------
# Scenario: Files in wrong subdirectory are ignored
# ---------------------------------------------------------------------------

class TestFilesInWrongSubdirectoryAreIgnored:
    def test_bl_file_in_done_is_not_a_valid_bl_source(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "BL-001.md").write_text("# BL-001\n")

        sd = spike_dir(project_dir)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "BL-002.md").write_text("# BL-002\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 0


# ---------------------------------------------------------------------------
# Scenario: CHORE, BUG, DEBT files are not source types
# ---------------------------------------------------------------------------

class TestChoreBugDebtNotSourceTypes:
    def test_chore_bug_debt_files_not_scanned(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "CHORE-010.md").write_text("# CHORE-010\n")
        (bl / "BUG-003.md").write_text("# BUG-003\n")
        (bl / "DEBT-005.md").write_text("# DEBT-005\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 0


# ---------------------------------------------------------------------------
# Scenario: Scan respects non-default product base
# ---------------------------------------------------------------------------

class TestScanRespectsNonDefaultProductBase:
    def test_scan_uses_custom_product_base_from_artifact_privacy(self, tmp_path):
        custom_base = tmp_path / ".sweetclaude" / "custom-product"
        bl = custom_base / "backlog"
        bl.mkdir(parents=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n")

        ap = tmp_path / ".sweetclaude" / "artifact-privacy.yaml"
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_text(yaml.safe_dump(
            {"product": {"base_path": ".sweetclaude/custom-product"}}
        ))

        sources = scan_sources(project_dir=str(tmp_path))

        assert len(sources) == 1
        assert ".sweetclaude/custom-product" in str(sources[0].path).replace("\\", "/")

    def test_scan_with_custom_base_source_path_under_custom_base(self, tmp_path):
        custom_base = tmp_path / ".sweetclaude" / "custom-product"
        bl = custom_base / "backlog"
        bl.mkdir(parents=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n")

        ap = tmp_path / ".sweetclaude" / "artifact-privacy.yaml"
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_text(yaml.safe_dump(
            {"product": {"base_path": ".sweetclaude/custom-product"}}
        ))

        sources = scan_sources(project_dir=str(tmp_path))

        assert str(custom_base) in str(sources[0].path)


# ---------------------------------------------------------------------------
# Scenario: BL file with leading zeros preserves raw_id
# ---------------------------------------------------------------------------

class TestBLFileWithLeadingZerosPreservesRawId:
    def test_bl_007_has_raw_id_007(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-007-spy.md").write_text("# BL-007: Spy\n")

        sources = scan_sources(project_dir=str(project_dir))

        assert len(sources) == 1
        assert sources[0].raw_id == "007"
