"""
Tests for collision detection — Feature: Collision detection
Translates: tests/features/issue-090-migrate-taxonomy-collisions.feature
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

from migrate.migrate_taxonomy import detect_collisions, load_collision_map

from fixtures.migrate_taxonomy_fixtures import (
    backlog_dir,
    done_dir,
    state_dir,
    collision_map_path,
    project_dir,  # noqa: F401 — pytest fixture
)


def _write_bl_files(project_dir, numbers):
    """Write minimal BL files for the given number strings."""
    bl = backlog_dir(project_dir)
    bl.mkdir(parents=True, exist_ok=True)
    for n in numbers:
        (bl / f"BL-{n:03d}-item.md").write_text(f"# BL-{n:03d}: Item\n")


def _write_story_files(project_dir, numbers):
    """Write minimal STORY files in done/ for the given number strings."""
    d = done_dir(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    for n in numbers:
        (d / f"STORY-{n:03d}-item.md").write_text(f"# STORY-{n:03d}: Item\n")


# ---------------------------------------------------------------------------
# Scenario: No collisions when number spaces don't overlap
# ---------------------------------------------------------------------------

class TestNoCollisionsWhenNoOverlap:
    def test_no_collision_map_is_empty(self, project_dir):
        _write_bl_files(project_dir, [1, 2])
        _write_story_files(project_dir, [3])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert collision_map == {}

    def test_story_003_maps_to_issue_003_with_no_bl_collision(self, project_dir):
        _write_bl_files(project_dir, [1, 2])
        _write_story_files(project_dir, [3])

        collision_map = detect_collisions(project_dir=str(project_dir))

        # no entry means STORY-003 keeps its number → ISSUE-003
        assert "STORY-3" not in collision_map


# ---------------------------------------------------------------------------
# Scenario: Colliding STORY gets renumbered
# ---------------------------------------------------------------------------

class TestCollidingStoryGetsRenumbered:
    def test_story_015_collides_with_bl_gets_remapped_to_issue_87(self, project_dir):
        # max BL is 86 (numbers 1 through 86 omitted — just need STORY to collide)
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert "STORY-15" in collision_map
        assert collision_map["STORY-15"] == "ISSUE-87"


# ---------------------------------------------------------------------------
# Scenario: Multiple collisions renumbered sequentially
# ---------------------------------------------------------------------------

class TestMultipleCollisionsRenumberedSequentially:
    def test_three_colliding_stories_renumbered_87_88_89(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15, 16, 17])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert collision_map["STORY-15"] == "ISSUE-87"
        assert collision_map["STORY-16"] == "ISSUE-88"
        assert collision_map["STORY-17"] == "ISSUE-89"


# ---------------------------------------------------------------------------
# Scenario: Non-colliding STORY keeps its number
# ---------------------------------------------------------------------------

class TestNonCollidingStoryKeepsNumber:
    def test_story_100_outside_bl_range_no_collision(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [100])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert collision_map == {}


# ---------------------------------------------------------------------------
# Scenario: No BL files — STORY numbers kept as-is
# ---------------------------------------------------------------------------

class TestNoBLFilesStoryNumbersKeptAsIs:
    def test_no_bl_files_story_015_maps_to_issue_015_no_collision(self, project_dir):
        _write_story_files(project_dir, [15, 16])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert collision_map == {}
        assert "STORY-15" not in collision_map
        assert "STORY-16" not in collision_map


# ---------------------------------------------------------------------------
# Scenario: Determinism — same input produces same output
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_produces_same_collision_map(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15, 16])

        map1 = detect_collisions(project_dir=str(project_dir))
        map2 = detect_collisions(project_dir=str(project_dir))

        assert map1 == map2


# ---------------------------------------------------------------------------
# Scenario: STORY number collides with remapped number of another STORY
# ---------------------------------------------------------------------------

class TestStoryCollidesWithRemappedNumber:
    def test_story_015_remapped_to_87_and_story_087_keeps_its_number(
        self, project_dir
    ):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15, 87])

        collision_map = detect_collisions(project_dir=str(project_dir))

        assert collision_map["STORY-15"] == "ISSUE-87"
        assert "STORY-87" not in collision_map


# ---------------------------------------------------------------------------
# Scenario: Collision map key format uses unpadded numbers
# ---------------------------------------------------------------------------

class TestCollisionMapKeyFormat:
    def test_collision_map_key_is_unpadded(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15])

        collision_map = detect_collisions(project_dir=str(project_dir))

        # key must be "STORY-15" not "STORY-015"
        assert "STORY-15" in collision_map
        assert "STORY-015" not in collision_map
        # value must be "ISSUE-87" not "ISSUE-087"
        assert collision_map["STORY-15"] == "ISSUE-87"
        assert collision_map.get("STORY-15") != "ISSUE-087"


# ---------------------------------------------------------------------------
# Scenario: Duplicate STORY files with same number produce error
# ---------------------------------------------------------------------------

class TestDuplicateStoryNumberProducesError:
    def test_two_story_files_with_same_number_raises_error(self, project_dir):
        d = done_dir(project_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "STORY-015-alpha.md").write_text("# STORY-015: Alpha\n")
        (d / "STORY-015-beta.md").write_text("# STORY-015: Beta\n")

        with pytest.raises(Exception, match="15"):
            detect_collisions(project_dir=str(project_dir))


# ---------------------------------------------------------------------------
# Scenario: Collision map is persisted to disk
# ---------------------------------------------------------------------------

class TestCollisionMapPersistedToDisk:
    def test_detect_collisions_writes_collision_map_yaml(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15])

        detect_collisions(project_dir=str(project_dir), persist=True)

        assert collision_map_path(project_dir).exists()

    def test_collision_map_yaml_contains_story_15_mapping(self, project_dir):
        _write_bl_files(project_dir, list(range(1, 87)))
        _write_story_files(project_dir, [15])

        detect_collisions(project_dir=str(project_dir), persist=True)

        data = yaml.safe_load(collision_map_path(project_dir).read_text())
        assert data["STORY-15"] == "ISSUE-87"


# ---------------------------------------------------------------------------
# Scenario: Persisted collision map is reused with correct mappings
# ---------------------------------------------------------------------------

class TestPersistedCollisionMapReused:
    def test_load_collision_map_returns_dict_with_correct_mapping(
        self, project_dir
    ):
        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_text(
            yaml.safe_dump({"STORY-15": "ISSUE-87"})
        )

        result = load_collision_map(project_dir=str(project_dir))

        assert result == {"STORY-15": "ISSUE-87"}


# ---------------------------------------------------------------------------
# Scenario: Empty collision map YAML is treated as no persisted map
# ---------------------------------------------------------------------------

class TestEmptyCollisionMapTreatedAsNone:
    def test_empty_collision_map_yaml_returns_none(self, project_dir):
        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_bytes(b"")

        result = load_collision_map(project_dir=str(project_dir))

        assert result is None


# ---------------------------------------------------------------------------
# Scenario: Invalid collision map YAML is treated as no persisted map
# ---------------------------------------------------------------------------

class TestInvalidCollisionMapYAMLReturnsNone:
    def test_invalid_yaml_returns_none_and_emits_warning(self, project_dir):
        import warnings
        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_text(
            "{{{{invalid yaml content[[["
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = load_collision_map(project_dir=str(project_dir))

        assert result is None
        assert any("collision map" in str(w.message).lower() for w in caught)


# ---------------------------------------------------------------------------
# Scenario: Collision map is locked when execute begins
# ---------------------------------------------------------------------------

class TestCollisionMapLockedOnExecute:
    def test_execute_writes_locked_true_to_collision_map(self, project_dir):
        from migrate.migrate_taxonomy import execute, build_plan, scan_sources

        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_text(
            yaml.safe_dump({"STORY-15": "ISSUE-87"})
        )

        # Build a minimal plan to drive execute()
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n\n**Status:** open\n")

        plan = build_plan(project_dir=str(project_dir))
        execute(plan, project_dir=str(project_dir), dry_run=True)

        # Even dry-run should lock (or: full execute before dry_run check)
        # The Gherkin says "when execute() begins" — so the lock happens before
        # dry_run short-circuit. Test full execute instead:
        execute(plan, project_dir=str(project_dir))

        data = yaml.safe_load(collision_map_path(project_dir).read_text())
        assert data.get("locked") is True


# ---------------------------------------------------------------------------
# Scenario: Locked collision map is never regenerated
# ---------------------------------------------------------------------------

class TestLockedCollisionMapNeverRegenerated:
    def test_plan_uses_locked_collision_map_without_regenerating(
        self, project_dir
    ):
        from migrate.migrate_taxonomy import build_plan

        state_dir(project_dir).mkdir(parents=True, exist_ok=True)
        collision_map_path(project_dir).write_text(
            yaml.safe_dump({"STORY-15": "ISSUE-87", "locked": True})
        )

        # Some source files deleted by partial run — only BL-001 remains
        bl = backlog_dir(project_dir)
        bl.mkdir(parents=True, exist_ok=True)
        (bl / "BL-001-foo.md").write_text("# BL-001: Foo\n\n**Status:** open\n")

        plan = build_plan(project_dir=str(project_dir))

        # The locked map should be used — STORY-15 assignment preserved
        assert plan.collision_map["STORY-15"] == "ISSUE-87"
