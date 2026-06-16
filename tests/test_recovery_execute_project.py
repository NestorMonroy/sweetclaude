import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import recovery.recover_project as recover_project
from recovery.recover_project import execute_project, resume_project, rollback_project
from recovery.recover_project import plan_project


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "syncog-layout"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "recovery" / "recover_project.py"


def _copy_syncog_fixture(tmp_path: Path) -> Path:
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
            # incomplete -> recovery_required (stabilize-without-migration), the
            # flow these recovery-lifecycle tests exercise. Post-S7 a "complete"
            # syncog routes to typed-legacy-migrate instead.
            "  migration_status: incomplete",
            "paths:",
            "  product_base: docs/product",
            "",
        ]),
        encoding="utf-8",
    )
    return project


def _product_snapshot(project: Path) -> dict[str, str]:
    product = project / "docs" / "product"
    return {
        path.relative_to(project).as_posix(): path.read_text(encoding="utf-8")
        for path in product.rglob("*")
        if path.is_file()
    }


def _state(project: Path) -> dict:
    return yaml.safe_load(
        (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text(
            encoding="utf-8"
        )
    )


def _approval_receipt_from_plan(project: Path, plan: dict, **overrides) -> Path:
    receipt = dict(plan["mutation_plan"]["approval_receipt_template"])
    receipt["approved"] = True
    for key, value in overrides.items():
        if key == "context":
            context = dict(receipt["context"])
            context.update(value)
            receipt["context"] = context
        else:
            receipt[key] = value
    path = project / ".sweetclaude" / "state" / "recovery-approval-receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_execute_requires_explicit_approval(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    with pytest.raises(PermissionError, match="--approve"):
        execute_project(project)


def test_recovery_plan_emits_mutation_lifecycle_plan(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    plan = plan_project(project)

    mutation_plan = plan["mutation_plan"]
    assert mutation_plan["status"] == "approval-required"
    assert mutation_plan["approval_receipt_template"]["approved"] is False
    assert mutation_plan["declared_write_set"]
    assert ".sweetclaude/state/recovery-runs/" in mutation_plan["declared_write_set"]
    assert ".sweetclaude/state" in mutation_plan["declared_blast_radius"]
    assert "docs/product" in mutation_plan["declared_blast_radius"]
    assert any(check["id"] == "verification" for check in mutation_plan["postconditions"])


def test_execute_requires_approval_receipt_before_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    before_product = _product_snapshot(project)

    with pytest.raises(PermissionError, match="approval receipt"):
        execute_project(project, approve=True)

    assert _product_snapshot(project) == before_product
    assert not (project / ".sweetclaude" / "state" / "recovery-runs").exists()


def test_execute_rejects_stale_approval_receipt_before_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    plan = plan_project(project)
    receipt = _approval_receipt_from_plan(project, plan, write_set_hash="stale-write-set")

    with pytest.raises(ValueError, match="write_set_hash mismatch"):
        execute_project(project, approve=True, approval_receipt=receipt)

    assert not (project / ".sweetclaude" / "state" / "recovery-runs").exists()


def test_execute_rejects_approval_when_operation_value_changes_before_writes(tmp_path, monkeypatch):
    project = _copy_syncog_fixture(tmp_path)
    plan = plan_project(project)
    receipt = _approval_receipt_from_plan(project, plan)
    original_state_operations = recover_project._state_operations

    def changed_state_operations(project_arg, diagnosis):
        operations = original_state_operations(project_arg, diagnosis)
        for operation in operations:
            if operation["id"] == "record-taxonomy-recovery-state":
                operation["planned_value"] = "changed-after-approval"
        return operations

    monkeypatch.setattr(recover_project, "_state_operations", changed_state_operations)

    with pytest.raises(ValueError, match="plan_hash mismatch"):
        execute_project(project, approve=True, approval_receipt=receipt)

    assert not (project / ".sweetclaude" / "state" / "recovery-runs").exists()


def test_execute_snapshots_applies_manifest_and_verifies_without_product_changes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text(
        json.dumps({"category": "migration_currency", "recommendation": "migrate"}),
        encoding="utf-8",
    )
    before_product = _product_snapshot(project)
    receipt = _approval_receipt_from_plan(project, plan_project(project))

    result = execute_project(project, approve=True, approval_receipt=receipt)

    assert result["status"] == "succeeded", result["verification"]
    lifecycle = result["mutation_lifecycle"]
    assert lifecycle["status"] == "pass"
    assert lifecycle["approval"]["status"] == "pass"
    assert lifecycle["write_set_validation"]["status"] == "pass"
    assert lifecycle["snapshot_scope_validation"]["status"] == "pass"
    assert lifecycle["postcondition_validation"]["status"] == "pass"
    assert Path(result["run_dir"]).is_dir()
    assert Path(result["snapshot"]["path"]).is_file()
    assert Path(result["report_path"]).is_file()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "SweetClaude Recovery Report" in report
    assert "record-taxonomy-recovery-state" in report
    assert "doctor-migration-scan-safe" in report
    assert "Rollback command" in report
    assert ".sweetclaude/state/recovery-runs/" in report
    assert result["snapshot"]["file_count"] >= len(before_product) + 2
    assert all(check["status"] == "passed" for check in result["verification"])
    check_ids = {check["id"] for check in result["verification"]}
    assert {
        "doctor-migration-scan-safe",
        "migrate-orphan-scan-consistent",
        "update-skill-taxonomy-prompt-disabled",
        "fix-sweetclaude-delegates-to-doctor",
        "maintenance-entrypoints-safe",
    }.issubset(check_ids)
    assert _product_snapshot(project) == before_product
    assert not pending.exists()

    state = _state(project)
    # Stabilizing an incomplete project records the taxonomy recovery state but
    # does not itself normalize migration_status (the set-migration-status op
    # only fires for the stale-complete case, which now routes to migration).
    assert state["framework"]["migration_status"] == "incomplete"
    assert state["recovery"]["taxonomy"]["status"] == "stabilized-without-migration"
    assert state["recovery"]["taxonomy"]["blind_taxonomy_migration_allowed"] is False


def test_rollback_restores_snapshot_after_execute(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text('{"recommendation":"migrate"}\n', encoding="utf-8")
    original_state = (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text(
        encoding="utf-8"
    )
    original_prompt = pending.read_text(encoding="utf-8")

    receipt = _approval_receipt_from_plan(project, plan_project(project))
    result = execute_project(project, approve=True, approval_receipt=receipt)
    rollback = rollback_project(result["run_dir"])

    assert rollback["status"] == "rolled_back"
    assert rollback["restore_proof"]["status"] == "pass"
    assert rollback["restore_proof"]["method"] == "command"
    assert Path(rollback["report_path"]).is_file()
    assert "Rollback Status" in Path(rollback["report_path"]).read_text(
        encoding="utf-8"
    )
    assert (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text(
        encoding="utf-8"
    ) == original_state
    assert pending.read_text(encoding="utf-8") == original_prompt


def test_resume_continues_interrupted_run_from_manifest(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text(
        json.dumps({"category": "migration_currency", "recommendation": "migrate"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="injected failure"):
        receipt = _approval_receipt_from_plan(project, plan_project(project))
        execute_project(project, approve=True, approval_receipt=receipt, fail_after_operations=1)

    run_dirs = sorted((project / ".sweetclaude" / "state" / "recovery-runs").iterdir())
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "execution-manifest.json").read_text(
        encoding="utf-8"
    ))
    assert manifest["status"] == "failed"
    assert [operation["id"] for operation in manifest["operations"]] == [
        "record-taxonomy-recovery-state"
    ]

    resumed = resume_project(run_dirs[0])

    assert resumed["command"] == "resume"
    assert resumed["status"] == "succeeded", resumed["verification"]
    assert Path(resumed["report_path"]).is_file()
    assert resumed["resume_count"] == 1
    assert [operation["id"] for operation in resumed["operations"]] == [
        "record-taxonomy-recovery-state",
        "delete-pending-doctor-prompt-1",
    ]
    assert not pending.exists()
    assert _state(project)["recovery"]["taxonomy"]["status"] == (
        "stabilized-without-migration"
    )


def test_resume_stops_when_repair_loop_budget_exhausted(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    receipt = _approval_receipt_from_plan(project, plan_project(project))
    with pytest.raises(RuntimeError, match="injected failure"):
        execute_project(project, approve=True, approval_receipt=receipt, fail_after_operations=1)

    run_dir = next((project / ".sweetclaude" / "state" / "recovery-runs").iterdir())
    manifest_path = run_dir / "execution-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["resume_count"] = 3
    manifest["max_resume_attempts"] = 3
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    stopped = resume_project(run_dir)

    assert stopped["status"] == "stopped"
    assert stopped["repair_loop"]["stop"] is True
    assert stopped["repair_loop"]["reason"] == "attempt-budget-exhausted"


def test_resume_refuses_interrupted_run_when_snapshot_is_missing(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    with pytest.raises(RuntimeError, match="injected failure"):
        receipt = _approval_receipt_from_plan(project, plan_project(project))
        execute_project(project, approve=True, approval_receipt=receipt, fail_after_operations=1)

    run_dir = next((project / ".sweetclaude" / "state" / "recovery-runs").iterdir())
    manifest = json.loads((run_dir / "execution-manifest.json").read_text(
        encoding="utf-8"
    ))
    Path(manifest["snapshot"]["path"]).unlink()

    with pytest.raises(FileNotFoundError, match="snapshot not found"):
        resume_project(run_dir)


def test_recover_project_cli_execute_requires_approval(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "execute",
            "--project-dir",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--approve" in completed.stderr


def test_recover_project_cli_execute_and_rollback(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    receipt = _approval_receipt_from_plan(project, plan_project(project))
    execute = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "execute",
            "--project-dir",
            str(project),
            "--approve",
            "--approval-receipt",
            str(receipt),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert execute.returncode == 0
    executed = json.loads(execute.stdout)
    assert executed["status"] == "succeeded", executed["verification"]
    assert "files" not in executed["snapshot"]
    assert executed["snapshot"]["files_omitted_from_cli"] > 0

    rollback = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "rollback",
            "--run-dir",
            executed["run_dir"],
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert rollback.returncode == 0
    rolled_back = json.loads(rollback.stdout)
    assert rolled_back["status"] == "rolled_back"


def test_recover_project_cli_resume_is_idempotent_after_success(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    receipt = _approval_receipt_from_plan(project, plan_project(project))
    executed = execute_project(project, approve=True, approval_receipt=receipt)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "resume",
            "--run-dir",
            executed["run_dir"],
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    resumed = json.loads(completed.stdout)
    assert resumed["command"] == "resume"
    assert resumed["resume_status"] == "already_succeeded"
