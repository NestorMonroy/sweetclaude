import json
import subprocess
import sys
from pathlib import Path

import pytest

from recovery.characterize_project import characterize_project


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "typed-product-layout"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "recovery" / "characterize_project.py"


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_characterizes_typed_product_layout_without_writes():
    before = _file_snapshot(FIXTURE_ROOT)

    result = characterize_project(FIXTURE_ROOT)

    assert _file_snapshot(FIXTURE_ROOT) == before
    assert Path(result["product_base"]) == (FIXTURE_ROOT / "docs" / "product").resolve()
    assert result["product_base_exists"] is True
    assert result["counts"]["product_files"] == 9
    assert result["counts"]["markdown_files"] == 9
    assert result["counts"]["prefixes"] == {
        "BL": 1,
        "BUG": 1,
        "CHORE": 1,
        "DEBT": 2,
        "EP": 1,
        "STORY": 1,
    }
    assert result["counts"]["typed_backlog_dirs"] == {
        "bugs": 1,
        "chores": 1,
        "debt": 2,
        "stories": 1,
    }
    assert result["frontmatter"]["present"] == 7
    assert result["frontmatter"]["missing"] == 2
    assert result["layout"]["has_backlog"] is True
    assert result["layout"]["has_backlog_done_dir"] is True
    assert result["layout"]["has_typed_backlog_dirs"] is True
    assert result["layout"]["has_epics"] is True
    assert result["layout"]["has_flat_backlog_items"] is False

    unsupported_codes = {
        pattern["code"] for pattern in result["layout"]["unsupported_patterns"]
    }
    assert unsupported_codes == {"typed-backlog-prefixes"}

    duplicates = {entry["id"]: entry["files"] for entry in result["ids"]["duplicates"]}
    assert duplicates == {
        "DEBT-001": [
            "backlog/debt/DEBT-001-duplicate-debt.md",
            "backlog/debt/DEBT-001-first-debt.md",
        ]
    }
    assert result["migration_risk"] == {
        "requires_manual_plan": True,
        "taxonomy_candidate_count": 6,
        "reasons": ["typed-backlog-prefixes", "duplicate-work-item-ids"],
    }


def test_cli_emits_json_for_typed_product_layout_fixture():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--project-dir",
            str(FIXTURE_ROOT),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["schema_version"] == 1
    assert result["migration_risk"]["requires_manual_plan"] is True
    assert "typed-backlog-prefixes" in result["migration_risk"]["reasons"]


def test_product_base_cannot_escape_project_root(tmp_path):
    project = tmp_path / "project"
    config_dir = project / ".sweetclaude"
    config_dir.mkdir(parents=True)
    (config_dir / "artifact-privacy.yaml").write_text(
        "product:\n  base_path: ../outside\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="product base escapes project root"):
        characterize_project(project)
