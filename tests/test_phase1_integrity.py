"""
Phase 1 & 2 success gate tests for the Unified Artifact Integrity System.

Phase 1:
- Bold-format files are ingested by the cache (1A/1B/1C)
- Doctor check_derived_status finds Bold-format parents with stale status (1A)
- Doctor check_format_consistency reports Bold-format files (1E)
- Schema validates all new ID prefixes (1D)
- Expanded scan directories pick up artifacts outside the original 4 dirs (1B)

Phase 2:
- op_create produces YAML frontmatter (2B)
- op_create with parent ref triggers propagation (2D)
- op_write with status change triggers propagation (2C)
- Doctor auto-fix resolves stale parent status (2E)
"""
import importlib.util
import json
import os
import sys
import sqlite3

import pytest
import yaml

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_HOOKS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "hooks")
)

from cache import rebuild, get_conn, db_path
from parse_utils import (
    parse_bold_metadata,
    parse_yaml_frontmatter,
    detect_format,
    parse_artifact,
    BOLD_TO_YAML_FIELD_MAP,
    PREFIX_TO_TYPE,
)
from schema import validate_frontmatter, VALID_TYPES, normalize_status


def _load_sc_artifact():
    spec = importlib.util.spec_from_file_location(
        "sc_artifact_impl",
        os.path.join(_HOOKS_DIR, "sc-artifact-impl.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml_file(path, frontmatter, body=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm_text = yaml.dump(frontmatter, default_flow_style=False)
    with open(path, "w") as f:
        f.write(f"---\n{fm_text}---\n{body}")


def write_bold_file(path, heading, fields, body=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f"# {heading}", ""]
    for key, val in fields.items():
        lines.append(f"**{key}:** {val}")
    if body:
        lines.append("")
        lines.append(body)
    with open(path, "w") as f:
        f.write("\n".join(lines))


def setup_project(tmp_path):
    sc = tmp_path / ".sweetclaude"
    sc.mkdir(parents=True)
    ap = sc / "artifact-privacy.yaml"
    ap.write_text(yaml.dump({"product": {"base_path": ".sweetclaude/product"}}))
    return str(tmp_path)


def get_item(project_dir, item_id):
    conn = get_conn(project_dir)
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_items(project_dir):
    conn = get_conn(project_dir)
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# parse_utils unit tests
# ---------------------------------------------------------------------------

class TestParseUtils:

    def test_detect_yaml_format(self):
        content = "---\nid: ISSUE-001\ntitle: Test\n---\n"
        assert detect_format(content) == "yaml"

    def test_detect_bold_format(self):
        content = "# SP-001: My Sprint\n\n**Status:** active\n**Created:** 2026-01-01\n"
        assert detect_format(content) == "bold"

    def test_detect_unknown_format(self):
        content = "Just some markdown without any format markers.\n"
        assert detect_format(content) == "unknown"

    def test_parse_bold_extracts_id_from_heading(self):
        content = "# SP-001: Sprint One\n\n**Status:** active\n"
        result = parse_bold_metadata(content)
        assert result is not None
        assert result["id"] == "SP-001"
        assert result["title"] == "Sprint One"

    def test_parse_bold_infers_type_from_prefix(self):
        for prefix, expected_type in PREFIX_TO_TYPE.items():
            content = f"# {prefix}-99: Test\n\n**Status:** active\n"
            result = parse_bold_metadata(content)
            assert result is not None
            assert result["type"] == expected_type, f"prefix {prefix} → expected {expected_type}"

    def test_parse_bold_remaps_field_names(self):
        content = (
            "# ISSUE-100: Test Issue\n\n"
            "**Epic ID:** EP-01\n"
            "**Sprint ID:** SP-01\n"
            "**Theme ID:** TH-01\n"
            "**Milestone ID:** MS-01\n"
        )
        result = parse_bold_metadata(content)
        assert result["epic"] == "EP-01"
        assert result["sprint"] == "SP-01"
        assert result["theme"] == "TH-01"
        assert result["milestone"] == "MS-01"

    def test_parse_bold_normalizes_none_sentinels(self):
        content = "# SP-001: Test\n\n**Epic ID:** (none)\n**Status:** active\n"
        result = parse_bold_metadata(content)
        assert result["epic"] is None
        assert result["status"] == "active"

    def test_parse_yaml_returns_dict(self):
        content = "---\nid: ISSUE-001\ntitle: Test\nstatus: active\n---\n"
        result = parse_yaml_frontmatter(content)
        assert result == {"id": "ISSUE-001", "title": "Test", "status": "active"}

    def test_parse_artifact_dispatches_to_bold(self):
        content = "# SP-001: Test\n\n**Status:** active\n"
        result = parse_artifact(content)
        assert result is not None
        assert result["id"] == "SP-001"

    def test_parse_artifact_dispatches_to_yaml(self):
        content = "---\nid: ISSUE-001\ntitle: Test\n---\n"
        result = parse_artifact(content)
        assert result is not None
        assert result["id"] == "ISSUE-001"


# ---------------------------------------------------------------------------
# Bold-format ingestion into cache (Phase 1A + 1B + 1C success gate)
# ---------------------------------------------------------------------------

class TestBoldFormatCacheIngestion:

    def test_bold_sprint_indexed_in_cache(self, tmp_path):
        project_dir = setup_project(tmp_path)
        sprint_dir = os.path.join(project_dir, ".sweetclaude", "product", "sprints")
        write_bold_file(
            os.path.join(sprint_dir, "SP-001-sprint-one.md"),
            "SP-001: Sprint One",
            {"Status": "active", "Created": "2026-01-01"},
        )
        rebuild(project_dir)
        item = get_item(project_dir, "SP-001")
        assert item is not None, "Bold-format SP-001 should be in cache"
        assert item["title"] == "Sprint One"
        assert item["type"] == "sprint"

    def test_bold_theme_indexed_in_cache(self, tmp_path):
        project_dir = setup_project(tmp_path)
        theme_dir = os.path.join(project_dir, ".sweetclaude", "product", "themes")
        write_bold_file(
            os.path.join(theme_dir, "TH-001-theme-one.md"),
            "TH-001: Theme One",
            {"Status": "active", "Created": "2026-01-01"},
        )
        rebuild(project_dir)
        item = get_item(project_dir, "TH-001")
        assert item is not None, "Bold-format TH-001 should be in cache"
        assert item["type"] == "theme"

    def test_bold_issue_with_epic_ref_indexed(self, tmp_path):
        project_dir = setup_project(tmp_path)
        backlog_dir = os.path.join(project_dir, ".sweetclaude", "product", "backlog")
        write_bold_file(
            os.path.join(backlog_dir, "ISSUE-100-test.md"),
            "ISSUE-100: Test Issue",
            {
                "Status": "active",
                "Created": "2026-01-01",
                "Epic ID": "EP-01",
                "Sprint ID": "SP-01",
            },
        )
        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-100")
        assert item is not None
        assert item["epic"] == "EP-01"
        assert item["sprint"] == "SP-01"

    def test_bold_epic_in_epics_dir_indexed(self, tmp_path):
        project_dir = setup_project(tmp_path)
        epics_dir = os.path.join(project_dir, ".sweetclaude", "product", "epics")
        write_bold_file(
            os.path.join(epics_dir, "EP-01-alpha.md"),
            "EP-01: Alpha Epic",
            {
                "Status": "done",
                "Created": "2026-01-01",
                "Milestone ID": "MS-01",
            },
        )
        rebuild(project_dir)
        item = get_item(project_dir, "EP-01")
        assert item is not None
        assert item["type"] == "epic"
        assert item["milestone"] == "MS-01"

    def test_new_columns_populated_from_bold(self, tmp_path):
        project_dir = setup_project(tmp_path)
        backlog_dir = os.path.join(project_dir, ".sweetclaude", "product", "backlog")
        write_bold_file(
            os.path.join(backlog_dir, "ISSUE-200-full.md"),
            "ISSUE-200: Full Refs",
            {
                "Status": "active",
                "Created": "2026-01-01",
                "Epic ID": "EP-01",
                "Sprint ID": "SP-01",
                "Theme ID": "TH-01",
                "Release ID": "REL-01",
            },
        )
        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-200")
        assert item is not None
        assert item["sprint"] == "SP-01"
        assert item["theme"] == "TH-01"
        assert item["release"] == "REL-01"

    def test_mixed_format_project_all_items_indexed(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = os.path.join(project_dir, ".sweetclaude", "product")

        write_yaml_file(
            os.path.join(base, "roadmap", "epics", "EP-01-yaml.md"),
            {"id": "EP-01", "title": "YAML Epic", "type": "epic", "status": "active",
             "created": "2026-01-01", "milestone": "MS-01"},
        )
        write_bold_file(
            os.path.join(base, "epics", "EP-02-bold.md"),
            "EP-02: Bold Epic",
            {"Status": "done", "Created": "2026-01-01", "Milestone ID": "MS-01"},
        )
        write_yaml_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-100-yaml.md"),
            {"id": "ISSUE-100", "title": "YAML Issue", "type": "enhancement",
             "status": "active", "created": "2026-01-01", "epic": "EP-01"},
        )
        write_bold_file(
            os.path.join(base, "backlog", "ISSUE-200-bold.md"),
            "ISSUE-200: Bold Issue",
            {"Status": "active", "Created": "2026-01-01", "Epic ID": "EP-02"},
        )

        rebuild(project_dir)
        items = get_all_items(project_dir)
        ids = {i["id"] for i in items}
        assert "EP-01" in ids, "YAML epic should be indexed"
        assert "EP-02" in ids, "Bold epic should be indexed"
        assert "ISSUE-100" in ids, "YAML issue should be indexed"
        assert "ISSUE-200" in ids, "Bold issue should be indexed"


# ---------------------------------------------------------------------------
# Expanded scan directories (Phase 1B)
# ---------------------------------------------------------------------------

class TestExpandedScanDirs:

    def test_sprints_dir_scanned(self, tmp_path):
        project_dir = setup_project(tmp_path)
        sprint_dir = os.path.join(project_dir, ".sweetclaude", "product", "sprints")
        write_yaml_file(
            os.path.join(sprint_dir, "SP-001-test.md"),
            {"id": "SP-001", "title": "Sprint 1", "type": "sprint", "status": "active",
             "created": "2026-01-01"},
        )
        rebuild(project_dir)
        assert get_item(project_dir, "SP-001") is not None

    def test_themes_dir_scanned(self, tmp_path):
        project_dir = setup_project(tmp_path)
        themes_dir = os.path.join(project_dir, ".sweetclaude", "product", "themes")
        write_yaml_file(
            os.path.join(themes_dir, "TH-001-test.md"),
            {"id": "TH-001", "title": "Theme 1", "type": "theme", "status": "active",
             "created": "2026-01-01"},
        )
        rebuild(project_dir)
        assert get_item(project_dir, "TH-001") is not None

    def test_cycles_dir_scanned(self, tmp_path):
        project_dir = setup_project(tmp_path)
        cycles_dir = os.path.join(project_dir, ".sweetclaude", "product", "cycles")
        write_yaml_file(
            os.path.join(cycles_dir, "CYC-001-test.md"),
            {"id": "CYC-001", "title": "Cycle 1", "type": "cycle", "status": "active",
             "created": "2026-01-01"},
        )
        rebuild(project_dir)
        assert get_item(project_dir, "CYC-001") is not None

    def test_pitches_dir_scanned(self, tmp_path):
        project_dir = setup_project(tmp_path)
        pitches_dir = os.path.join(project_dir, ".sweetclaude", "product", "pitches")
        write_yaml_file(
            os.path.join(pitches_dir, "PITCH-001-test.md"),
            {"id": "PITCH-001", "title": "Pitch 1", "type": "pitch", "status": "new",
             "created": "2026-01-01"},
        )
        rebuild(project_dir)
        assert get_item(project_dir, "PITCH-001") is not None

    def test_releases_dir_scanned(self, tmp_path):
        project_dir = setup_project(tmp_path)
        releases_dir = os.path.join(
            project_dir, ".sweetclaude", "product", "roadmap", "releases"
        )
        write_yaml_file(
            os.path.join(releases_dir, "REL-001-test.md"),
            {"id": "REL-001", "title": "Release 1", "type": "release", "status": "new",
             "created": "2026-01-01"},
        )
        rebuild(project_dir)
        assert get_item(project_dir, "REL-001") is not None

    def test_deduplication_across_dirs(self, tmp_path):
        """Same file reachable via roadmap/ and roadmap/epics/ is not double-counted."""
        project_dir = setup_project(tmp_path)
        epics_dir = os.path.join(
            project_dir, ".sweetclaude", "product", "roadmap", "epics"
        )
        write_yaml_file(
            os.path.join(epics_dir, "EP-01-test.md"),
            {"id": "EP-01", "title": "Epic 1", "type": "epic", "status": "active",
             "created": "2026-01-01", "milestone": "MS-01"},
        )
        rebuild(project_dir)
        conn = get_conn(project_dir)
        count = conn.execute(
            "SELECT COUNT(*) FROM items WHERE id = 'EP-01'"
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ---------------------------------------------------------------------------
# Schema validation for new ID prefixes (Phase 1D)
# ---------------------------------------------------------------------------

class TestSchemaNewPrefixes:

    @pytest.mark.parametrize("artifact_id", [
        "SP-01", "TH-01", "RM-01", "REL-01", "PITCH-01", "CYC-01", "I-01",
    ])
    def test_new_id_prefixes_valid(self, artifact_id):
        fm = {
            "id": artifact_id,
            "title": "Test",
            "type": "sprint",
            "status": "active",
            "created": "2026-01-01",
        }
        violations = validate_frontmatter(fm)
        id_violations = [v for v in violations if "invalid id" in v.lower()]
        assert len(id_violations) == 0, f"{artifact_id} should be a valid ID"

    @pytest.mark.parametrize("artifact_type", [
        "sprint", "theme", "roadmap_item", "release", "pitch", "cycle",
    ])
    def test_new_types_valid(self, artifact_type):
        assert artifact_type in VALID_TYPES


# ---------------------------------------------------------------------------
# Status alias normalization (Phase 1D)
# ---------------------------------------------------------------------------

class TestStatusAliases:

    @pytest.mark.parametrize("alias, canonical", [
        ("complete", "done"),
        ("completed", "done"),
        ("closed", "done"),
        ("cancelled", "declined"),
        ("planned", "new"),
        ("pending", "new"),
        ("backlog", "new"),
        ("in_progress", "active"),
        ("in-progress", "active"),
        ("achieved", "done"),
        ("missed", "declined"),
        ("paused", "on-hold"),
    ])
    def test_alias_resolves_to_canonical(self, alias, canonical):
        assert normalize_status(alias) == canonical

    def test_canonical_status_unchanged(self):
        for status in ("new", "active", "done", "declined", "on-hold", "blocked"):
            assert normalize_status(status) == status


# ---------------------------------------------------------------------------
# Doctor: check_format_consistency (Phase 1E)
# ---------------------------------------------------------------------------

class TestDoctorFormatConsistency:

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        fake = tmp_path / "fakehome"
        fake.mkdir()
        monkeypatch.setenv("HOME", str(fake))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake)
        claude_dir = fake / ".claude"
        claude_dir.mkdir()
        return fake

    def _build_project(self, tmp_path):
        from test_doctor import build_fixture, build_project_state
        return build_fixture, build_project_state

    def test_bold_file_flagged(self, tmp_path, fake_home):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_doctor import build_fixture, build_project_state
        from doctor import check_format_consistency

        project_dir = build_fixture(tmp_path)
        sprints_dir = project_dir / ".sweetclaude" / "product" / "sprints"
        sprints_dir.mkdir(parents=True, exist_ok=True)
        bold_file = sprints_dir / "SP-001-test.md"
        bold_file.write_text(
            "# SP-001: Test Sprint\n\n**Status:** active\n**Created:** 2026-01-01\n"
        )

        state = build_project_state(project_dir)
        findings = check_format_consistency(state)
        assert len(findings) >= 1
        bold_findings = [f for f in findings if "SP-001" in f.id]
        assert len(bold_findings) == 1
        assert bold_findings[0].severity == "warning"
        assert bold_findings[0].fix_type == "auto"
        assert bold_findings[0].fix_recipe["action"] == "convert_to_yaml"

    def test_yaml_file_not_flagged(self, tmp_path, fake_home):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_doctor import build_fixture, build_project_state
        from doctor import check_format_consistency

        project_dir = build_fixture(tmp_path)
        epics_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "epics"
        epics_dir.mkdir(parents=True, exist_ok=True)
        yaml_file = epics_dir / "EP-01-test.md"
        yaml_file.write_text(
            "---\nid: EP-01\ntitle: Test\ntype: epic\nstatus: active\n"
            "created: 2026-01-01\nmilestone: MS-01\n---\n"
        )

        state = build_project_state(project_dir)
        findings = check_format_consistency(state)
        format_findings = [f for f in findings if "EP-01" in f.id]
        assert len(format_findings) == 0


# ---------------------------------------------------------------------------
# Doctor: check_derived_status with Bold-format parent (Phase 1A success gate)
# ---------------------------------------------------------------------------

class TestDerivedStatusWithBoldParent:

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        fake = tmp_path / "fakehome"
        fake.mkdir()
        monkeypatch.setenv("HOME", str(fake))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake)
        claude_dir = fake / ".claude"
        claude_dir.mkdir()
        return fake

    def test_bold_epic_stale_status_detected(self, tmp_path, fake_home):
        """Bold-format epic marked done with active children triggers derived_status finding."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_doctor import build_fixture, build_project_state
        from doctor import check_derived_status

        project_dir = build_fixture(tmp_path, overrides={
            "roadmap_files": [
                {
                    "name": "issues/ISSUE-100-test.md",
                    "frontmatter": {
                        "id": "ISSUE-100", "title": "Active Issue", "type": "enhancement",
                        "status": "active", "created": "2026-01-01", "epic": "EP-01",
                    },
                },
                {
                    "name": "issues/ISSUE-101-test.md",
                    "frontmatter": {
                        "id": "ISSUE-101", "title": "Done Issue", "type": "enhancement",
                        "status": "done", "created": "2026-01-01", "epic": "EP-01",
                    },
                },
            ],
        })

        epics_dir = project_dir / ".sweetclaude" / "product" / "epics"
        epics_dir.mkdir(parents=True, exist_ok=True)
        bold_epic = epics_dir / "EP-01-alpha.md"
        bold_epic.write_text(
            "# EP-01: Alpha Epic\n\n"
            "**Status:** done\n"
            "**Created:** 2026-01-01\n"
            "**Milestone ID:** MS-01\n"
        )

        state = build_project_state(project_dir)
        findings = check_derived_status(state)
        ep_findings = [f for f in findings if "EP-01" in f.id]
        assert len(ep_findings) >= 1, (
            "Doctor should detect that Bold-format EP-01 (done) has active children"
        )


# ---------------------------------------------------------------------------
# Phase 2: op_create produces YAML frontmatter (2B)
# ---------------------------------------------------------------------------

class TestCreateProducesYAML:

    def _setup_project(self, tmp_path):
        project_dir = tmp_path / "proj"
        sc = project_dir / ".sweetclaude"
        (sc / "state").mkdir(parents=True)
        (sc / "artifact-privacy.yaml").write_text(
            yaml.dump({"product": {"base_path": ".sweetclaude/product"}})
        )
        product_base = project_dir / ".sweetclaude" / "product"
        state_base = project_dir / ".sweetclaude" / "state"
        for d in ("issues", "epics", "sprints", "themes", "milestones",
                   "roadmap", "roadmap/releases", "pitches", "cycles"):
            (product_base / d).mkdir(parents=True, exist_ok=True)
        return project_dir, product_base, state_base

    @pytest.mark.parametrize("entity_type", [
        "issue", "epic", "sprint", "theme", "roadmap_item",
        "milestone", "release", "pitch", "cycle",
    ])
    def test_create_produces_yaml(self, tmp_path, entity_type):
        sa = _load_sc_artifact()
        project_dir, product_base, state_base = self._setup_project(tmp_path)
        sa.op_create(product_base, state_base, entity_type,
                     json.dumps({"title": f"Test {entity_type}"}),
                     project_dir=project_dir)
        type_dir = product_base / sa.TYPE_TO_DIR[entity_type]
        files = list(type_dir.glob("*.md"))
        assert len(files) == 1, f"Expected 1 file for {entity_type}, got {len(files)}"
        content = files[0].read_text()
        assert detect_format(content) == "yaml", f"{entity_type} template should be YAML"
        fm = parse_artifact(content)
        assert fm is not None
        assert "id" in fm
        assert "status" in fm

    def test_created_issue_parseable_by_cache(self, tmp_path):
        sa = _load_sc_artifact()
        project_dir, product_base, state_base = self._setup_project(tmp_path)
        sa.op_create(product_base, state_base, "issue",
                     json.dumps({"title": "Cache test", "epic_id": "EP-001"}),
                     project_dir=project_dir)
        rebuild(str(project_dir))
        items = get_all_items(str(project_dir))
        issue_items = [i for i in items if i["id"].startswith("I-")]
        assert len(issue_items) == 1
        assert issue_items[0]["epic"] == "EP-001"


# ---------------------------------------------------------------------------
# Phase 2: Create issue in done epic → epic reopens (2D)
# ---------------------------------------------------------------------------

class TestCreateTriggersPropagation:

    def _setup_project_with_done_epic(self, tmp_path):
        project_dir = tmp_path / "proj"
        sc = project_dir / ".sweetclaude"
        (sc / "state").mkdir(parents=True)
        (sc / "artifact-privacy.yaml").write_text(
            yaml.dump({"product": {"base_path": ".sweetclaude/product"}})
        )
        product_base = project_dir / ".sweetclaude" / "product"
        state_base = project_dir / ".sweetclaude" / "state"
        for d in ("issues", "roadmap/epics", "roadmap/milestones"):
            (product_base / d).mkdir(parents=True, exist_ok=True)

        write_yaml_file(
            os.path.join(str(product_base), "roadmap", "epics", "EP-001-test.md"),
            {"id": "EP-001", "title": "Test Epic", "type": "epic",
             "status": "done", "source": "auto",
             "created": "2026-01-01", "milestone": "MS-01"},
        )
        write_yaml_file(
            os.path.join(str(product_base), "issues", "I-001-existing.md"),
            {"id": "I-001", "title": "Done Issue", "type": "enhancement",
             "status": "done", "created": "2026-01-01", "epic": "EP-001"},
        )
        rebuild(str(project_dir))
        return project_dir, product_base, state_base

    def test_create_issue_in_done_epic_reopens_epic(self, tmp_path):
        sa = _load_sc_artifact()
        project_dir, product_base, state_base = self._setup_project_with_done_epic(tmp_path)

        epic_file = product_base / "roadmap" / "epics" / "EP-001-test.md"
        fm_before = parse_artifact(epic_file.read_text())
        assert fm_before["status"] == "done"

        sa.op_create(product_base, state_base, "issue",
                     json.dumps({"title": "New active issue", "epic_id": "EP-001"}),
                     project_dir=project_dir)

        rebuild(str(project_dir))
        conn = get_conn(str(project_dir))
        ep_row = conn.execute("SELECT status FROM items WHERE id='EP-001'").fetchone()
        conn.close()

        assert ep_row is not None
        assert ep_row["status"] != "done", (
            f"EP-001 should have reopened after adding a new issue, but status is {ep_row['status']}"
        )


# ---------------------------------------------------------------------------
# Phase 2: Status write propagation — close last issue → epic auto-closes (2C)
# ---------------------------------------------------------------------------

class TestWritePropagation:

    def _setup_project_with_active_epic(self, tmp_path):
        project_dir = tmp_path / "proj"
        sc = project_dir / ".sweetclaude"
        (sc / "state").mkdir(parents=True)
        (sc / "artifact-privacy.yaml").write_text(
            yaml.dump({"product": {"base_path": ".sweetclaude/product"}})
        )
        product_base = project_dir / ".sweetclaude" / "product"
        state_base = project_dir / ".sweetclaude" / "state"
        for d in ("issues", "roadmap/epics", "roadmap/milestones"):
            (product_base / d).mkdir(parents=True, exist_ok=True)

        write_yaml_file(
            os.path.join(str(product_base), "roadmap", "epics", "EP-001-test.md"),
            {"id": "EP-001", "title": "Test Epic", "type": "epic",
             "status": "active", "source": "auto",
             "created": "2026-01-01", "milestone": "MS-01"},
        )
        write_yaml_file(
            os.path.join(str(product_base), "issues", "I-001-done.md"),
            {"id": "I-001", "title": "Done Issue", "type": "enhancement",
             "status": "done", "created": "2026-01-01", "epic": "EP-001"},
        )
        write_yaml_file(
            os.path.join(str(product_base), "issues", "I-002-active.md"),
            {"id": "I-002", "title": "Last Active Issue", "type": "enhancement",
             "status": "active", "created": "2026-01-01", "epic": "EP-001"},
        )
        rebuild(str(project_dir))
        return project_dir, product_base, state_base

    def test_closing_last_issue_auto_closes_epic(self, tmp_path):
        sa = _load_sc_artifact()
        project_dir, product_base, state_base = self._setup_project_with_active_epic(tmp_path)

        sa.op_write(product_base, state_base, "I-002",
                    json.dumps({"status": "done"}),
                    project_dir=project_dir)

        rebuild(str(project_dir))
        conn = get_conn(str(project_dir))
        ep_row = conn.execute("SELECT status FROM items WHERE id='EP-001'").fetchone()
        conn.close()

        assert ep_row is not None
        assert ep_row["status"] == "done", (
            f"EP-001 should auto-close when all children are done, but status is {ep_row['status']}"
        )


# ---------------------------------------------------------------------------
# Phase 2: Doctor auto-fix resolves stale parent (2E)
# ---------------------------------------------------------------------------

class TestDoctorAutoFix:

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        fake = tmp_path / "fakehome"
        fake.mkdir()
        monkeypatch.setenv("HOME", str(fake))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake)
        claude_dir = fake / ".claude"
        claude_dir.mkdir()
        return fake

    def test_sync_parent_status_fix_resolves_finding(self, tmp_path, fake_home):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_doctor import build_fixture, build_project_state
        from doctor import check_derived_status, execute_recipe, RecipeResult

        project_dir = build_fixture(tmp_path, overrides={
            "roadmap_files": [
                {
                    "name": "epics/EP-01-test.md",
                    "frontmatter": {
                        "id": "EP-01", "title": "Stale Epic", "type": "epic",
                        "status": "done", "source": "auto",
                        "created": "2026-01-01", "milestone": "MS-01",
                    },
                },
                {
                    "name": "issues/ISSUE-100-test.md",
                    "frontmatter": {
                        "id": "ISSUE-100", "title": "Active Issue", "type": "enhancement",
                        "status": "active", "created": "2026-01-01", "epic": "EP-01",
                    },
                },
                {
                    "name": "issues/ISSUE-101-test.md",
                    "frontmatter": {
                        "id": "ISSUE-101", "title": "Done Issue", "type": "enhancement",
                        "status": "done", "created": "2026-01-01", "epic": "EP-01",
                    },
                },
            ],
        })

        state = build_project_state(project_dir)
        findings = check_derived_status(state)
        ep_findings = [f for f in findings if "EP-01" in f.id]
        assert len(ep_findings) >= 1, "Should detect stale EP-01"

        finding = ep_findings[0]
        assert finding.fix_recipe["action"] == "sync_parent_status"

        archive = project_dir / ".sweetclaude" / "doctor-archive"
        archive.mkdir(parents=True, exist_ok=True)
        result = execute_recipe(project_dir, finding.fix_recipe, archive)
        assert result.success, f"Auto-fix should succeed, error: {result.error}"

        state2 = build_project_state(project_dir)
        findings2 = check_derived_status(state2)
        ep_findings2 = [f for f in findings2 if "EP-01" in f.id]
        assert len(ep_findings2) == 0, (
            f"After auto-fix, EP-01 should have no stale status finding, got: {ep_findings2}"
        )
