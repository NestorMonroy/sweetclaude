"""
Tests for cache taxonomy update (ISSUE-92).

Translates: tests/features/cache-taxonomy-update.feature

The roadmap cache must be updated to scan the post-migration file structure
(.sweetclaude/product/), normalize messy frontmatter values, and return correct
query results for all consumers.
"""
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

from cache import (
    rebuild,
    query_backlog,
    query_releases_compact,
    query_summary,
    query_next_id,
    query_epic_stories,
    get_conn,
    db_path,
)


# ---------------------------------------------------------------------------
# New query functions expected to exist post-implementation
# ---------------------------------------------------------------------------
try:
    from cache import query_milestones_compact
except ImportError:
    query_milestones_compact = None

try:
    from cache import query_epic_issues
except ImportError:
    query_epic_issues = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_frontmatter_file(path, frontmatter_dict, body=""):
    """Create a markdown file with YAML frontmatter at the given path."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm_text = yaml.dump(frontmatter_dict, default_flow_style=False)
    content = f"---\n{fm_text}---\n{body}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def setup_project(tmp_path):
    """Create the minimal directory structure and artifact-privacy.yaml."""
    sc_dir = tmp_path / ".sweetclaude"
    sc_dir.mkdir(parents=True, exist_ok=True)
    ap = sc_dir / "artifact-privacy.yaml"
    ap.write_text(yaml.dump({"product": {"base_path": ".sweetclaude/product"}}))
    return str(tmp_path)


def get_item(project_dir, item_id):
    """Fetch a single item dict from the cache by id."""
    conn = get_conn(project_dir)
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_items(project_dir):
    """Return all items from the cache as a list of dicts."""
    conn = get_conn(project_dir)
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_schema_columns(project_dir, table="items"):
    """Return column names for the given table."""
    conn = sqlite3.connect(db_path(project_dir))
    cursor = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()
    return cols


def get_schema_indexes(project_dir):
    """Return index names for items table."""
    conn = sqlite3.connect(db_path(project_dir))
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_deps_table_columns(project_dir):
    """Return column names for the dependencies table (item_id, depends_on)."""
    conn = sqlite3.connect(db_path(project_dir))
    # Try generic name first, then fall back to known names
    for table in ("dependencies", "item_dependencies", "epic_dependencies"):
        try:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]
            if cols:
                conn.close()
                return cols, table
        except Exception:
            pass
    conn.close()
    return [], None


def get_all_deps(project_dir):
    """Return all rows from the dependencies table."""
    conn = sqlite3.connect(db_path(project_dir))
    for table in ("dependencies", "item_dependencies", "epic_dependencies"):
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            conn.close()
            return [dict(zip([d[0] for d in conn.execute(f"PRAGMA table_info({table})").description or []], r)) for r in rows], table
        except Exception:
            pass
    # Try again more carefully
    conn2 = sqlite3.connect(db_path(project_dir))
    conn2.row_factory = sqlite3.Row
    for table in ("dependencies", "item_dependencies", "epic_dependencies"):
        try:
            rows = conn2.execute(f"SELECT * FROM {table}").fetchall()
            result = [dict(r) for r in rows]
            conn2.close()
            return result, table
        except Exception:
            pass
    conn2.close()
    return [], None


def get_completion_criteria(project_dir, epic_id):
    """Return completion criteria rows for an epic."""
    conn = get_conn(project_dir)
    rows = conn.execute(
        "SELECT * FROM completion_criteria WHERE epic_id = ? ORDER BY seq",
        (epic_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Feature: Scan paths
# ---------------------------------------------------------------------------

class TestRebuildScansNewTaxonomyPaths:
    """Scenario: Rebuild scans new taxonomy paths"""

    def test_cache_contains_five_items(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-foo.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Foo", "status": "new"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-002-bar.md"),
            {"id": "ISSUE-002", "type": "bug-fix", "title": "Bar", "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-003-baz.md"),
            {"id": "ISSUE-003", "type": "spike", "title": "Baz", "status": "done"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-launch.md"),
            {"id": "MS-001", "type": "milestone", "title": "Launch", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-workflow.md"),
            {"id": "EP-001", "type": "epic", "title": "Workflow", "status": "active", "milestone": "MS-001"},
        )

        rebuild(project_dir)
        items = get_all_items(project_dir)

        assert len(items) == 5

    def test_all_item_types_present(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-foo.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Foo", "status": "new"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-002-bar.md"),
            {"id": "ISSUE-002", "type": "bug-fix", "title": "Bar", "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-003-baz.md"),
            {"id": "ISSUE-003", "type": "spike", "title": "Baz", "status": "done"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-launch.md"),
            {"id": "MS-001", "type": "milestone", "title": "Launch", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-workflow.md"),
            {"id": "EP-001", "type": "epic", "title": "Workflow", "status": "active", "milestone": "MS-001"},
        )

        rebuild(project_dir)

        item_001 = get_item(project_dir, "ISSUE-001")
        item_002 = get_item(project_dir, "ISSUE-002")
        item_003 = get_item(project_dir, "ISSUE-003")
        item_ms = get_item(project_dir, "MS-001")
        item_ep = get_item(project_dir, "EP-001")

        assert item_001 is not None and item_001["type"] == "enhancement"
        assert item_002 is not None and item_002["type"] == "bug-fix"
        assert item_003 is not None and item_003["type"] == "spike"
        assert item_ms is not None and item_ms["type"] == "milestone"
        assert item_ep is not None and item_ep["type"] == "epic"


class TestRebuildIgnoresOldDocsPaths:
    """Scenario: Rebuild ignores old docs/product/ paths"""

    def test_old_docs_product_path_yields_zero_items(self, tmp_path):
        project_dir = setup_project(tmp_path)
        old_path = str(tmp_path / "docs" / "product" / "backlog" / "stories")
        write_frontmatter_file(
            os.path.join(old_path, "STORY-001-old.md"),
            {"id": "STORY-001", "type": "story", "title": "Old", "status": "new"},
        )

        rebuild(project_dir)
        items = get_all_items(project_dir)

        assert len(items) == 0


class TestIndexFilesSkipped:
    """Scenario: Index files without frontmatter are skipped"""

    def test_index_files_without_frontmatter_are_skipped(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        # One real item in the backlog — this should be indexed
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-real.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Real", "status": "new"},
        )

        backlog_idx = os.path.join(base, "backlog", "BACKLOG-INDEX.md")
        with open(backlog_idx, "w") as f:
            f.write("# Backlog")

        issues_idx = os.path.join(base, "issues", "ISSUES-INDEX.md")
        os.makedirs(os.path.dirname(issues_idx), exist_ok=True)
        with open(issues_idx, "w") as f:
            f.write("# Issues")

        rebuild(project_dir)
        items = get_all_items(project_dir)

        # The real item must be indexed; index files must be skipped
        assert len(items) == 1
        assert items[0]["id"] == "ISSUE-001"


class TestArchivedFilesIncluded:
    """Scenario: Archived files are included in cache"""

    def test_archived_file_is_indexed(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "archived", "I-021-spike.md"),
            {"id": "I-021", "type": "spike", "title": "Old spike", "status": "done"},
        )

        rebuild(project_dir)
        items = get_all_items(project_dir)

        assert len(items) == 1
        assert items[0]["id"] == "I-021"
        assert items[0]["type"] == "spike"


# ---------------------------------------------------------------------------
# Feature: Status normalization
# ---------------------------------------------------------------------------

class TestStatusWithEmbeddedDateNormalized:
    """Scenario: Status with embedded date is normalized to bare keyword"""

    def test_done_with_date_in_parens_normalizes_to_done(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-023-worktree.md"),
            {"id": "ISSUE-023", "type": "enhancement", "title": "Worktree",
             "status": "done (2026-05-02)"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-023")

        assert item is not None
        assert item["status"] == "done"


class TestStatusWithEmDashNormalized:
    """Scenario: Status with em-dash date is normalized"""

    def test_done_with_emdash_date_normalizes_to_done(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-009-routing.md"),
            {"id": "ISSUE-009", "type": "enhancement", "title": "Routing",
             "status": "done — 2026-05-02"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-009")

        assert item is not None
        assert item["status"] == "done"


class TestStatusWithParentheticalNoteNormalized:
    """Scenario: Status with parenthetical note is normalized"""

    def test_done_with_parenthetical_note_normalizes_to_done(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-032-demo.md"),
            {"id": "ISSUE-032", "type": "enhancement", "title": "Demo",
             "status": "done (bl-032 remotion demo video carried to ms-005)"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-032")

        assert item is not None
        assert item["status"] == "done"


class TestNormalizedDoneExcludedFromBacklog:
    """Scenario: Normalized done items excluded from backlog query"""

    def test_done_with_date_not_in_backlog(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-010-open.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "Open item", "status": "new"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-023-done.md"),
            {"id": "ISSUE-023", "type": "enhancement", "title": "Done item",
             "status": "done (2026-05-02)"},
        )

        rebuild(project_dir)
        backlog = query_backlog(project_dir)
        ids = [item["id"] for item in backlog]

        assert len(backlog) == 1
        assert "ISSUE-010" in ids
        assert "ISSUE-023" not in ids


# ---------------------------------------------------------------------------
# Feature: Milestone field normalization
# ---------------------------------------------------------------------------

class TestMilestoneWithDisplayNameNormalized:
    """Scenario: Milestone with display name is normalized to clean ID"""

    def test_milestone_with_display_name_strips_to_id(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-027-decay.md"),
            {"id": "ISSUE-027", "type": "enhancement", "title": "Decay",
             "status": "new", "milestone": "MS-004 (Stream B)"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-027")

        assert item is not None
        assert item["milestone"] == "MS-004"


class TestMilestoneUnassignedNormalizedToNull:
    """Scenario: Milestone "(unassigned)" is normalized to null"""

    def test_unassigned_milestone_is_null(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-025-cli.md"),
            {"id": "ISSUE-025", "type": "enhancement", "title": "CLI",
             "status": "new", "milestone": "(unassigned)"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-025")

        assert item is not None
        assert item["milestone"] is None


class TestMilestoneTBDNormalizedToNull:
    """Scenario: Milestone "TBD" is normalized to null"""

    def test_tbd_milestone_is_null(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-036-test.md"),
            {"id": "ISSUE-036", "type": "enhancement", "title": "Test",
             "status": "new", "milestone": "TBD"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-036")

        assert item is not None
        assert item["milestone"] is None


class TestCleanMilestoneIdPreserved:
    """Scenario: Clean milestone ID is preserved"""

    def test_clean_milestone_id_unchanged(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-050-clean.md"),
            {"id": "ISSUE-050", "type": "enhancement", "title": "Clean",
             "status": "new", "milestone": "MS-007"},
        )

        rebuild(project_dir)
        item = get_item(project_dir, "ISSUE-050")

        assert item is not None
        assert item["milestone"] == "MS-007"


# ---------------------------------------------------------------------------
# Feature: Type filter — denylist approach
# ---------------------------------------------------------------------------

class TestAllWorkflowTypesInBacklog:
    """Scenario: All workflow types appear in backlog query"""

    def test_enhancement_spike_bugfix_techdebt_netnewfeature_all_in_backlog(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        for item_id, item_type in [
            ("ISSUE-001", "enhancement"),
            ("ISSUE-002", "spike"),
            ("ISSUE-003", "bug-fix"),
            ("ISSUE-004", "tech-debt"),
            ("ISSUE-005", "net-new-feature"),
        ]:
            write_frontmatter_file(
                os.path.join(base, "backlog", f"{item_id}-x.md"),
                {"id": item_id, "type": item_type, "title": item_id, "status": "new"},
            )

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )

        rebuild(project_dir)
        backlog = query_backlog(project_dir)
        ids = [item["id"] for item in backlog]

        assert len(backlog) == 5
        assert "MS-001" not in ids
        assert "EP-001" not in ids


# ---------------------------------------------------------------------------
# Feature: Milestone hierarchy (replaces releases)
# ---------------------------------------------------------------------------

class TestMilestonesCompactHierarchy:
    """Scenario: Milestones-compact returns milestone-epic-issue hierarchy"""

    def test_milestones_compact_returns_milestone_with_epics_and_issues(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-launch.md"),
            {"id": "MS-001", "type": "milestone", "title": "Launch", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-engine.md"),
            {"id": "EP-001", "type": "epic", "title": "Engine", "status": "active",
             "milestone": "MS-001",
             "completion_criteria": ["Design done", "Tests pass"],
             "completion_criteria_done": [0]},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-design.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "Design",
             "status": "done", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-011-impl.md"),
            {"id": "ISSUE-011", "type": "enhancement", "title": "Implement",
             "status": "new", "epic": "EP-001"},
        )

        rebuild(project_dir)

        assert query_milestones_compact is not None, (
            "query_milestones_compact must be importable from scripts.cache"
        )
        result = query_milestones_compact(project_dir)

        assert len(result) == 1
        ms = result[0]
        assert ms["id"] == "MS-001"
        assert ms["status"] == "active"
        assert len(ms["epics"]) == 1

        ep = ms["epics"][0]
        assert ep["id"] == "EP-001"
        assert ep["criteria_done"] == 1
        assert ep["criteria_total"] == 2
        assert len(ep["stories"]) == 2

    def test_query_releases_compact_returns_same_as_milestones_compact(self, tmp_path):
        """query_releases_compact must work against the new milestone structure."""
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-launch.md"),
            {"id": "MS-001", "type": "milestone", "title": "Launch", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-engine.md"),
            {"id": "EP-001", "type": "epic", "title": "Engine", "status": "active",
             "milestone": "MS-001",
             "completion_criteria": ["Design done", "Tests pass"],
             "completion_criteria_done": [0]},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-design.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "Design",
             "status": "done", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-011-impl.md"),
            {"id": "ISSUE-011", "type": "enhancement", "title": "Implement",
             "status": "new", "epic": "EP-001"},
        )

        rebuild(project_dir)
        result = query_releases_compact(project_dir)

        assert len(result) == 1
        ms = result[0]
        assert ms["id"] == "MS-001"
        assert ms["status"] == "active"
        assert len(ms["epics"]) == 1


class TestReleasesCompactAliasForMilestonesCompact:
    """Scenario: Releases-compact is an alias for milestones-compact"""

    def test_releases_compact_and_milestones_compact_return_identical_results(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )

        rebuild(project_dir)

        assert query_milestones_compact is not None, (
            "query_milestones_compact must be importable from scripts.cache"
        )

        r1 = query_releases_compact(project_dir)
        r2 = query_milestones_compact(project_dir)

        assert r1 == r2


# ---------------------------------------------------------------------------
# Feature: Summary query
# ---------------------------------------------------------------------------

class TestSummaryReturnsMilestoneCounts:
    """Scenario: Summary returns milestone counts instead of release counts"""

    def test_summary_has_milestones_key_not_releases(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-002-m.md"),
            {"id": "MS-002", "type": "milestone", "title": "N", "status": "done"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-a.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-b.md"),
            {"id": "ISSUE-002", "type": "spike", "title": "B", "status": "new"},
        )

        rebuild(project_dir)
        summary = query_summary(project_dir)

        assert "milestones" in summary, (
            "summary must have 'milestones' key (not 'releases')"
        )
        assert summary["milestones"]["total"] == 2

    def test_summary_linked_open_count(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-002-m.md"),
            {"id": "MS-002", "type": "milestone", "title": "N", "status": "done"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-a.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-b.md"),
            {"id": "ISSUE-002", "type": "spike", "title": "B", "status": "new"},
        )

        rebuild(project_dir)
        summary = query_summary(project_dir)

        assert summary["linked"]["open"] == 1

    def test_summary_unlinked_open_count(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-002-m.md"),
            {"id": "MS-002", "type": "milestone", "title": "N", "status": "done"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-a.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-b.md"),
            {"id": "ISSUE-002", "type": "spike", "title": "B", "status": "new"},
        )

        rebuild(project_dir)
        summary = query_summary(project_dir)

        assert summary["unlinked"]["open"] == 1


# ---------------------------------------------------------------------------
# Feature: Priority sort
# ---------------------------------------------------------------------------

class TestBacklogSortsPriorityOrder:
    """Scenario: Backlog sorts P1 before P2 before P3"""

    def test_p1_before_p2_before_p3(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-low.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Low",
             "status": "new", "priority": "P3"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-high.md"),
            {"id": "ISSUE-002", "type": "enhancement", "title": "High",
             "status": "new", "priority": "P1"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-003-med.md"),
            {"id": "ISSUE-003", "type": "enhancement", "title": "Med",
             "status": "new", "priority": "P2"},
        )

        rebuild(project_dir)
        backlog = query_backlog(project_dir)
        ids = [item["id"] for item in backlog]

        assert ids == ["ISSUE-002", "ISSUE-003", "ISSUE-001"]


class TestBacklogSortsLegacyPriorities:
    """Scenario: Backlog sorts legacy priorities correctly"""

    def test_now_before_later(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-later.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Later",
             "status": "new", "priority": "later"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-now.md"),
            {"id": "ISSUE-002", "type": "enhancement", "title": "Now",
             "status": "new", "priority": "now"},
        )

        rebuild(project_dir)
        backlog = query_backlog(project_dir)
        ids = [item["id"] for item in backlog]

        assert ids == ["ISSUE-002", "ISSUE-001"]


# ---------------------------------------------------------------------------
# Feature: Dependencies
# ---------------------------------------------------------------------------

class TestIssueDependsOnStoredInDependenciesTable:
    """Scenario: Issue depends_on is stored in dependencies table"""

    def test_issue_depends_on_stored_with_item_id_column(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-092-cache.md"),
            {"id": "ISSUE-092", "type": "enhancement", "title": "Cache update",
             "status": "new", "depends_on": ["ISSUE-091"]},
        )

        rebuild(project_dir)

        conn = sqlite3.connect(db_path(project_dir))
        conn.row_factory = sqlite3.Row
        # Must be in a table with item_id and depends_on columns
        # Try "dependencies" first (new schema name), then fall back
        row = None
        for table in ("dependencies", "item_dependencies"):
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE item_id = ? AND depends_on = ?",
                    ("ISSUE-092", "ISSUE-091")
                ).fetchone()
                if row is not None:
                    break
            except sqlite3.OperationalError:
                pass
        conn.close()

        assert row is not None, (
            "Expected a row with item_id='ISSUE-092' and depends_on='ISSUE-091' "
            "in the dependencies or item_dependencies table"
        )


class TestEpicDependsOnStoredInDependenciesTable:
    """Scenario: Epic depends_on is stored in dependencies table"""

    def test_epic_depends_on_stored_with_item_id_column(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-002-next.md"),
            {"id": "EP-002", "type": "epic", "title": "Next",
             "status": "planned", "depends_on": ["EP-001"]},
        )

        rebuild(project_dir)

        conn = sqlite3.connect(db_path(project_dir))
        conn.row_factory = sqlite3.Row
        row = None
        for table in ("dependencies", "item_dependencies"):
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE item_id = ? AND depends_on = ?",
                    ("EP-002", "EP-001")
                ).fetchone()
                if row is not None:
                    break
            except sqlite3.OperationalError:
                pass
        conn.close()

        assert row is not None, (
            "Expected a row with item_id='EP-002' and depends_on='EP-001' "
            "in the dependencies or item_dependencies table"
        )


# ---------------------------------------------------------------------------
# Feature: next-id counter
# ---------------------------------------------------------------------------

class TestNextIdScansAllDirectories:
    """Scenario: next-id for ISSUE scans all directories"""

    def test_next_id_uses_max_across_all_scan_paths(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-050-a.md"),
            {"id": "ISSUE-050", "type": "enhancement", "title": "A", "status": "new"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-100-b.md"),
            {"id": "ISSUE-100", "type": "enhancement", "title": "B", "status": "done"},
        )

        rebuild(project_dir)
        result = query_next_id(project_dir, "ISSUE")

        assert result["next_id"] == "ISSUE-101"


# ---------------------------------------------------------------------------
# Feature: Epic-issues query (replaces epic-stories)
# ---------------------------------------------------------------------------

class TestEpicIssuesReturnsAllWorkflowTypes:
    """Scenario: Epic-issues returns all workflow types linked to an epic"""

    def test_epic_issues_returns_all_three_types_including_done(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-a.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-011-b.md"),
            {"id": "ISSUE-011", "type": "bug-fix", "title": "B",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-012-c.md"),
            {"id": "ISSUE-012", "type": "tech-debt", "title": "C",
             "status": "done", "epic": "EP-001"},
        )

        rebuild(project_dir)

        assert query_epic_issues is not None, (
            "query_epic_issues must be importable from scripts.cache"
        )

        result_all = query_epic_issues(project_dir, "EP-001", include_done=True)
        assert len(result_all) == 3

    def test_epic_issues_excluding_done_returns_two(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "milestone": "MS-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-a.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-011-b.md"),
            {"id": "ISSUE-011", "type": "bug-fix", "title": "B",
             "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-012-c.md"),
            {"id": "ISSUE-012", "type": "tech-debt", "title": "C",
             "status": "done", "epic": "EP-001"},
        )

        rebuild(project_dir)

        assert query_epic_issues is not None, (
            "query_epic_issues must be importable from scripts.cache"
        )

        result_open = query_epic_issues(project_dir, "EP-001", include_done=False)
        assert len(result_open) == 2


class TestEpicStoriesAliasForEpicIssues:
    """Scenario: Epic-stories is an alias for epic-issues"""

    def test_epic_stories_and_epic_issues_return_identical_results(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-a.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "A",
             "status": "new", "epic": "EP-001"},
        )

        rebuild(project_dir)

        assert query_epic_issues is not None, (
            "query_epic_issues must be importable from scripts.cache"
        )

        result_stories = query_epic_stories(project_dir, "EP-001", include_done=True)
        result_issues = query_epic_issues(project_dir, "EP-001", include_done=True)

        assert result_stories == result_issues


# ---------------------------------------------------------------------------
# Feature: Schema correctness
# ---------------------------------------------------------------------------

class TestSchemaHasMilestoneColumnNotRelease:
    """Scenario: Schema has milestone column and index, not release"""

    def test_items_table_has_milestone_column(self, tmp_path):
        project_dir = setup_project(tmp_path)
        rebuild(project_dir)
        cols = get_schema_columns(project_dir, "items")
        assert "milestone" in cols

    def test_items_table_does_not_have_release_column(self, tmp_path):
        project_dir = setup_project(tmp_path)
        rebuild(project_dir)
        cols = get_schema_columns(project_dir, "items")
        assert "release" not in cols

    def test_index_exists_on_items_milestone(self, tmp_path):
        project_dir = setup_project(tmp_path)
        rebuild(project_dir)
        indexes = get_schema_indexes(project_dir)
        # Accept any index name that references milestone on items
        conn = sqlite3.connect(db_path(project_dir))
        rows = conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        milestone_index = any(
            row[1] == "items" and "milestone" in (row[2] or "").lower()
            for row in rows
        )
        assert milestone_index, (
            "Expected an index on items(milestone) but none found. "
            f"Available indexes: {[(r[0], r[1], r[2]) for r in rows]}"
        )


class TestDependenciesTableUsesItemId:
    """Scenario: Dependencies table uses item_id not epic_id"""

    def test_dependencies_table_has_item_id_column(self, tmp_path):
        project_dir = setup_project(tmp_path)
        rebuild(project_dir)

        conn = sqlite3.connect(db_path(project_dir))
        found_table = None
        found_cols = []
        for table in ("dependencies", "item_dependencies", "epic_dependencies"):
            cursor = conn.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]
            if cols:
                found_table = table
                found_cols = cols
                break
        conn.close()

        assert found_table is not None, "Expected a dependencies-like table to exist"
        assert "item_id" in found_cols, (
            f"Expected 'item_id' column in {found_table}, got columns: {found_cols}"
        )
        assert "depends_on" in found_cols, (
            f"Expected 'depends_on' column in {found_table}, got columns: {found_cols}"
        )
        assert "epic_id" not in found_cols, (
            f"Column 'epic_id' must be renamed to 'item_id' in {found_table}"
        )


class TestCompletionCriteriaTableStillWorksForEpics:
    """Scenario: Completion criteria table still works for epics"""

    def test_epic_has_three_criteria_with_two_done(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")

        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active",
             "completion_criteria": ["A done", "B done", "C done"],
             "completion_criteria_done": [0, 2]},
        )

        rebuild(project_dir)
        criteria = get_completion_criteria(project_dir, "EP-001")

        assert len(criteria) == 3
        done_count = sum(1 for c in criteria if c["done"])
        assert done_count == 2


# ---------------------------------------------------------------------------
# QA caucus additions
# ---------------------------------------------------------------------------


class TestBacklogUnlinkedOnly:
    """backlog(unlinked_only=True) must exclude items with an epic field — used by big-picture."""

    def test_unlinked_only_excludes_items_with_epic(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-001-linked.md"),
            {"id": "ISSUE-001", "type": "enhancement", "title": "Linked", "status": "new", "epic": "EP-001"},
        )
        write_frontmatter_file(
            os.path.join(base, "backlog", "ISSUE-002-unlinked.md"),
            {"id": "ISSUE-002", "type": "bug-fix", "title": "Unlinked", "status": "new"},
        )

        rebuild(project_dir)
        backlog = query_backlog(project_dir, unlinked_only=True)
        ids = [item["id"] for item in backlog]

        assert "ISSUE-002" in ids
        assert "ISSUE-001" not in ids


class TestSummaryReleasesKeyAbsent:
    """summary must return 'milestones' key and NOT return 'releases' key."""

    def test_releases_key_absent_from_summary(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )

        rebuild(project_dir)
        summary = query_summary(project_dir)

        assert "milestones" in summary, "summary must contain 'milestones' key"
        assert "releases" not in summary, "summary must not contain legacy 'releases' key"


class TestStatusNormalizationFlowsToSummaryCounts:
    """A 'done (2026-05-02)' item must increment by_status['done'], not create a new bucket."""

    def test_compound_status_counted_as_bare_keyword(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-023-done.md"),
            {"id": "ISSUE-023", "type": "enhancement", "title": "Done", "status": "done (2026-05-02)"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "done", "ISSUE-024-done.md"),
            {"id": "ISSUE-024", "type": "spike", "title": "Also done", "status": "done"},
        )

        rebuild(project_dir)
        summary = query_summary(project_dir)

        assert summary["by_status"].get("done", 0) == 2
        assert "done (2026-05-02)" not in summary["by_status"]


class TestMilestonesCompactJsonShape:
    """Milestones-compact returned dicts must contain the keys big-picture expects."""

    def test_milestone_dict_has_required_keys(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "epics", "EP-001-e.md"),
            {"id": "EP-001", "type": "epic", "title": "E", "status": "active", "milestone": "MS-001",
             "completion_criteria": ["A"], "completion_criteria_done": []},
        )
        write_frontmatter_file(
            os.path.join(base, "roadmap", "issues", "ISSUE-010-a.md"),
            {"id": "ISSUE-010", "type": "enhancement", "title": "A", "status": "new", "epic": "EP-001"},
        )

        rebuild(project_dir)

        assert query_milestones_compact is not None, "query_milestones_compact must be importable"
        result = query_milestones_compact(project_dir)

        assert len(result) >= 1
        ms = result[0]
        for key in ("id", "title", "status", "epics"):
            assert key in ms, f"milestone dict missing key '{key}'"

        ep = ms["epics"][0]
        for key in ("id", "title", "status", "criteria_done", "criteria_total", "stories"):
            assert key in ep, f"epic dict missing key '{key}'"

        story = ep["stories"][0]
        for key in ("id", "title", "status"):
            assert key in story, f"story dict missing key '{key}'"


class TestCliRegistersNewQueryNames:
    """The CLI argparse choices must include milestones-compact and epic-issues."""

    def test_milestones_compact_in_cli_choices(self):
        import cache
        import argparse
        import io
        parser = argparse.ArgumentParser()
        # Re-parse the source to find the choices list
        import inspect
        source = inspect.getsource(cache.main)
        assert "milestones-compact" in source, "milestones-compact must be registered in CLI choices"

    def test_epic_issues_in_cli_choices(self):
        import cache
        import inspect
        source = inspect.getsource(cache.main)
        assert "epic-issues" in source, "epic-issues must be registered in CLI choices"


class TestNextIdEmptyCache:
    """next-id on an empty cache (new taxonomy paths) should return ISSUE-001."""

    def test_next_id_returns_001_when_no_issues_in_new_paths(self, tmp_path):
        project_dir = setup_project(tmp_path)
        base = str(tmp_path / ".sweetclaude" / "product")
        write_frontmatter_file(
            os.path.join(base, "roadmap", "milestones", "MS-001-m.md"),
            {"id": "MS-001", "type": "milestone", "title": "M", "status": "active"},
        )

        rebuild(project_dir)
        result = query_next_id(project_dir, "ISSUE")

        assert result["next_id"] == "ISSUE-001"
        item_count = len(get_all_items(project_dir))
        assert item_count >= 1, "rebuild must find items in new taxonomy paths"
