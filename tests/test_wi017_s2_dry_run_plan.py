"""
WI-017 S2 — Dry-run plan engine tests.

Covers every scenario in tests/features/wi-017-s2-dry-run-plan.feature.
All tests call run_migration(project_dir, dry_run=True) with real on-disk
file trees; NO mocks.

Implementer contract — new keys added to the dry-run result dict:
  result["moves"]              — list of planned work-item move dicts, each with:
    move["legacy_id"]          — original id (e.g. "STORY-024", "EPIC-003", "US-DM-002")
    move["new_id"]             — assigned v4 id (e.g. "ISSUE-NNN", "EP-003")
    move["source"]             — product-base-relative source path string
    move["dest"]               — product-base-relative destination path string
    move["action"]             — action string (e.g. "migrate", "restructure")
    move["tier"]               — "A" (high confidence) or "B" (low confidence)
    move["epic"]               — (optional) new epic id for stories that have a parent epic

  result["id_map"]             — dict mapping every remapped legacy_id -> {"new_id": str, "source": str}
                                  MS-* and SP-* ids must NOT appear here (unchanged)

  result["reference_edits"]    — list of dicts, each:
    edit["file"]               — product-base-relative path of the file containing the reference
    edit["old_id"]             — the old id string found in the body/frontmatter
    edit["new_id"]             — the replacement id string

  result["conflicts"]          — list of conflict dicts, each:
    conflict["id"]             — the legacy id with a real duplicate (e.g. "STORY-007")
    conflict["files"]          — list of product-base-relative paths involved
    conflict["status"]         — "decision required"

  result["flags"]              — list of flag dicts, each:
    flag["id"]                 — the legacy id with low confidence
    flag["reason"]             — human-readable reason string
    flag["tier"]               — "B"
"""
import re
import sys
import os

# Make scripts/ importable — mirrors conftest.py convention
_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from pathlib import Path
import pytest
import yaml

# ---------------------------------------------------------------------------
# Deferred import: run_migration does not exist yet in the worktree.
# We import at module load so collection succeeds; individual test calls
# will raise AttributeError/ImportError when they invoke _dry_run(), which
# is the genuine MISSING BEHAVIOR failure — not a setup error.
# ---------------------------------------------------------------------------
try:
    from migrate.migrate_taxonomy import run_migration as _run_migration
    _RUN_MIGRATION_MISSING = False
except ImportError:
    _run_migration = None
    _RUN_MIGRATION_MISSING = True


# ---------------------------------------------------------------------------
# Helpers — shared by all test classes
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    """
    Create a minimal project where docs/product is the product base.
    Returns (project_root, product_base).
    Uses artifact-privacy.yaml so _get_product_base() finds docs/product.
    """
    project = tmp_path / "project"
    product = project / "docs" / "product"
    product.mkdir(parents=True)

    sc = project / ".sweetclaude"
    sc.mkdir(parents=True)
    privacy = {"product": {"base_path": "docs/product"}}
    (sc / "artifact-privacy.yaml").write_text(yaml.safe_dump(privacy))

    return project, product


def _write_md(
    product_base: Path,
    rel: str,
    frontmatter: dict | None = None,
    body: str = "",
) -> Path:
    """Write a Markdown file at <product_base>/<rel>."""
    target = product_base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter is not None:
        fm_yaml = yaml.safe_dump(frontmatter, default_flow_style=False).strip()
        content = f"---\n{fm_yaml}\n---\n\n{body}"
    else:
        content = f"# No frontmatter\n\n{body}" if not body else f"# File\n\n{body}"
    target.write_text(content, encoding="utf-8")
    return target


def _snapshot(root: Path) -> dict[str, bytes]:
    """Snapshot all file paths and content under root."""
    snap = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p)] = p.read_bytes()
    return snap


def _dry_run(project: Path, **kwargs) -> dict:
    """
    Call run_migration with dry_run=True and return the result dict.
    Raises pytest.fail with a clear message if run_migration is missing.
    """
    if _RUN_MIGRATION_MISSING or _run_migration is None:
        pytest.fail(
            "run_migration is not exported from migrate.migrate_taxonomy — "
            "this is the missing behavior being tested (S2 implementation does not exist yet)"
        )
    return _run_migration(str(project), dry_run=True, **kwargs)


def _find_move(result: dict, legacy_id: str) -> dict | None:
    """Return the first move dict matching the given legacy_id, or None."""
    for m in result.get("moves", []):
        if m.get("legacy_id") == legacy_id:
            return m
    return None


def _find_id_map_entry(result: dict, legacy_id: str) -> dict | None:
    """Return the id_map entry for legacy_id, or None."""
    return result.get("id_map", {}).get(legacy_id)


ISSUE_RE = re.compile(r"^ISSUE-\d+$")
EP_RE = re.compile(r"^EP-\d+$")


# ===========================================================================
# Scenario: Typed backlog dirs are planned for migration
# ===========================================================================

class TestTypedBacklogDirsMigration:
    """
    Gherkin: typed-dir STORY and DEBT files get a new ISSUE-NNN id,
    legacy_id is preserved, dest is under flat standard backlog (NOT a typed subdir).
    """

    def test_typed_story_gets_issue_id(self, tmp_path):
        # Given "backlog/stories/STORY-024-parallel-run.md" with frontmatter id "STORY-024"
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        # result["moves"] must exist with an entry for STORY-024
        assert "moves" in result, "dry-run result must contain a 'moves' key"
        move = _find_move(result, "STORY-024")
        assert move is not None, "plan must contain a move for STORY-024"
        assert ISSUE_RE.match(move["new_id"]), (
            f"STORY-024 new_id must match ISSUE-\\d+, got {move['new_id']!r}"
        )

    def test_typed_story_preserves_legacy_id(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        move = _find_move(result, "STORY-024")
        assert move is not None, "plan must contain a move for STORY-024"
        # legacy_id is the original id before remapping
        assert move["legacy_id"] == "STORY-024", (
            f"move.legacy_id must be 'STORY-024', got {move.get('legacy_id')!r}"
        )

    def test_typed_story_dest_not_in_typed_subdir(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        move = _find_move(result, "STORY-024")
        assert move is not None, "plan must contain a move for STORY-024"
        # dest must be under backlog/ (flat standard) not backlog/stories/
        dest = move.get("dest", "")
        assert "backlog/stories/" not in dest, (
            f"STORY-024 dest must not be under a typed subdir, got {dest!r}"
        )
        assert "backlog" in dest or "roadmap" in dest, (
            f"STORY-024 dest must be under standard backlog layout, got {dest!r}"
        )

    def test_typed_debt_gets_issue_id(self, tmp_path):
        # Given "backlog/debt/DEBT-001-creds.md" with frontmatter id "DEBT-001" type "tech-debt"
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/debt/DEBT-001-creds.md",
                  frontmatter={"id": "DEBT-001", "title": "Remove creds", "status": "new", "type": "tech-debt"})

        result = _dry_run(project)

        assert "moves" in result, "dry-run result must contain a 'moves' key"
        move = _find_move(result, "DEBT-001")
        assert move is not None, "plan must contain a move for DEBT-001"
        assert ISSUE_RE.match(move["new_id"]), (
            f"DEBT-001 new_id must match ISSUE-\\d+, got {move['new_id']!r}"
        )

    def test_typed_debt_preserves_legacy_id(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/debt/DEBT-001-creds.md",
                  frontmatter={"id": "DEBT-001", "title": "Remove creds", "status": "new", "type": "tech-debt"})

        result = _dry_run(project)

        move = _find_move(result, "DEBT-001")
        assert move is not None, "plan must contain a move for DEBT-001"
        assert move["legacy_id"] == "DEBT-001", (
            f"move.legacy_id must be 'DEBT-001', got {move.get('legacy_id')!r}"
        )

    def test_typed_debt_dest_not_in_typed_subdir(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/debt/DEBT-001-creds.md",
                  frontmatter={"id": "DEBT-001", "title": "Remove creds", "status": "new", "type": "tech-debt"})

        result = _dry_run(project)

        move = _find_move(result, "DEBT-001")
        assert move is not None, "plan must contain a move for DEBT-001"
        dest = move.get("dest", "")
        assert "backlog/debt/" not in dest, (
            f"DEBT-001 dest must not be under a typed subdir, got {dest!r}"
        )

    def test_moves_key_has_required_fields(self, tmp_path):
        # Each move must expose: legacy_id, new_id, source, dest, action, tier
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        move = _find_move(result, "STORY-024")
        assert move is not None, "plan must contain a move for STORY-024"
        for field in ("legacy_id", "new_id", "source", "dest", "action", "tier"):
            assert field in move, (
                f"move dict must contain field '{field}', got keys: {list(move.keys())}"
            )

    def test_moves_tier_is_a_or_b(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        move = _find_move(result, "STORY-024")
        assert move is not None, "plan must contain a move for STORY-024"
        assert move.get("tier") in ("A", "B"), (
            f"move.tier must be 'A' or 'B', got {move.get('tier')!r}"
        )


# ===========================================================================
# Scenario: Top-level old-prefix files are planned for migration
# ===========================================================================

class TestTopLevelOldPrefixMigration:
    """
    Gherkin: top-level BL-* files at the product base root get a new ISSUE-NNN id.
    """

    def test_top_level_bl_gets_issue_id(self, tmp_path):
        # Given "BL-005-product-brief.md" with frontmatter id "BL-005" at the product base root
        project, product = _make_project(tmp_path)
        _write_md(product, "BL-005-product-brief.md",
                  frontmatter={"id": "BL-005", "title": "Product brief", "status": "new", "type": "story"})

        result = _dry_run(project)

        assert "moves" in result, "dry-run result must contain a 'moves' key"
        move = _find_move(result, "BL-005")
        assert move is not None, "plan must contain a move for BL-005"
        assert ISSUE_RE.match(move["new_id"]), (
            f"BL-005 new_id must match ISSUE-\\d+, got {move['new_id']!r}"
        )

    def test_top_level_bl_legacy_id_preserved(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "BL-005-product-brief.md",
                  frontmatter={"id": "BL-005", "title": "Product brief", "status": "new", "type": "story"})

        result = _dry_run(project)

        move = _find_move(result, "BL-005")
        assert move is not None, "plan must contain a move for BL-005"
        assert move["legacy_id"] == "BL-005", (
            f"move.legacy_id must be 'BL-005', got {move.get('legacy_id')!r}"
        )


# ===========================================================================
# Scenario: Bespoke epics map to EP with number preserved
# ===========================================================================

class TestBespokeEpicMapping:
    """
    Gherkin: EPIC-003/EPIC-003.md (no frontmatter) -> EP-003, legacy_id "EPIC-003".
    """

    def test_bespoke_epic_maps_to_ep_003(self, tmp_path):
        # Given "stories/EPIC-003/EPIC-003.md" with no frontmatter
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md")

        result = _dry_run(project)

        assert "moves" in result, "dry-run result must contain a 'moves' key"
        move = _find_move(result, "EPIC-003")
        assert move is not None, "plan must contain a move for EPIC-003"
        assert move["new_id"] == "EP-003", (
            f"EPIC-003 must map to 'EP-003' (number preserved), got {move['new_id']!r}"
        )

    def test_bespoke_epic_legacy_id_recorded(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md")

        result = _dry_run(project)

        move = _find_move(result, "EPIC-003")
        assert move is not None, "plan must contain a move for EPIC-003"
        assert move["legacy_id"] == "EPIC-003", (
            f"move.legacy_id must be 'EPIC-003', got {move.get('legacy_id')!r}"
        )


# ===========================================================================
# Scenario: Bespoke user stories map to ISSUE and re-link to their epic's new id
# ===========================================================================

class TestBespokeUserStoryMapping:
    """
    Gherkin: US-DM-002 -> ISSUE-NNN; its planned epic field == the epic's new id (EP-003).
    """

    def _make_epic_tree(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")
        return project, product

    def test_bespoke_story_maps_to_issue(self, tmp_path):
        project, _ = self._make_epic_tree(tmp_path)

        result = _dry_run(project)

        assert "moves" in result, "dry-run result must contain a 'moves' key"
        move = _find_move(result, "US-DM-002")
        assert move is not None, "plan must contain a move for US-DM-002"
        assert ISSUE_RE.match(move["new_id"]), (
            f"US-DM-002 new_id must match ISSUE-\\d+, got {move['new_id']!r}"
        )

    def test_bespoke_story_epic_set_to_new_ep_003(self, tmp_path):
        # The planned frontmatter for US-DM-002 sets epic to the new epic id "EP-003"
        project, _ = self._make_epic_tree(tmp_path)

        result = _dry_run(project)

        move = _find_move(result, "US-DM-002")
        assert move is not None, "plan must contain a move for US-DM-002"
        # The move must expose the planned epic link as the new id of the parent
        assert "epic" in move, (
            f"move for US-DM-002 must contain an 'epic' field; got keys: {list(move.keys())}"
        )
        assert move["epic"] == "EP-003", (
            f"US-DM-002 planned epic must be 'EP-003', got {move.get('epic')!r}"
        )


# ===========================================================================
# Scenario: Milestones and sprints are left unchanged
# ===========================================================================

class TestMilestonesAndSprintsUnchanged:
    """
    Gherkin: MS-001 and SP-001 must NOT appear in the id remap (id_map).
    """

    def test_ms_not_in_id_map(self, tmp_path):
        # Given "milestones/MS-001-core.md" with frontmatter id "MS-001"
        project, product = _make_project(tmp_path)
        _write_md(product, "milestones/MS-001-core.md",
                  frontmatter={"id": "MS-001", "title": "Core milestone", "status": "active", "type": "milestone"})

        result = _dry_run(project)

        # MS-001 must NOT appear in the id_map (no remapping)
        assert "id_map" in result, "dry-run result must contain an 'id_map' key"
        id_map = result["id_map"]
        assert "MS-001" not in id_map, (
            "MS-001 must NOT appear in id_map — milestones are unchanged"
        )

    def test_sp_not_in_id_map(self, tmp_path):
        # Given "sprints/SP-001-hardening.md" with frontmatter id "SP-001"
        project, product = _make_project(tmp_path)
        _write_md(product, "sprints/SP-001-hardening.md",
                  frontmatter={"id": "SP-001", "title": "Hardening sprint", "status": "active", "type": "sprint"})

        result = _dry_run(project)

        assert "id_map" in result, "dry-run result must contain an 'id_map' key"
        id_map = result["id_map"]
        assert "SP-001" not in id_map, (
            "SP-001 must NOT appear in id_map — sprints are unchanged"
        )


# ===========================================================================
# Scenario: The id remap is bijective and deterministic
# ===========================================================================

class TestIdRemapBijectiveDeterministic:
    """
    Gherkin: two runs produce identical id remaps; all new ids unique;
    no two legacy ids share a new id.
    """

    def _make_mixed_tree(self, tmp_path) -> Path:
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-010-alpha.md",
                  frontmatter={"id": "STORY-010", "title": "Alpha", "status": "new", "type": "story"})
        _write_md(product, "backlog/debt/DEBT-002-legacy-auth.md",
                  frontmatter={"id": "DEBT-002", "title": "Legacy auth", "status": "new", "type": "tech-debt"})
        _write_md(product, "BL-007-feature.md",
                  frontmatter={"id": "BL-007", "title": "Feature", "status": "new", "type": "story"})
        _write_md(product, "stories/EPIC-003/EPIC-003.md")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")
        return project

    def test_two_runs_produce_identical_id_remaps(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = _dry_run(project)
        r2 = _dry_run(project)

        assert "id_map" in r1, "first run must have id_map"
        assert "id_map" in r2, "second run must have id_map"
        assert r1["id_map"] == r2["id_map"], (
            "id_map must be identical across two dry-run calls (deterministic)"
        )

    def test_all_new_ids_unique(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        result = _dry_run(project)

        assert "id_map" in result, "dry-run result must have id_map"
        new_ids = [entry["new_id"] for entry in result["id_map"].values()]
        assert len(new_ids) == len(set(new_ids)), (
            f"all new ids must be unique across the plan; duplicates found: "
            f"{[nid for nid in new_ids if new_ids.count(nid) > 1]}"
        )

    def test_no_two_legacy_ids_share_a_new_id(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        result = _dry_run(project)

        assert "id_map" in result, "dry-run result must have id_map"
        # Build reverse map: new_id -> list of legacy_ids
        reverse: dict[str, list[str]] = {}
        for legacy_id, entry in result["id_map"].items():
            nid = entry["new_id"]
            reverse.setdefault(nid, []).append(legacy_id)

        collisions = {nid: legs for nid, legs in reverse.items() if len(legs) > 1}
        assert not collisions, (
            f"no two legacy ids may share a new id; found collisions: {collisions}"
        )

    def test_moves_list_deterministic(self, tmp_path):
        project = self._make_mixed_tree(tmp_path)

        r1 = _dry_run(project)
        r2 = _dry_run(project)

        assert "moves" in r1 and "moves" in r2, "both runs must have moves"
        ids1 = sorted(m["legacy_id"] for m in r1["moves"])
        ids2 = sorted(m["legacy_id"] for m in r2["moves"])
        assert ids1 == ids2, (
            "moves set must be identical across two dry-run calls"
        )


# ===========================================================================
# Scenario: New ISSUE numbers continue past existing ISSUE ids
# ===========================================================================

class TestIssueNumbersContinuePastExisting:
    """
    Gherkin: existing ISSUE-050-existing.md means STORY-001's new_id number > 50;
    ISSUE-050 itself is NOT remapped.
    """

    def test_story_new_id_number_greater_than_fifty(self, tmp_path):
        # Given an existing "backlog/ISSUE-050-existing.md" with frontmatter id "ISSUE-050"
        # And a typed-dir "backlog/stories/STORY-001-x.md" with id "STORY-001"
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/ISSUE-050-existing.md",
                  frontmatter={"id": "ISSUE-050", "title": "Existing", "status": "active", "type": "story"})
        _write_md(product, "backlog/stories/STORY-001-x.md",
                  frontmatter={"id": "STORY-001", "title": "Story one", "status": "new", "type": "story"})

        result = _dry_run(project)

        assert "moves" in result, "dry-run result must have moves"
        move = _find_move(result, "STORY-001")
        assert move is not None, "plan must contain a move for STORY-001"
        new_id_num = int(re.match(r"ISSUE-(\d+)", move["new_id"]).group(1))
        assert new_id_num > 50, (
            f"STORY-001 new id number must be > 50 (past existing ISSUE-050); "
            f"got {move['new_id']!r} (number={new_id_num})"
        )

    def test_existing_issue_050_not_remapped(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/ISSUE-050-existing.md",
                  frontmatter={"id": "ISSUE-050", "title": "Existing", "status": "active", "type": "story"})
        _write_md(product, "backlog/stories/STORY-001-x.md",
                  frontmatter={"id": "STORY-001", "title": "Story one", "status": "new", "type": "story"})

        result = _dry_run(project)

        assert "id_map" in result, "dry-run result must have id_map"
        assert "ISSUE-050" not in result["id_map"], (
            "ISSUE-050 (already v4) must NOT appear in id_map — it is not remapped"
        )


# ===========================================================================
# Scenario: Reference edits are listed for old-id mentions
# ===========================================================================

class TestReferenceEditsListed:
    """
    Gherkin: EPIC-003.md body mentions "US-DM-002"; plan lists a reference-edit
    entry for that file replacing "US-DM-002" with its new id.
    """

    def test_reference_edit_entry_for_epic_mentioning_story(self, tmp_path):
        # Given "stories/EPIC-003/EPIC-003.md" whose body mentions "US-DM-002"
        # And "stories/EPIC-003/US-DM-002.md" with no frontmatter
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md",
                  body="See US-DM-002 for implementation details.\n")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")

        result = _dry_run(project)

        assert "reference_edits" in result, (
            "dry-run result must contain a 'reference_edits' key"
        )

    def test_reference_edit_names_correct_file(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md",
                  body="See US-DM-002 for implementation details.\n")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")

        result = _dry_run(project)

        edits = result.get("reference_edits", [])
        # There must be an edit entry for EPIC-003.md
        matching_edits = [
            e for e in edits
            if "EPIC-003.md" in e.get("file", "") and e.get("old_id") == "US-DM-002"
        ]
        assert matching_edits, (
            f"reference_edits must include an entry for 'stories/EPIC-003/EPIC-003.md' "
            f"replacing 'US-DM-002'; got reference_edits: {edits!r}"
        )

    def test_reference_edit_specifies_new_id(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md",
                  body="See US-DM-002 for implementation details.\n")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")

        result = _dry_run(project)

        edits = result.get("reference_edits", [])
        matching_edits = [
            e for e in edits
            if "EPIC-003.md" in e.get("file", "") and e.get("old_id") == "US-DM-002"
        ]
        assert matching_edits, "must have edit entry for US-DM-002 mention in EPIC-003.md"
        edit = matching_edits[0]
        # The replacement new_id must be the ISSUE-NNN assigned to US-DM-002
        assert "new_id" in edit, f"reference_edit must contain 'new_id'; got keys: {list(edit.keys())}"
        assert ISSUE_RE.match(edit["new_id"]), (
            f"reference_edit new_id must match ISSUE-\\d+; got {edit.get('new_id')!r}"
        )

    def test_reference_edit_has_required_fields(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md",
                  body="See US-DM-002 for details.\n")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")

        result = _dry_run(project)

        edits = result.get("reference_edits", [])
        for edit in edits:
            for field in ("file", "old_id", "new_id"):
                assert field in edit, (
                    f"each reference_edit must have field '{field}'; got keys: {list(edit.keys())}"
                )


# ===========================================================================
# Scenario: A migration map (old -> new) is included in the plan
# ===========================================================================

class TestMigrationMapIncluded:
    """
    Gherkin: id_map has an entry for every remapped item with original_id, new_id, source.
    """

    def test_id_map_key_exists(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-010-alpha.md",
                  frontmatter={"id": "STORY-010", "title": "Alpha", "status": "new", "type": "story"})

        result = _dry_run(project)

        assert "id_map" in result, "dry-run result must contain an 'id_map' key"

    def test_id_map_entry_has_required_fields(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-010-alpha.md",
                  frontmatter={"id": "STORY-010", "title": "Alpha", "status": "new", "type": "story"})

        result = _dry_run(project)

        id_map = result.get("id_map", {})
        assert "STORY-010" in id_map, "id_map must contain entry for STORY-010"
        entry = id_map["STORY-010"]
        # Each entry must have: new_id, source
        for field in ("new_id", "source"):
            assert field in entry, (
                f"id_map entry must have field '{field}'; got keys: {list(entry.keys())}"
            )

    def test_id_map_covers_all_remapped_items(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-010-alpha.md",
                  frontmatter={"id": "STORY-010", "title": "Alpha", "status": "new", "type": "story"})
        _write_md(product, "backlog/debt/DEBT-002-legacy-auth.md",
                  frontmatter={"id": "DEBT-002", "title": "Legacy auth", "status": "new", "type": "tech-debt"})
        _write_md(product, "BL-007-feature.md",
                  frontmatter={"id": "BL-007", "title": "Feature", "status": "new", "type": "story"})
        _write_md(product, "stories/EPIC-003/EPIC-003.md")
        _write_md(product, "stories/EPIC-003/US-DM-002.md")

        result = _dry_run(project)

        id_map = result.get("id_map", {})
        # Every item in moves that has a new_id different from legacy_id should be in id_map
        for move in result.get("moves", []):
            leg = move["legacy_id"]
            if move["new_id"] != leg:
                assert leg in id_map, (
                    f"id_map must contain entry for every remapped legacy_id; "
                    f"missing: {leg!r}"
                )

    def test_id_map_entry_source_path_correct(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-010-alpha.md",
                  frontmatter={"id": "STORY-010", "title": "Alpha", "status": "new", "type": "story"})

        result = _dry_run(project)

        id_map = result.get("id_map", {})
        assert "STORY-010" in id_map, "id_map must contain STORY-010"
        source = id_map["STORY-010"].get("source", "")
        # Source must reference the original file (product-base-relative or project-relative)
        assert "STORY-010" in source, (
            f"id_map['STORY-010']['source'] must reference the source file; got {source!r}"
        )


# ===========================================================================
# Scenario: Real duplicates are surfaced, backups are not blockers
# ===========================================================================

class TestRealDuplicatesSurfacedBackupsExcluded:
    """
    Gherkin: two real STORY-007 files flagged "decision required";
    backup file .bold-backup-* is absent from the plan.
    """

    def _make_duplicate_tree(self, tmp_path):
        project, product = _make_project(tmp_path)
        # Two real STORY-007 files
        _write_md(product, "backlog/stories/STORY-007-a.md",
                  frontmatter={"id": "STORY-007", "title": "Story seven a", "status": "new", "type": "story"})
        _write_md(product, "backlog/stories/STORY-007-b.md",
                  frontmatter={"id": "STORY-007", "title": "Story seven b", "status": "new", "type": "story"})
        # One bold-backup file (must not count)
        _write_md(product, "backlog/stories/STORY-007-a.bold-backup-1.md",
                  frontmatter={"id": "STORY-007", "title": "Story seven a", "status": "new", "type": "story"})
        return project, product

    def test_conflicts_key_exists(self, tmp_path):
        project, _ = self._make_duplicate_tree(tmp_path)

        result = _dry_run(project)

        assert "conflicts" in result, "dry-run result must contain a 'conflicts' key"

    def test_story_007_flagged_decision_required(self, tmp_path):
        project, _ = self._make_duplicate_tree(tmp_path)

        result = _dry_run(project)

        conflicts = result.get("conflicts", [])
        story_007_conflict = [c for c in conflicts if c.get("id") == "STORY-007"]
        assert story_007_conflict, (
            "STORY-007 must appear in conflicts as a real duplicate"
        )
        assert story_007_conflict[0].get("status") == "decision required", (
            f"STORY-007 conflict status must be 'decision required'; "
            f"got {story_007_conflict[0].get('status')!r}"
        )

    def test_backup_not_in_plan_moves(self, tmp_path):
        project, product = self._make_duplicate_tree(tmp_path)

        result = _dry_run(project)

        # The bold-backup file must not be in the plan's moves
        backup_path = "backlog/stories/STORY-007-a.bold-backup-1.md"
        for move in result.get("moves", []):
            assert backup_path not in move.get("source", ""), (
                f"backup file '{backup_path}' must NOT be part of the plan's moves"
            )

    def test_backup_not_in_conflicts_files_list(self, tmp_path):
        project, product = self._make_duplicate_tree(tmp_path)

        result = _dry_run(project)

        conflicts = result.get("conflicts", [])
        story_007_conflict = [c for c in conflicts if c.get("id") == "STORY-007"]
        if story_007_conflict:
            files = story_007_conflict[0].get("files", [])
            backup_path = "backlog/stories/STORY-007-a.bold-backup-1.md"
            assert not any(backup_path in f for f in files), (
                f"backup file must NOT appear in conflict files list; got {files!r}"
            )

    def test_conflict_entry_has_required_fields(self, tmp_path):
        project, _ = self._make_duplicate_tree(tmp_path)

        result = _dry_run(project)

        conflicts = result.get("conflicts", [])
        story_007_conflict = [c for c in conflicts if c.get("id") == "STORY-007"]
        assert story_007_conflict, "STORY-007 must be in conflicts"
        c = story_007_conflict[0]
        for field in ("id", "files", "status"):
            assert field in c, (
                f"conflict entry must have field '{field}'; got keys: {list(c.keys())}"
            )


# ===========================================================================
# Scenario: Low-confidence Tier B inferences are flagged
# ===========================================================================

class TestLowConfidenceTierBFlagged:
    """
    Gherkin: US-XX-005.md with no frontmatter and no H1 title ->
    flagged as low-confidence (tier B) in flags section.
    """

    def test_flags_key_exists(self, tmp_path):
        project, product = _make_project(tmp_path)
        # A US file with no frontmatter AND no H1 title
        target = product / "stories" / "EPIC-009" / "US-XX-005.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Some body text with no heading.\n", encoding="utf-8")

        result = _dry_run(project)

        assert "flags" in result, "dry-run result must contain a 'flags' key"

    def test_no_frontmatter_no_h1_flagged_low_confidence(self, tmp_path):
        # Given "stories/EPIC-009/US-XX-005.md" with no frontmatter and no H1 title
        project, product = _make_project(tmp_path)
        target = product / "stories" / "EPIC-009" / "US-XX-005.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("No heading here. Just raw text.\n", encoding="utf-8")

        result = _dry_run(project)

        flags = result.get("flags", [])
        us_flag = [f for f in flags if "US-XX-005" in f.get("id", "")]
        assert us_flag, (
            f"US-XX-005 (no frontmatter, no H1) must appear in flags; got flags: {flags!r}"
        )

    def test_low_confidence_entry_has_tier_b(self, tmp_path):
        project, product = _make_project(tmp_path)
        target = product / "stories" / "EPIC-009" / "US-XX-005.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("No heading here. Just raw text.\n", encoding="utf-8")

        result = _dry_run(project)

        flags = result.get("flags", [])
        us_flag = [f for f in flags if "US-XX-005" in f.get("id", "")]
        assert us_flag, "US-XX-005 must appear in flags"
        assert us_flag[0].get("tier") == "B", (
            f"low-confidence flag must have tier='B'; got {us_flag[0].get('tier')!r}"
        )

    def test_low_confidence_move_entry_has_tier_b(self, tmp_path):
        # Also: the corresponding move entry must have tier="B"
        project, product = _make_project(tmp_path)
        target = product / "stories" / "EPIC-009" / "US-XX-005.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("No heading here. Just raw text.\n", encoding="utf-8")

        result = _dry_run(project)

        move = _find_move(result, "US-XX-005")
        assert move is not None, "plan must contain a move for US-XX-005"
        assert move.get("tier") == "B", (
            f"US-XX-005 move.tier must be 'B' (low confidence); got {move.get('tier')!r}"
        )

    def test_flag_entry_has_required_fields(self, tmp_path):
        project, product = _make_project(tmp_path)
        target = product / "stories" / "EPIC-009" / "US-XX-005.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("No heading.\n", encoding="utf-8")

        result = _dry_run(project)

        flags = result.get("flags", [])
        us_flag = [f for f in flags if "US-XX-005" in f.get("id", "")]
        assert us_flag, "US-XX-005 must appear in flags"
        f = us_flag[0]
        for field in ("id", "reason", "tier"):
            assert field in f, (
                f"flag entry must have field '{field}'; got keys: {list(f.keys())}"
            )


# ===========================================================================
# Scenario: The dry-run writes nothing to the project tree
# ===========================================================================

class TestDryRunWritesNothing:
    """
    Gherkin: after the dry-run call, the product base is byte-for-byte identical
    to the snapshot taken before the call; no new files under the project
    except optionally under .sweetclaude/.
    """

    def _make_full_tree(self, tmp_path) -> tuple[Path, Path]:
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})
        _write_md(product, "backlog/debt/DEBT-001-creds.md",
                  frontmatter={"id": "DEBT-001", "title": "Remove creds", "status": "new", "type": "tech-debt"})
        _write_md(product, "BL-005-product-brief.md",
                  frontmatter={"id": "BL-005", "title": "Product brief", "status": "new", "type": "story"})
        _write_md(product, "stories/EPIC-003/EPIC-003.md")
        _write_md(product, "stories/EPIC-003/US-DM-002.md",
                  body="See US-DM-002 for details.\n")
        _write_md(product, "milestones/MS-001-core.md",
                  frontmatter={"id": "MS-001", "title": "Core", "status": "active", "type": "milestone"})
        return project, product

    def test_product_base_unchanged_after_dry_run(self, tmp_path):
        project, product = self._make_full_tree(tmp_path)

        # Snapshot every file under product base before
        before = _snapshot(product)

        _dry_run(project)

        # Snapshot every file under product base after
        after = _snapshot(product)

        # Check no files added or removed
        assert set(before.keys()) == set(after.keys()), (
            f"dry-run must not add or remove files in product base; "
            f"added: {set(after) - set(before)!r}, "
            f"removed: {set(before) - set(after)!r}"
        )

        # Check no file content changed
        for path in before:
            assert before[path] == after[path], (
                f"dry-run must not modify file {path!r}"
            )

    def test_no_new_files_outside_sweetclaude(self, tmp_path):
        project, product = self._make_full_tree(tmp_path)

        # Snapshot all files in project before
        before = _snapshot(project)

        _dry_run(project)

        after = _snapshot(project)

        sweetclaude_dir = str(project / ".sweetclaude")
        new_files = set(after.keys()) - set(before.keys())
        outside_sc = [f for f in new_files if not f.startswith(sweetclaude_dir)]
        assert not outside_sc, (
            f"dry-run must not create new files outside .sweetclaude/; "
            f"found: {outside_sc!r}"
        )

    def test_product_base_files_not_modified(self, tmp_path):
        project, product = self._make_full_tree(tmp_path)

        before = _snapshot(product)
        _dry_run(project)
        after = _snapshot(product)

        for path in set(before.keys()) & set(after.keys()):
            assert before[path] == after[path], (
                f"dry-run must leave all product-base files byte-for-byte identical; "
                f"changed: {path!r}"
            )


# ===========================================================================
# Additional contract tests — id_map structure
# ===========================================================================

class TestIdMapStructure:
    """
    Additional assertions on the shape and completeness of id_map.
    """

    def test_id_map_new_id_for_epic_preserved_number(self, tmp_path):
        project, product = _make_project(tmp_path)
        _write_md(product, "stories/EPIC-003/EPIC-003.md")

        result = _dry_run(project)

        id_map = result.get("id_map", {})
        assert "EPIC-003" in id_map, "id_map must contain EPIC-003"
        assert id_map["EPIC-003"]["new_id"] == "EP-003", (
            f"id_map['EPIC-003']['new_id'] must be 'EP-003'; got {id_map['EPIC-003'].get('new_id')!r}"
        )

    def test_id_map_story_new_id_matches_move_new_id(self, tmp_path):
        # The id_map and the moves list must be consistent
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        id_map = result.get("id_map", {})
        move = _find_move(result, "STORY-024")
        assert move is not None, "must have move for STORY-024"
        assert "STORY-024" in id_map, "id_map must have STORY-024"
        assert id_map["STORY-024"]["new_id"] == move["new_id"], (
            "id_map new_id and move new_id must agree for STORY-024"
        )

    def test_ok_and_dry_run_flags_present(self, tmp_path):
        # run_migration must return ok=True, dry_run=True in the result
        project, product = _make_project(tmp_path)
        _write_md(product, "backlog/stories/STORY-024-parallel-run.md",
                  frontmatter={"id": "STORY-024", "title": "Parallel run", "status": "new", "type": "story"})

        result = _dry_run(project)

        assert result.get("ok") is True, "run_migration dry-run must return ok=True"
        assert result.get("dry_run") is True, "run_migration must return dry_run=True"
