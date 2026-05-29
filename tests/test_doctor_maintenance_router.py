import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
SYNCOG_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "syncog-layout"
MIGRATE_SMOKE = REPO_ROOT / "tests" / "fixtures" / "migrate-smoke"


def _copy_syncog_fixture(tmp_path: Path, migration_status: str = "complete") -> Path:
    project = tmp_path / "syncog"
    shutil.copytree(SYNCOG_FIXTURE, project)
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
            "  installed_version: 4.1.4-beta",
            f"  migration_status: {migration_status}",
            "paths:",
            "  product_base: docs/product",
            "",
        ]),
        encoding="utf-8",
    )
    return project


def _copy_flat_bl_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "flat-bl"
    shutil.copytree(MIGRATE_SMOKE, project)
    return project


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _doctor_scan(project: Path, category: str | None = "migration_currency") -> dict:
    command = [
        sys.executable,
        str(DOCTOR),
        "scan",
        "--project-dir",
        str(project),
    ]
    if category:
        command.extend(["--category", category])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _doctor_route(project: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(DOCTOR),
            "maintenance-route",
            "--project-dir",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_doctor_maintenance_route_command_emits_compact_route_without_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\nrecovery:\n"
        + "  taxonomy:\n"
        + "    status: stabilized-without-migration\n"
        + "    migration_required: false\n"
        + "    blind_taxonomy_migration_allowed: false\n",
        encoding="utf-8",
    )
    before = _file_snapshot(project)

    result = _doctor_route(project)

    assert _file_snapshot(project) == before
    assert "findings" not in result
    route = result["maintenance_route"]
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["mutates_project"] is False
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert result["project_state_summary"]["product_base"].endswith("docs/product")


def test_doctor_routes_recoverable_project_to_safe_recovery_without_writes(tmp_path):
    project = _copy_syncog_fixture(tmp_path)
    before = _file_snapshot(project)

    scan = _doctor_scan(project)

    assert _file_snapshot(project) == before
    route = scan["maintenance_route"]
    assert route["doctor_front_door"] is True
    assert route["status"] == "recovery-available"
    assert route["primary_action"]["label"] == "Run safe recovery"
    assert route["primary_action"]["capability_id"] == (
        "recover.stabilize_without_migration"
    )
    assert route["primary_action"]["delegate_skill"] == "sweetclaude:recover"
    assert route["primary_action"]["requires_approval"] is True
    assert route["primary_action"]["supported_project_shapes"] == ["recovery_required"]
    assert "snapshot" in route["primary_action"]["safety_contract"]
    assert route["guard"]["status"] == "run-recover"


def test_doctor_routes_accepted_legacy_layout_to_compatibility_mode(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\nrecovery:\n"
        + "  taxonomy:\n"
        + "    status: stabilized-without-migration\n"
        + "    migration_required: false\n"
        + "    blind_taxonomy_migration_allowed: false\n",
        encoding="utf-8",
    )

    scan = _doctor_scan(project)

    route = scan["maintenance_route"]
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["label"] == "Continue in compatibility mode"
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert route["primary_action"]["mutates_project"] is False
    assert route["guard"]["migrate_allowed"] is False
    assert route["blocked_capabilities"][0]["capability_id"] == (
        "migrate.typed_legacy_backlog"
    )


def test_doctor_compatibility_mode_collapses_accepted_legacy_taxonomy_noise(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\nrecovery:\n"
        + "  taxonomy:\n"
        + "    status: stabilized-without-migration\n"
        + "    migration_required: false\n"
        + "    blind_taxonomy_migration_allowed: false\n",
        encoding="utf-8",
    )
    (project / "docs/product/backlog/bugs/BUG-001-example-bug.md").write_text(
        "---\n"
        "id: BUG-001\n"
        "title: Example bug\n"
        "type: bug\n"
        "status: new\n"
        "created: 2026-05-25T00:00:00+00:00\n"
        "---\n\n"
        "Legacy bug fixture.\n",
        encoding="utf-8",
    )
    for path in [
        project / "docs/product/backlog/debt/DEBT-001-first-debt.md",
        project / "docs/product/backlog/debt/DEBT-001-duplicate-debt.md",
    ]:
        path.write_text(
            "---\n"
            "id: DEBT-001\n"
            "title: Duplicate debt fixture\n"
            "type: debt\n"
            "status: new\n"
            "created: 2026-05-25T00:00:00+00:00\n"
            "---\n\n"
            "Legacy debt fixture.\n",
            encoding="utf-8",
        )
    before = _file_snapshot(project)

    scan = _doctor_scan(project, category="migration_currency,file_diagnostics")

    assert _file_snapshot(project) == before
    assert scan["maintenance_route"]["status"] == "compatibility-mode"
    adjustments = scan["compatibility_adjustments"]
    assert adjustments["applied"] is True
    assert adjustments["collapsed_count"] >= 1
    ids = [finding["id"] for finding in scan["findings"]]
    assert "migration-currency:taxonomy-drift:old-prefixes" not in ids
    assert not any(id_.startswith("file-diagnostics:invalid-id:") for id_ in ids)
    assert "file-diagnostics:duplicate-id:DEBT-001" in ids
    assert adjustments["collapsed_by_kind"]["legacy-work-item-id"] >= 1
    summary = next(
        finding for finding in scan["findings"]
        if finding["id"] == "compatibility-mode:accepted-legacy-taxonomy"
    )
    assert summary["severity"] == "info"
    assert summary["fix_type"] == "report-only"


def test_doctor_routes_supported_flat_bl_project_to_migration_flow(tmp_path):
    project = _copy_flat_bl_fixture(tmp_path)
    before = _file_snapshot(project)

    scan = _doctor_scan(project)

    assert _file_snapshot(project) == before
    route = scan["maintenance_route"]
    assert route["status"] == "supported-migration-available"
    assert route["primary_action"]["label"] == "Start supported migration"
    assert route["primary_action"]["capability_id"] == "migrate.flat_bl_to_issue"
    assert route["primary_action"]["delegate_skill"] == "sweetclaude:migrate"
    assert route["primary_action"]["supported_project_shapes"] == ["flat_bl_backlog"]
    assert route["capability_check"]["supported"] is True
    assert route["migration_preflight"]["migrate_allowed"] is True
    assert route["guard"]["status"] == "migration-may-be-needed"


def test_doctor_never_recommends_migration_without_manifest_support(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\nrecovery:\n"
        + "  taxonomy:\n"
        + "    status: stabilized-without-migration\n"
        + "    migration_required: false\n"
        + "    blind_taxonomy_migration_allowed: false\n",
        encoding="utf-8",
    )

    scan = _doctor_scan(project)
    route = scan["maintenance_route"]

    assert route["status"] == "compatibility-mode"
    assert route["guard"]["project_shape"] == "accepted_legacy_taxonomy"
    assert route["primary_action"].get("delegate_skill") != "sweetclaude:migrate"
    assert scan["migration_recommendations"] == []
    assert scan["manifest_migration_policy"]["blocked_prompt_count"] >= 0
    assert all(
        finding.get("fix_recipe", {}).get("type") != "migration"
        for finding in scan["findings"]
        if finding.get("fix_type") == "report-only"
    )
    assert all(
        capability["capability_id"] != "migrate.flat_bl_to_issue"
        for capability in route["blocked_capabilities"]
    )
    assert route["blocked_capabilities"][0]["capability_id"] == (
        "migrate.typed_legacy_backlog"
    )


def test_doctor_does_not_dispatch_migration_from_supported_version_string(tmp_path):
    project = _copy_syncog_fixture(tmp_path, migration_status="deferred")
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    state_path.write_text(
        "\n".join([
            "framework:",
            "  installed_version: 4.1.9-beta",
            "  migration_status: deferred",
            "paths:",
            "  product_base: docs/product",
            "recovery:",
            "  taxonomy:",
            "    status: stabilized-without-migration",
            "    migration_required: false",
            "    blind_taxonomy_migration_allowed: false",
            "",
        ]),
        encoding="utf-8",
    )

    scan = _doctor_scan(project)
    route = scan["maintenance_route"]

    assert route["guard"]["project_shape"] == "accepted_legacy_taxonomy"
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["mutates_project"] is False
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert route["primary_action"].get("delegate_skill") != "sweetclaude:migrate"
    assert scan["migration_recommendations"] == []
