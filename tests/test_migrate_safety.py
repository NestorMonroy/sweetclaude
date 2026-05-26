import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate" / "migrate-v3-to-v4.py"
SYNCOG_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "syncog-layout"


def _copy_syncog_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "syncog-layout"
    shutil.copytree(SYNCOG_FIXTURE, project)
    state_dir = project / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True)
    (project / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "categories:\n"
        "  product:\n"
        "    base_path: docs/product\n",
        encoding="utf-8",
    )
    (state_dir / "sweetclaude.yaml").write_text(
        "framework:\n"
        "  installed_version: 4.1.3-beta\n"
        "  migration_status: complete\n"
        "paths:\n"
        "  product_base: docs/product\n",
        encoding="utf-8",
    )
    return project


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_migrator(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--project-dir", str(project)],
        check=False,
        capture_output=True,
        text=True,
    )


def _blocking_codes(preflight: dict) -> set[str]:
    return {factor["code"] for factor in preflight.get("blocking_factors", [])}


def test_migrate_preflight_blocks_unsupported_typed_layout_without_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    before = _file_snapshot(project)

    result = _run_migrator(project, "preflight")

    assert result.returncode == 0, result.stderr
    preflight = json.loads(result.stdout)
    assert preflight["status"] == "blocked"
    assert preflight["migrate_allowed"] is False
    assert preflight["flat_bl_count"] == 0
    assert preflight["typed_old_prefix_count"] == 5
    assert {
        "unsupported-typed-backlog-layout",
        "duplicate-work-item-ids",
    }.issubset(_blocking_codes(preflight))
    assert _file_snapshot(project) == before


def test_migrate_execute_blocks_unsupported_typed_layout_before_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    before = _file_snapshot(project)

    result = _run_migrator(project, "execute", "--include-done")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["error"] == "migration-blocked"
    assert "unsupported-typed-backlog-layout" in _blocking_codes(payload["preflight"])
    assert _file_snapshot(project) == before
    assert not (project / ".sweetclaude" / "product" / "backlog" / "MIGRATION-MAP.md").exists()
