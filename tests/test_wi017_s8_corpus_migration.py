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


def test_migrating_done_subdir_leaves_no_typed_backlog(tmp_path):
    project = _make_project(tmp_path, {
        "backlog/stories/STORY-001-active.md": _story("STORY-001"),
        "backlog/stories/done/STORY-002-finished.md": _story("STORY-002", "done"),
    })
    run_migration(project, dry_run=False)
    leftover = list((project / "docs" / "product" / "backlog" / "stories").rglob("STORY-*.md"))
    leftover = [p for p in leftover if ".bold-backup-" not in p.name]
    assert leftover == [], f"old STORY files remain after migration: {leftover}"
