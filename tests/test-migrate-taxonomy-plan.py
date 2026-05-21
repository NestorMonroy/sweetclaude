"""
Tests for plan building — Feature: Plan building
Translates: tests/features/issue-090-migrate-taxonomy-plan.feature
"""
import os
import re
import sys
import warnings
import yaml
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import build_plan

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
    make_yaml_frontmatter_file,
    make_bold_format_file,
    project_dir,  # noqa: F401 — pytest fixture
)


def _write_collision_map(project_dir, data: dict):
    state_dir(project_dir).mkdir(parents=True, exist_ok=True)
    collision_map_path(project_dir).write_text(yaml.safe_dump(data))


def _find_move(plan, new_id_prefix):
    """Return first PlannedMove whose new_id starts with new_id_prefix."""
    for move in plan.moves:
        if str(getattr(move, "new_id", "")).startswith(new_id_prefix):
            return move
    return None


def _find_move_by_action(plan, action, new_id_prefix=None):
    for move in plan.moves:
        if getattr(move, "action", None) == action:
            if new_id_prefix is None or str(getattr(move, "new_id", "")).startswith(
                new_id_prefix
            ):
                return move
    return None


# ---------------------------------------------------------------------------
# Scenario: BL with terminal status routes to roadmap/issues/done/
# ---------------------------------------------------------------------------

class TestBLTerminalStatusRoutesToDone:
    def test_bl_done_routes_to_roadmap_issues_done(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-050-old-feature.md",
            {"id": "BL-050", "title": "Old feature", "status": "done"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-050")
        assert move is not None
        assert "roadmap/issues/done" in str(move.dest).replace("\\", "/")
        assert move.action == "migrate"


# ---------------------------------------------------------------------------
# Scenario: BL with non-terminal status and epic routes to roadmap/issues/
# ---------------------------------------------------------------------------

class TestBLActiveWithEpicRoutesToRoadmapIssues:
    def test_bl_active_with_epic_routes_to_roadmap_issues(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {"id": "BL-042", "title": "Feature", "status": "active", "epic": "EP-001"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "roadmap/issues" in dest
        assert "done" not in dest


# ---------------------------------------------------------------------------
# Scenario: BL with non-terminal status and milestone but no epic routes to roadmap/issues/
# ---------------------------------------------------------------------------

class TestBLActiveWithMilestoneNoEpicRoutesToRoadmapIssues:
    def test_bl_active_with_milestone_routes_to_roadmap_issues(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {
                "id": "BL-042",
                "title": "Feature",
                "status": "active",
                "milestone": "MS-007",
            },
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "roadmap/issues" in dest


# ---------------------------------------------------------------------------
# Scenario: BL with non-terminal status and no epic or milestone routes to backlog/
# ---------------------------------------------------------------------------

class TestBLActiveNoEpicNoMilestoneRoutesToBacklog:
    def test_bl_new_no_epic_routes_to_backlog(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-070-baz.md",
            {"id": "BL-070", "title": "Baz", "status": "new"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-070")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "backlog" in dest
        assert "roadmap" not in dest


# ---------------------------------------------------------------------------
# Scenario: BL with PROMOTED status and parseable target
# ---------------------------------------------------------------------------

class TestBLPromotedParseable:
    def test_bl_promoted_has_status_superseded_and_superseded_by(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-082-promoted.md",
            "BL-082: Tracked workflows",
            {"Status": "PROMOTED", "Promoted to": "EP-009 (v4.1)"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-082")
        assert move is not None
        assert move.frontmatter["status"] == "superseded"
        assert move.frontmatter["superseded_by"] == "EP-009"


# ---------------------------------------------------------------------------
# Scenario: BL with PROMOTED status and unparseable target
# ---------------------------------------------------------------------------

class TestBLPromotedUnparseable:
    def test_bl_promoted_unparseable_target_warns(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-099-orphan.md",
            "BL-099: Orphan",
            {"Status": "PROMOTED", "Promoted to": "some narrative text"},
        )
        _write_collision_map(project_dir, {})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-099")
        assert move is not None
        assert move.frontmatter["superseded_by"] == "some narrative text"
        assert any(
            "superseded_by" in str(w.message).lower() for w in caught
        )


# ---------------------------------------------------------------------------
# Scenario: BL with PROMOTED status and no promoted_to field
# ---------------------------------------------------------------------------

class TestBLPromotedNoTarget:
    def test_bl_promoted_no_promoted_to_has_superseded_status_no_superseded_by(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-099-orphan.md",
            "BL-099: Orphan promoted",
            {"Status": "PROMOTED"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-099")
        assert move is not None
        assert move.frontmatter["status"] == "superseded"
        assert "superseded_by" not in move.frontmatter


# ---------------------------------------------------------------------------
# Scenario: STORY routes to roadmap/issues/done/
# ---------------------------------------------------------------------------

class TestStoryRoutesToDone:
    def test_story_routes_to_roadmap_issues_done(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {"id": "STORY-015", "title": "Alpha", "status": "done"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-015")
        if move is None:
            # Might have been remapped — check all moves with action=migrate
            for m in plan.moves:
                if "STORY-015" in str(getattr(m, "source", "")) or "STORY-015" in str(
                    getattr(m, "migrated_from", "")
                ):
                    move = m
                    break
        assert move is not None
        assert "roadmap/issues/done" in str(move.dest).replace("\\", "/")
        assert move.action == "migrate"


# ---------------------------------------------------------------------------
# Scenario: Colliding STORY uses remapped number
# ---------------------------------------------------------------------------

class TestCollidingStoryUsesRemappedNumber:
    def test_story_015_collision_maps_to_issue_87(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {"id": "STORY-015", "title": "Alpha", "status": "done"},
        )
        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87"})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-87")
        assert move is not None
        assert move.new_id == "ISSUE-87"
        assert move.frontmatter.get("migrated_from") == "STORY-15"


# ---------------------------------------------------------------------------
# Scenario: spike-BL routes to backlog with type spike
# ---------------------------------------------------------------------------

class TestSpikeBLRoutesToBacklogWithTypeSpike:
    def test_spike_bl_routes_to_backlog_with_spike_type(self, project_dir):
        sd = spike_dir(project_dir)
        sd.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            sd / "spike-BL-016-gstack.md",
            {"id": "spike-BL-016", "title": "GStack spike", "status": "done"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-016")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "backlog" in dest
        assert move.frontmatter.get("type") == "spike"
        assert move.frontmatter.get("migrated_from") == "spike-BL-016"


# ---------------------------------------------------------------------------
# Scenario: I-N file is archived as-is
# ---------------------------------------------------------------------------

class TestIFileArchivedAsIs:
    def test_i_file_routes_to_backlog_archived_with_archive_action(
        self, project_dir
    ):
        iss = issues_dir(project_dir)
        iss.mkdir(parents=True, exist_ok=True)
        (iss / "I-001-duplicate.md").write_text(
            "# I-001\n\n**Effort:** 3\n**Sprint:** 12\n**Source:** JIRA\n"
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move_by_action(plan, "archive")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "backlog/archived" in dest
        assert move.frontmatter == {}


# ---------------------------------------------------------------------------
# Scenario: RM-N file is retired
# ---------------------------------------------------------------------------

class TestRMFileIsRetired:
    def test_rm_file_has_retire_action(self, project_dir):
        rm = roadmap_dir(project_dir)
        rm.mkdir(parents=True, exist_ok=True)
        (rm / "RM-001-mvp.md").write_text("# RM-001: MVP\n\n**Status:** achieved\n")
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move_by_action(plan, "retire")
        assert move is not None


# ---------------------------------------------------------------------------
# Scenario: MS-N file is restructured
# ---------------------------------------------------------------------------

class TestMSFileIsRestructured:
    def test_ms_file_routes_to_roadmap_milestones_with_restructure_action(
        self, project_dir
    ):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked workflows",
            {"Status": "active"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move_by_action(plan, "restructure")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "roadmap/milestones" in dest


# ---------------------------------------------------------------------------
# Scenario: MS-N with proposed status — frontmatter status is "new"
# ---------------------------------------------------------------------------

class TestMSProposedStatusBecomesNew:
    def test_ms_proposed_status_remapped_to_new(self, project_dir):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked workflows",
            {"Status": "proposed"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move_by_action(plan, "restructure")
        assert move is not None
        dest = str(move.dest).replace("\\", "/")
        assert "roadmap/milestones" in dest
        assert move.frontmatter.get("status") == "new"


# ---------------------------------------------------------------------------
# Scenario: EP-N file already in new format — restructure only
# ---------------------------------------------------------------------------

class TestEPAlreadyNewFormat:
    def test_ep_file_routes_to_roadmap_epics_with_restructure(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "EP-001-taxonomy.md",
            {"id": "EP-001", "title": "Taxonomy", "status": "active"},
            "This epic has no legacy refs.",
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        ep_moves = [
            m for m in plan.moves if str(getattr(m, "new_id", "")).startswith("EP-001")
        ]
        restructure_moves = [m for m in ep_moves if m.action == "restructure"]
        rewrite_moves = [m for m in ep_moves if m.action == "rewrite-refs"]

        assert len(restructure_moves) >= 1
        dest = str(restructure_moves[0].dest).replace("\\", "/")
        assert "roadmap/epics" in dest
        assert len(rewrite_moves) == 0


# ---------------------------------------------------------------------------
# Scenario: EP-N file with legacy refs in body gets restructure + rewrite-refs
# ---------------------------------------------------------------------------

class TestEPWithLegacyRefsGetsRewriteRefs:
    def test_ep_with_bl_ref_in_body_gets_two_moves_restructure_then_rewrite(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "EP-001-taxonomy.md",
            {"id": "EP-001", "title": "Taxonomy", "status": "active"},
            "Blocks: BL-081\n",
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        ep_moves = [
            m for m in plan.moves if str(getattr(m, "new_id", "")).startswith("EP-001")
        ]
        actions = [m.action for m in ep_moves]
        assert "restructure" in actions
        assert "rewrite-refs" in actions

        restructure_idx = next(
            i for i, m in enumerate(plan.moves) if m.action == "restructure" and str(getattr(m, "new_id", "")).startswith("EP-001")
        )
        rewrite_idx = next(
            i for i, m in enumerate(plan.moves) if m.action == "rewrite-refs" and str(getattr(m, "new_id", "")).startswith("EP-001")
        )
        assert restructure_idx < rewrite_idx


# ---------------------------------------------------------------------------
# Scenario: Slug sanitization removes special characters
# ---------------------------------------------------------------------------

class TestSlugSanitization:
    def test_slug_contains_only_lowercase_alphanumeric_and_hyphens(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-widget-builder-v2.md",
            {
                "id": "BL-042",
                "title": "Widget builder (v2.0) — improved!",
                "status": "open",
            },
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        slug = os.path.basename(str(move.dest)).replace(".md", "").split("-", 1)[1]
        assert re.match(r"^[a-z0-9\-]+$", slug), f"Slug had invalid chars: {slug!r}"


# ---------------------------------------------------------------------------
# Scenario: Slug truncates to 60 characters with no trailing dash
# ---------------------------------------------------------------------------

class TestSlugTruncation:
    def test_slug_truncated_to_60_chars_no_trailing_dash(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        # Title that produces >60 char slug
        long_title = "a" * 30 + " " + "b" * 30
        make_yaml_frontmatter_file(
            bl / "BL-042-long.md",
            {"id": "BL-042", "title": long_title, "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        filename = os.path.basename(str(move.dest)).replace(".md", "")
        # filename is like "ISSUE-042-<slug>"
        slug = "-".join(filename.split("-")[2:])
        assert len(slug) <= 60
        assert not slug.endswith("-")


# ---------------------------------------------------------------------------
# Scenario: Empty title falls back to new_id
# ---------------------------------------------------------------------------

class TestEmptyTitleFallsBackToNewId:
    def test_empty_title_slug_is_issue_id(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042.md",
            {"id": "BL-042", "title": "", "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        filename = os.path.basename(str(move.dest))
        assert "issue-042" in filename.lower()


# ---------------------------------------------------------------------------
# Scenario: Title of all special characters falls back to new_id
# ---------------------------------------------------------------------------

class TestAllSpecialCharsTitleFallsBackToNewId:
    def test_special_chars_only_title_slug_is_issue_id(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042.md",
            {"id": "BL-042", "title": "---!!!", "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        filename = os.path.basename(str(move.dest))
        assert "issue-042" in filename.lower()


# ---------------------------------------------------------------------------
# Scenario: Unicode-only title falls back to new_id
# ---------------------------------------------------------------------------

class TestUnicodeTitleFallsBackToNewId:
    def test_unicode_only_title_slug_is_issue_id(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042.md",
            {"id": "BL-042", "title": "导航功能", "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        filename = os.path.basename(str(move.dest))
        assert "issue-042" in filename.lower()


# ---------------------------------------------------------------------------
# Scenario: Duplicate dest paths abort plan
# ---------------------------------------------------------------------------

class TestDuplicateDestPathsAbortPlan:
    def test_duplicate_dest_paths_raises_error_naming_both_paths(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        # Two files whose truncated-60 slugs would be identical
        long_title = "x" * 58
        make_yaml_frontmatter_file(
            bl / "BL-001-a.md",
            {"id": "BL-001", "title": long_title, "status": "open"},
        )
        make_yaml_frontmatter_file(
            bl / "BL-002-b.md",
            {"id": "BL-002", "title": long_title, "status": "open"},
        )
        _write_collision_map(project_dir, {})

        with pytest.raises(Exception) as exc:
            build_plan(project_dir=str(project_dir))

        assert "ISSUE-001" in str(exc.value) or "ISSUE-002" in str(exc.value)


# ---------------------------------------------------------------------------
# Scenario: Duplicate new_ids abort plan
# ---------------------------------------------------------------------------

class TestDuplicateNewIdsAbortPlan:
    def test_duplicate_new_id_from_bl_and_spike_raises_error(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-016-thing.md",
            {"id": "BL-016", "title": "Thing", "status": "open"},
        )
        sd = spike_dir(project_dir)
        sd.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            sd / "spike-BL-016-thing.md",
            {"id": "spike-BL-016", "title": "Spike thing", "status": "done"},
        )
        _write_collision_map(project_dir, {})

        with pytest.raises(Exception, match="ISSUE-016"):
            build_plan(project_dir=str(project_dir))


# ---------------------------------------------------------------------------
# Scenario: depends_on references are remapped via id_map
# ---------------------------------------------------------------------------

class TestDependsOnRemapping:
    def test_depends_on_bl_040_and_story_015_remapped_to_issue_ids(
        self, project_dir
    ):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {
                "id": "BL-042",
                "title": "Feature",
                "status": "active",
                "depends_on": ["BL-040", "STORY-015"],
            },
        )
        make_yaml_frontmatter_file(
            bl / "BL-040-dep.md",
            {"id": "BL-040", "title": "Dep", "status": "open"},
        )
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {"id": "STORY-015", "title": "Alpha", "status": "done"},
        )
        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87"})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        assert move is not None
        assert "ISSUE-040" in move.frontmatter.get("depends_on", [])
        assert "ISSUE-087" in move.frontmatter.get("depends_on", [])


# ---------------------------------------------------------------------------
# Scenario: superseded_by is cleaned to bare ID
# ---------------------------------------------------------------------------

class TestSupersededByCleanedToBareId:
    def test_promoted_to_ep_009_v41_cleaned_to_ep_009(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-082-promoted.md",
            "BL-082: Tracked workflows",
            {"Status": "PROMOTED", "Promoted to": "EP-009 (v4.1)"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-082")
        assert move is not None
        assert move.frontmatter.get("superseded_by") == "EP-009"


# ---------------------------------------------------------------------------
# Scenario: migrated_from is set when ID changes
# ---------------------------------------------------------------------------

class TestMigratedFromSet:
    def test_migrated_from_contains_original_bl_id(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {"id": "BL-042", "title": "Feature", "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-042")
        assert move is not None
        assert move.frontmatter.get("migrated_from") == "BL-042"


# ---------------------------------------------------------------------------
# Scenario: closed_date is preserved
# ---------------------------------------------------------------------------

class TestClosedDatePreserved:
    def test_closed_date_in_source_preserved_in_frontmatter(self, project_dir):
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            bl / "BL-050-old.md",
            "BL-050: Old feature",
            {"Status": "DONE — 2026-05-02", "Priority": "P3"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        move = _find_move(plan, "ISSUE-050")
        assert move is not None
        assert move.frontmatter.get("closed_date") == "2026-05-02"


# ---------------------------------------------------------------------------
# Scenario: Unrecognized fields from source are preserved
# ---------------------------------------------------------------------------

class TestUnrecognizedFieldsPreservedInFrontmatter:
    def test_shape_and_phase_fields_preserved(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {
                "id": "STORY-015",
                "title": "Alpha",
                "status": "done",
                "shape": "small",
                "phase": "ship",
            },
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        story_move = next(
            (
                m
                for m in plan.moves
                if m.frontmatter.get("migrated_from") in ("STORY-015", "STORY-15")
                or m.frontmatter.get("migrated_from", "").startswith("STORY")
            ),
            None,
        )
        assert story_move is not None
        assert story_move.frontmatter.get("shape") == "small"
        assert story_move.frontmatter.get("phase") == "ship"


# ---------------------------------------------------------------------------
# Scenario: Milestone body refs are rewritten
# ---------------------------------------------------------------------------

class TestMilestoneBodyRefsRewritten:
    def test_ms_body_bl_and_story_refs_rewritten_in_rewrite_refs_move(
        self, project_dir
    ):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked workflows",
            {"Status": "active"},
            body="See BL-042 and STORY-015",
        )
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {"id": "BL-042", "title": "Feature", "status": "active"},
        )
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            d / "STORY-015-alpha.md",
            {"id": "STORY-015", "title": "Alpha", "status": "done"},
        )
        _write_collision_map(project_dir, {"STORY-15": "ISSUE-87"})

        plan = build_plan(project_dir=str(project_dir))

        ms_rewrite = next(
            (
                m
                for m in plan.moves
                if m.action == "rewrite-refs"
                and "MS-007" in str(getattr(m, "new_id", ""))
            ),
            None,
        )
        assert ms_rewrite is not None
        assert "ISSUE-042" in ms_rewrite.body
        assert "ISSUE-87" in ms_rewrite.body


# ---------------------------------------------------------------------------
# Scenario: Refs not in id_map are left as-is with warning
# ---------------------------------------------------------------------------

class TestRefsNotInIdMapLeftAsIsWithWarning:
    def test_unknown_ref_preserved_and_warning_emitted(self, project_dir):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked",
            {"Status": "active"},
            body="See CHORE-999",
        )
        _write_collision_map(project_dir, {})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = build_plan(project_dir=str(project_dir))

        ms_rewrite = next(
            (m for m in plan.moves if m.action == "rewrite-refs"),
            None,
        )
        if ms_rewrite:
            assert "CHORE-999" in ms_rewrite.body
        assert any("CHORE-999" in str(w.message) for w in caught)


# ---------------------------------------------------------------------------
# Scenario: Word-boundary matching prevents partial matches
# ---------------------------------------------------------------------------

class TestWordBoundaryMatchingPreventsPartialMatches:
    def test_notable_42_not_matched_by_bl_42_rewrite(self, project_dir):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked",
            {"Status": "active"},
            body="NOTABLE-42 should not match",
        )
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {"id": "BL-042", "title": "Feature", "status": "open"},
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        ms_rewrite = next(
            (m for m in plan.moves if m.action == "rewrite-refs"),
            None,
        )
        if ms_rewrite:
            assert "NOTABLE-42" in ms_rewrite.body


# ---------------------------------------------------------------------------
# Scenario: rewrite-refs moves are ordered after restructure for same file
# ---------------------------------------------------------------------------

class TestRewriteRefsOrderedAfterRestructure:
    def test_restructure_before_rewrite_refs_in_plan_moves(self, project_dir):
        ms = milestones_dir(project_dir)
        ms.mkdir(parents=True, exist_ok=True)
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        make_yaml_frontmatter_file(
            bl / "BL-042-feature.md",
            {"id": "BL-042", "title": "Feature", "status": "open"},
        )
        make_bold_format_file(
            ms / "MS-007-tracked.md",
            "MS-007: Tracked",
            {"Status": "active"},
            body="See BL-042",
        )
        _write_collision_map(project_dir, {})

        plan = build_plan(project_dir=str(project_dir))

        ms_moves = [
            (i, m)
            for i, m in enumerate(plan.moves)
            if "MS-007" in str(getattr(m, "new_id", ""))
        ]
        actions_ordered = [m.action for _, m in ms_moves]
        if "restructure" in actions_ordered and "rewrite-refs" in actions_ordered:
            restructure_pos = actions_ordered.index("restructure")
            rewrite_pos = actions_ordered.index("rewrite-refs")
            assert restructure_pos < rewrite_pos
