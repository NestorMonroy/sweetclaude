"""WI-017 S8 — end-to-end / completeness tests.

These cover shapes the synthetic S2/S3 fixtures missed but the real
llm-session-harness corpus exposed: nested `done/` subdirs inside typed backlog
dirs, and US-* stories nested under BL-NNN dirs. The migration must plan moves
for ALL legacy work items so the project ends up fully v4 (no typed-legacy
shape left).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate.migrate_taxonomy import run_migration  # noqa: E402
from recovery.characterize_project import characterize_project  # noqa: E402


def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    project = tmp_path / "proj"
    for rel, body in files.items():
        p = project / "docs" / "product" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    state = project / ".sweetclaude" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "sweetclaude.yaml").write_text(
        "framework:\n  installed_version: 4.1.4-beta\n  migration_status: complete\n"
        "paths:\n  product_base: docs/product\n",
        encoding="utf-8",
    )
    (project / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "schema_version: 1\ncategories:\n  product:\n    base_path: docs/product\n",
        encoding="utf-8",
    )
    return project


def _story(item_id: str, status: str = "new") -> str:
    return (
        f"---\nid: {item_id}\ntitle: {item_id} title\ntype: story\n"
        f"status: {status}\n---\n\nBody for {item_id}.\n"
    )


def test_plan_covers_done_subdir_inside_typed_backlog(tmp_path):
    project = _make_project(tmp_path, {
        "backlog/stories/STORY-001-active.md": _story("STORY-001"),
        "backlog/stories/done/STORY-002-finished.md": _story("STORY-002", "done"),
    })
    result = run_migration(project, dry_run=True)
    assert result["ok"] is True
    legacy_ids = {m["legacy_id"] for m in result["moves"]}
    assert "STORY-001" in legacy_ids
    # The completed story in the nested done/ subdir must also be planned.
    assert "STORY-002" in legacy_ids


def test_plan_covers_us_stories_under_bl_dir(tmp_path):
    project = _make_project(tmp_path, {
        "stories/BL-027/US-BL027-002-judge-fields.md": "# US-BL027-002\n\nA story under a BL dir.\n",
    })
    result = run_migration(project, dry_run=True)
    assert result["ok"] is True
    legacy_ids = {m["legacy_id"] for m in result["moves"]}
    assert any(lid.startswith("US-BL027-002") for lid in legacy_ids)


def test_versioned_draft_doc_with_work_item_prefix_is_document(tmp_path):
    project = _make_project(tmp_path, {
        "BL-005-product-brief-draft-v1.0-20260511.md": "# Product brief\n\nDraft.\n",
        "BL-005-prd-draft-v1.0-20260511.md": "# PRD\n\nDraft.\n",
        "backlog/stories/STORY-007-real-feature.md": _story("STORY-007"),
        # The caucus rule still holds: a work item with doc keywords but no
        # versioned/dated draft signature stays a work item.
        "backlog/ISSUE-001-prd-brief.md": (
            "---\nid: ISSUE-001\ntitle: x\ntype: bug-fix\nstatus: new\n---\n"
        ),
    })
    result = characterize_project(project)
    docs = result["documents"]["supporting"]
    assert "BL-005-product-brief-draft-v1.0-20260511.md" in docs
    assert "BL-005-prd-draft-v1.0-20260511.md" in docs
    # The versioned-draft BL files must NOT be counted as BL work items.
    assert result["counts"]["prefixes"].get("BL", 0) == 0
    assert result["counts"]["prefixes"].get("STORY", 0) == 1
    # ISSUE-001-prd-brief.md (no version/date) stays a work item, not a document.
    assert "backlog/ISSUE-001-prd-brief.md" not in docs
    assert result["counts"]["prefixes"].get("ISSUE", 0) == 1


def test_migrating_done_subdir_leaves_no_typed_backlog(tmp_path):
    project = _make_project(tmp_path, {
        "backlog/stories/STORY-001-active.md": _story("STORY-001"),
        "backlog/stories/done/STORY-002-finished.md": _story("STORY-002", "done"),
    })
    run_migration(project, dry_run=False)
    leftover = list((project / "docs" / "product" / "backlog" / "stories").rglob("STORY-*.md"))
    leftover = [p for p in leftover if ".bold-backup-" not in p.name]
    assert leftover == [], f"old STORY files remain after migration: {leftover}"
