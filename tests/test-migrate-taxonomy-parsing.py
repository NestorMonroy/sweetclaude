"""
Tests for file parsing — Feature: File parsing
Translates: tests/features/issue-090-migrate-taxonomy-parsing.feature
"""
import hashlib
import os
import sys
import textwrap
import warnings
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import parse_file


def write_file(tmp_path, content):
    p = tmp_path / "test_file.md"
    p.write_text(textwrap.dedent(content).strip())
    return p


# ---------------------------------------------------------------------------
# Scenario: Parse YAML frontmatter file
# ---------------------------------------------------------------------------

class TestParseYAMLFrontmatterFile:
    def test_parse_yaml_frontmatter_all_fields(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: Widget builder
            status: open
            priority: P2
            type: enhancement
            epic: EP-001
            milestone: MS-007
            depends_on: [BL-040, BL-041]
            created: 2026-05-01
            updated: 2026-05-15
            ---

            # BL-042: Widget builder

            Build the widget builder component.
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["id"] == "BL-042"
        assert parsed["title"] == "Widget builder"
        assert parsed["status"] == "open"
        assert parsed["priority"] == "P2"
        assert parsed["epic"] == "EP-001"
        assert parsed["depends_on"] == ["BL-040", "BL-041"]
        assert "Build the widget builder component." in parsed["body"]


# ---------------------------------------------------------------------------
# Scenario: Parse markdown bold format file
# ---------------------------------------------------------------------------

class TestParseMarkdownBoldFormatFile:
    def test_parse_bold_format_extracts_metadata(self, tmp_path):
        content = """\
            # BL-042: Widget builder

            **Status:** Open
            **Priority:** P2
            **Epic:** EP-001

            Build the widget builder component.
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["title"] == "Widget builder"
        assert parsed["status"] == "open"
        assert parsed["priority"] == "P2"
        assert parsed["epic"] == "EP-001"
        assert "Build the widget builder component." in parsed["body"]


# ---------------------------------------------------------------------------
# Scenario: YAML frontmatter takes precedence over markdown bold
# ---------------------------------------------------------------------------

class TestYAMLFrontmatterTakesPrecedence:
    def test_yaml_title_overrides_markdown_title(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: YAML title
            status: active
            ---

            # BL-042: Markdown title

            **Status:** Open
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["title"] == "YAML title"
        assert parsed["status"] == "active"


# ---------------------------------------------------------------------------
# Scenario: Parse file with date-embedded status
# ---------------------------------------------------------------------------

class TestParseDateEmbeddedStatus:
    def test_done_status_with_em_dash_date_extracted(self, tmp_path):
        content = """\
            # BL-050: Old feature

            **Status:** DONE — 2026-05-02
            **Priority:** P3
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "done"
        assert parsed["closed_date"] == "2026-05-02"

    def test_done_status_with_em_dash_no_spaces_extracted(self, tmp_path):
        content = """\
            # BL-050: Old feature

            **Status:** DONE—2026-05-02
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "done"
        assert parsed["closed_date"] == "2026-05-02"


# ---------------------------------------------------------------------------
# Scenario: Parse file with reason-embedded status
# ---------------------------------------------------------------------------

class TestParseReasonEmbeddedStatus:
    def test_deferred_with_reason_extracted(self, tmp_path):
        content = """\
            # BL-060: Deferred item

            **Status:** deferred — low ROI for current phase
            **Priority:** P4
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "deferred"
        assert parsed["deferred_reason"] == "low ROI for current phase"


# ---------------------------------------------------------------------------
# Scenario: Parse PROMOTED file with target
# ---------------------------------------------------------------------------

class TestParsePromotedFileWithTarget:
    def test_promoted_status_and_promoted_to_extracted(self, tmp_path):
        content = """\
            # BL-082: Tracked workflows

            **Status:** PROMOTED
            **Promoted to:** EP-009 (v4.1)
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "promoted"
        assert parsed["promoted_to"] == "EP-009 (v4.1)"


# ---------------------------------------------------------------------------
# Scenario: Parse PROMOTED file with no promoted_to field
# ---------------------------------------------------------------------------

class TestParsePromotedFileNoTarget:
    def test_promoted_status_no_promoted_to_is_none(self, tmp_path):
        content = """\
            # BL-099: Orphan promoted

            **Status:** PROMOTED
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "promoted"
        assert parsed["promoted_to"] is None


# ---------------------------------------------------------------------------
# Scenario: Status values are lowercased before remap
# ---------------------------------------------------------------------------

class TestStatusValuesLowercased:
    def test_backlog_status_uppercased_is_lowercased(self, tmp_path):
        content = """\
            # BL-084: Case test

            **Status:** BACKLOG
            **Priority:** P3
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "backlog"


# ---------------------------------------------------------------------------
# Scenario: Priority values are lowercased before remap
# ---------------------------------------------------------------------------

class TestPriorityValuesLowercased:
    def test_spike_priority_uppercased_is_lowercased(self, tmp_path):
        content = """\
            # BL-001: Spike

            **Status:** Open
            **Priority:** SPIKE
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["priority"] == "spike"


# ---------------------------------------------------------------------------
# Scenario: depends_on as YAML inline list
# ---------------------------------------------------------------------------

class TestDependsOnFormats:
    def test_depends_on_yaml_inline_list(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: Test
            status: open
            depends_on: [BL-040, BL-041]
            ---
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["depends_on"] == ["BL-040", "BL-041"]

    def test_depends_on_scalar_string_normalized_to_list(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: Test
            status: open
            depends_on: BL-040
            ---
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["depends_on"] == ["BL-040"]

    def test_depends_on_yaml_block_sequence(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: Test
            status: open
            depends_on:
              - BL-040
              - BL-041
            ---
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["depends_on"] == ["BL-040", "BL-041"]


# ---------------------------------------------------------------------------
# Scenario: Empty YAML frontmatter falls back to bold parsing
# ---------------------------------------------------------------------------

class TestEmptyYAMLFrontmatterFallsBack:
    def test_empty_frontmatter_falls_back_to_bold(self, tmp_path):
        content = """\
            ---
            ---

            # BL-042: Widget builder

            **Status:** Open
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["title"] == "Widget builder"
        assert parsed["status"] == "open"


# ---------------------------------------------------------------------------
# Scenario: Malformed YAML frontmatter falls back to bold parsing with warning
# ---------------------------------------------------------------------------

class TestMalformedYAMLFrontmatterFallsBack:
    def test_malformed_yaml_falls_back_to_bold_and_emits_warning(self, tmp_path):
        content = """\
            ---
            id: BL-042
            title: "unclosed quote
            status: [invalid: yaml
            ---

            # BL-042: Widget builder

            **Status:** Open
            """
        p = write_file(tmp_path, content)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parsed = parse_file(str(p))

        assert parsed["title"] == "Widget builder"
        assert parsed["status"] == "open"
        assert any("yaml" in str(w.message).lower() for w in caught)


# ---------------------------------------------------------------------------
# Scenario: Body containing HR separator is not re-parsed as frontmatter
# ---------------------------------------------------------------------------

class TestBodyWithHRSeparator:
    def test_hr_in_body_not_parsed_as_frontmatter(self, tmp_path):
        content = """\
            # BL-082: Tracked workflows

            **Status:** Open

            First section content.

            ---

            ## Feature Request: Second Document

            Second section content.
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert "First section content." in parsed["body"]
        assert "Feature Request: Second Document" in parsed["body"]
        assert "Second section content." in parsed["body"]


# ---------------------------------------------------------------------------
# Scenario: Bold patterns inside code blocks are not parsed as metadata
# ---------------------------------------------------------------------------

class TestBoldPatternsInCodeBlocksNotMetadata:
    def test_bold_status_inside_code_block_not_parsed(self, tmp_path):
        content = """\
            # MS-007: Tracked workflows

            **Status:** Active

            ## Appendix A

            ```
            **Status:** done
            **Priority:** P0
            ```

            Regular body text after code block.
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "active"
        assert "**Status:** done" in parsed["body"]
        assert "Regular body text after code block." in parsed["body"]


# ---------------------------------------------------------------------------
# Scenario: Bold patterns after first blank line are body not metadata
# ---------------------------------------------------------------------------

class TestBoldPatternsAfterBlankLineAreBody:
    def test_bold_status_after_blank_line_treated_as_body(self, tmp_path):
        content = """\
            # MS-007: Tracked workflows

            **Status:** Active
            **Priority:** P2

            **Status:** This is a body line that looks like metadata
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["status"] == "active"
        assert "**Status:** This is a body line" in parsed["body"]


# ---------------------------------------------------------------------------
# Scenario: Unrecognized YAML frontmatter fields are preserved
# ---------------------------------------------------------------------------

class TestUnrecognizedYAMLFieldsPreserved:
    def test_unrecognized_yaml_fields_appear_in_parsed(self, tmp_path):
        content = """\
            ---
            id: STORY-015
            title: Orchestrator state machine
            status: done
            workflow_type: enhancement
            shape: small
            phase: ship
            pr: "#52"
            milestone: MS-007
            ---

            Story body.
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["workflow_type"] == "enhancement"
        assert parsed["shape"] == "small"
        assert parsed["phase"] == "ship"
        assert parsed["pr"] == "#52"


# ---------------------------------------------------------------------------
# Scenario: Unrecognized bold-format fields are preserved
# ---------------------------------------------------------------------------

class TestUnrecognizedBoldFieldsPreserved:
    def test_unrecognized_bold_fields_appear_in_parsed(self, tmp_path):
        content = """\
            # MS-001: Public Launch

            **Status:** Proposed
            **mode_introduced:** agile
            **Replaces:** MS-000-alpha
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["mode_introduced"] == "agile"
        assert parsed["replaces"] == "MS-000-alpha"


# ---------------------------------------------------------------------------
# Scenario: SHA-256 hash is computed over raw bytes
# ---------------------------------------------------------------------------

class TestSourceHashComputed:
    def test_source_hash_equals_sha256_of_raw_bytes(self, tmp_path):
        raw = b"# BL-001: Foo\n\n**Status:** Open\n"
        p = tmp_path / "BL-001-foo.md"
        p.write_bytes(raw)

        parsed = parse_file(str(p))

        expected = hashlib.sha256(raw).hexdigest()
        assert parsed["source_hash"] == expected


# ---------------------------------------------------------------------------
# Scenario: File with no body produces empty string body
# ---------------------------------------------------------------------------

class TestFileWithNoBodyProducesEmptyBody:
    def test_no_body_after_frontmatter_produces_empty_string(self, tmp_path):
        content = """\
            ---
            id: BL-001
            title: Foo
            status: open
            ---
            """
        p = write_file(tmp_path, content)

        parsed = parse_file(str(p))

        assert parsed["body"] == ""


# ---------------------------------------------------------------------------
# Scenario: File with no parseable metadata at all
# ---------------------------------------------------------------------------

class TestFileWithNoMetadata:
    def test_file_with_no_metadata_parses_title_from_heading(self, tmp_path):
        content = """\
            # MS-009: Planning Workflows

            Just a heading and some prose, no metadata fields.
            """
        p = write_file(tmp_path, content)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parsed = parse_file(str(p))

        assert parsed["title"] == "Planning Workflows"
        assert parsed["status"] is None
        assert any("metadata" in str(w.message).lower() for w in caught)
