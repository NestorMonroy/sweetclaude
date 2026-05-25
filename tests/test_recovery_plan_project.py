import json
import shutil
import subprocess
import sys
from pathlib import Path

from recovery.recover_project import plan_project


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "typed-product-layout"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "recovery" / "recover_project.py"


def _copy_typed_product_fixture(tmp_path: Path, migration_status: str = "complete") -> Path:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)

    state_dir = project / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True)
    (project / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "schema_version: 1\n"
        "categories:\n"
        "  product:\n"
        "    privacy: private\n"
        "    base_path: docs/product\n",
        encoding="utf-8",
    )
    (state_dir / "sweetclaude.yaml").write_text(
        "\n".join([
            "framework:",
            "  installed_version: 4.1.1-beta",
            f"  migration_status: {migration_status}",
            "paths:",
            "  product_base: docs/product",
            "",
        ]),
        encoding="utf-8",
    )
    return project


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_plan_stabilizes_typed_product_state_without_writes_or_product_moves(tmp_path):
    project = _copy_typed_product_fixture(tmp_path)
    before = _file_snapshot(project)

    plan = plan_project(project)

    assert _file_snapshot(project) == before
    assert plan["command"] == "plan"
    assert plan["plan_status"] == "planned"
    assert plan["recovery_route"] == "stabilize-without-migration"
    assert plan["mutating_actions_allowed"] is False
    assert plan["execute_requires_approval"] is True
    assert plan["requires_snapshot_before_execute"] is True
    assert plan["can_execute_after_snapshot"] is True
    assert plan["snapshot"]["required"] is True
    assert plan["snapshot"]["paths"] == [
        ".sweetclaude/artifact-privacy.yaml",
        ".sweetclaude/state",
        "docs/product",
    ]

    operation_ids = {operation["id"] for operation in plan["operations"]}
    assert operation_ids == {
        "record-taxonomy-recovery-state",
        "set-migration-status-deferred",
    }
    assert all(
        not operation["target"].startswith("docs/product")
        for operation in plan["operations"]
    )

    status_operation = next(
        operation
        for operation in plan["operations"]
        if operation["id"] == "set-migration-status-deferred"
    )
    assert status_operation["action"] == "yaml-set"
    assert status_operation["target"] == ".sweetclaude/state/sweetclaude.yaml"
    assert status_operation["yaml_path"] == ["framework", "migration_status"]
    assert status_operation["current_value"] == "complete"
    assert status_operation["planned_value"] == "deferred"
    assert status_operation["rollback"]["value"] == "complete"

    blocked = {action["id"]: action for action in plan["blocked_actions"]}
    assert set(blocked) == {"taxonomy-migration"}
    assert "layout-specific migration manifest" in blocked["taxonomy-migration"]["reason"]


def test_plan_deletes_pending_doctor_prompt_by_manifest(tmp_path):
    project = _copy_typed_product_fixture(tmp_path, migration_status="deferred")
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text(
        json.dumps({"category": "migration_currency", "recommendation": "migrate"}),
        encoding="utf-8",
    )

    plan = plan_project(project)

    prompt_operation = next(
        operation
        for operation in plan["operations"]
        if operation["id"] == "delete-pending-doctor-prompt-1"
    )
    assert prompt_operation["action"] == "delete-file"
    assert prompt_operation["target"] == ".sweetclaude/state/doctor-prompt-pending.json"
    assert prompt_operation["rollback"]["action"] == "restore-file-from-snapshot"


def test_plan_noops_for_simple_current_layout(tmp_path):
    project = tmp_path / "project"
    backlog = project / "docs" / "product" / "backlog"
    backlog.mkdir(parents=True)
    (backlog / "ISSUE-001-current.md").write_text(
        "---\n"
        "id: ISSUE-001\n"
        "title: Current item\n"
        "status: new\n"
        "type: enhancement\n"
        "---\n"
        "\n"
        "Current taxonomy item.\n",
        encoding="utf-8",
    )

    plan = plan_project(project)

    assert plan["plan_status"] == "no-op"
    assert plan["operations"] == []
    assert plan["snapshot"]["required"] is False
    assert plan["can_execute_after_snapshot"] is False


def test_recover_project_cli_plan_emits_manifest_json(tmp_path):
    project = _copy_typed_product_fixture(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "plan",
            "--project-dir",
            str(project),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    plan = json.loads(completed.stdout)
    assert plan["command"] == "plan"
    assert plan["plan_id"].startswith("recovery-plan-")
    assert plan["plan_status"] == "planned"
    assert plan["recovery_route"] == "stabilize-without-migration"
