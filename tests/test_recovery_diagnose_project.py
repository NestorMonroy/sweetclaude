import json
import shutil
import subprocess
import sys
from pathlib import Path

from recovery.recover_project import diagnose_project, guard_project


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "syncog-layout"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "recovery" / "recover_project.py"


def _copy_syncog_fixture(tmp_path: Path, migration_status: str = "complete") -> Path:
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


def test_diagnose_routes_syncog_state_to_recovery_plan_without_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    before = _file_snapshot(project)

    result = diagnose_project(project)

    assert _file_snapshot(project) == before
    assert result["mutating_actions_allowed"] is False
    assert result["can_plan_recovery"] is True
    assert result["requires_snapshot_before_execute"] is True
    assert result["recovery_route"] == "stabilize-without-migration"
    assert result["sweetclaude_state"]["migration_status"] == "complete"

    assert set(result["failure_class_codes"]) == {
        "unsupported-typed-backlog-layout",
        "stale-migration-complete-state",
    }
    blocking_codes = {factor["code"] for factor in result["blocking_factors"]}
    assert blocking_codes == {"duplicate-work-item-ids"}

    action_ids = {action["id"] for action in result["recommended_actions"]}
    assert action_ids == {
        "snapshot-before-recovery",
        "plan-stabilize-without-taxonomy-migration",
        "verify-maintenance-entrypoints",
    }


def test_diagnose_detects_pending_doctor_prompt_as_recoverable(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text(
        json.dumps({"category": "migration_currency", "recommendation": "migrate"}),
        encoding="utf-8",
    )

    result = diagnose_project(project)

    assert "bad-doctor-migration-recommendation" in result["failure_class_codes"]
    assert ".sweetclaude/state/doctor-prompt-pending.json" in result["pending_doctor_prompts"]
    assert result["can_plan_recovery"] is True


def test_diagnose_ignores_normal_time_based_doctor_prompt_after_stabilization(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        "\n".join([
            "framework:",
            "  installed_version: 4.1.1-beta",
            "  migration_status: deferred",
            "paths:",
            "  product_base: docs/product",
            "recovery:",
            "  taxonomy:",
            "    status: stabilized-without-migration",
            "    accepted_layout: typed-backlog-prefixes",
            "    migration_required: false",
            "    blind_taxonomy_migration_allowed: false",
            "",
        ]),
        encoding="utf-8",
    )
    pending = project / ".sweetclaude" / "state" / "doctor-prompt-pending.json"
    pending.write_text(
        json.dumps({"trigger": "time", "created_at": "2026-05-25T04:23:10+00:00"}),
        encoding="utf-8",
    )

    result = diagnose_project(project)
    guard = guard_project(project)

    assert result["pending_doctor_prompts"] == []
    assert "bad-doctor-migration-recommendation" not in result["failure_class_codes"]
    assert result["recovery_route"] == "no-recovery-needed"
    assert guard["status"] == "compatibility-mode"
    assert guard["project_shape"] == "accepted_legacy_taxonomy"
    assert guard["migrate_allowed"] is False


def test_diagnose_reports_no_recovery_needed_after_stabilization(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        "\n".join([
            "framework:",
            "  installed_version: 4.1.1-beta",
            "  migration_status: deferred",
            "paths:",
            "  product_base: docs/product",
            "recovery:",
            "  taxonomy:",
            "    status: stabilized-without-migration",
            "    accepted_layout: typed-backlog-prefixes",
            "    migration_required: false",
            "    blind_taxonomy_migration_allowed: false",
            "",
        ]),
        encoding="utf-8",
    )

    result = diagnose_project(project)

    assert result["failure_classes"] == []
    assert result["blocking_factors"] == []
    assert result["can_plan_recovery"] is False
    assert result["recovery_route"] == "no-recovery-needed"
    assert result["sweetclaude_state"]["taxonomy_recovery_status"] == (
        "stabilized-without-migration"
    )


def test_guard_routes_unstable_legacy_layout_to_recover(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    result = guard_project(project)

    assert result["command"] == "guard"
    assert result["status"] == "run-recover"
    assert result["project_shape"] == "recovery_required"
    assert result["migrate_allowed"] is False
    assert result["recovery_route"] == "stabilize-without-migration"
    assert "unsupported-typed-backlog-layout" in result["failure_class_codes"]
    assert "/sweetclaude:recover" in result["message"]


def test_guard_keeps_recovered_legacy_layout_in_compatibility_mode(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        "\n".join([
            "framework:",
            "  installed_version: 4.1.1-beta",
            "  migration_status: deferred",
            "paths:",
            "  product_base: docs/product",
            "recovery:",
            "  taxonomy:",
            "    status: stabilized-without-migration",
            "    accepted_layout: typed-backlog-prefixes",
            "    migration_required: false",
            "    blind_taxonomy_migration_allowed: false",
            "",
        ]),
        encoding="utf-8",
    )

    result = guard_project(project)

    assert result["status"] == "compatibility-mode"
    assert result["project_shape"] == "accepted_legacy_taxonomy"
    assert result["migrate_allowed"] is False
    assert result["recovery_route"] == "no-recovery-needed"
    assert result["taxonomy_recovery_status"] == "stabilized-without-migration"


def test_diagnose_malformed_sweetclaude_state_fails_closed_without_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text("framework:\n  migration_status: [\n", encoding="utf-8")
    before = _file_snapshot(project)

    result = diagnose_project(project)

    assert _file_snapshot(project) == before
    assert result["can_plan_recovery"] is False
    assert result["recovery_route"] == "manual-escalation"
    blocking_codes = {factor["code"] for factor in result["blocking_factors"]}
    assert "sweetclaude-state-parse-error" in blocking_codes
    assert result["sweetclaude_state"]["parse_error"]


def test_diagnose_reports_no_recovery_needed_for_simple_current_layout(tmp_path):
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

    result = diagnose_project(project)
    guard = guard_project(project)

    assert result["failure_classes"] == []
    assert result["blocking_factors"] == []
    assert result["can_plan_recovery"] is False
    assert result["recovery_route"] == "no-recovery-needed"
    assert guard["project_shape"] == "current_layout"


def test_guard_does_not_call_non_bl_old_prefixes_flat_bl_backlog(tmp_path):
    project = tmp_path / "project"
    backlog = project / "docs" / "product" / "backlog"
    backlog.mkdir(parents=True)
    (backlog / "STORY-001-old-story.md").write_text(
        "---\n"
        "id: STORY-001\n"
        "title: Old story\n"
        "status: new\n"
        "type: story\n"
        "---\n\n"
        "Old story taxonomy item.\n",
        encoding="utf-8",
    )

    guard = guard_project(project)

    assert guard["status"] == "manual-review"
    assert guard["project_shape"] == "manual_escalation"
    assert guard["migrate_allowed"] is False


def test_recover_project_cli_diagnose_emits_json(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "diagnose",
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
    result = json.loads(completed.stdout)
    assert result["command"] == "diagnose"
    assert result["recovery_route"] == "stabilize-without-migration"
    assert "unsupported-typed-backlog-layout" in result["failure_class_codes"]


def test_recover_project_cli_without_subcommand_defaults_to_read_only_diagnosis(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["command"] == "diagnose"
    assert result["mutating_actions_allowed"] is False
    assert result["recovery_route"] == "stabilize-without-migration"


def test_recover_project_cli_guard_emits_json(tmp_path):
    project = _copy_syncog_fixture(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "guard",
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
    result = json.loads(completed.stdout)
    assert result["command"] == "guard"
    assert result["status"] == "run-recover"
    assert result["migrate_allowed"] is False
