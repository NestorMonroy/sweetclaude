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


def _make_compat_mode_project(tmp_path: Path) -> Path:
    """A stabilized project that still routes to compatibility mode under S7.

    It is v4-clean (no old-prefix work items, so it does NOT route to migration)
    but has a non-standard structure — a v4 ISSUE file outside backlog/ — so
    graduation is blocked by a non-fixable issue and the guard lands on
    accepted_legacy_taxonomy / compatibility-mode. (The syncog fixture no longer
    reaches this state post-S7: its old prefixes route it to migration.)
    """
    project = tmp_path / "compat"
    (project / "docs" / "product").mkdir(parents=True)
    (project / "docs" / "product" / "ISSUE-001-orphan.md").write_text(
        "---\nid: ISSUE-001\ntitle: Orphan\ntype: bug-fix\nstatus: new\n---\n\nbody\n",
        encoding="utf-8",
    )
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
        "framework:\n"
        "  installed_version: 4.1.4-beta\n"
        "  migration_status: deferred\n"
        "paths:\n"
        "  product_base: docs/product\n"
        "recovery:\n"
        "  taxonomy:\n"
        "    status: stabilized-without-migration\n"
        "    migration_required: false\n"
        "    blind_taxonomy_migration_allowed: false\n",
        encoding="utf-8",
    )
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
    project = _make_compat_mode_project(tmp_path)
    before = _file_snapshot(project)

    result = _doctor_route(project)

    assert _file_snapshot(project) == before
    assert "findings" not in result
    route = result["maintenance_route"]
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["mutates_project"] is False
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert result["project_state_summary"]["product_base"].endswith("docs/product")


def test_doctor_routes_accepted_legacy_layout_to_compatibility_mode(tmp_path):
    project = _make_compat_mode_project(tmp_path)

    scan = _doctor_scan(project)

    route = scan["maintenance_route"]
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["label"] == "Continue in compatibility mode"
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert route["primary_action"]["mutates_project"] is False
    # accepted_legacy_taxonomy is a compatibility-mode shape that still OFFERS
    # migration (manifest: migrate_allowed: true) — staying in compat and
    # migrating to v4 are both available from here.
    assert route["guard"]["migrate_allowed"] is True
    # S7 unblocked migrate.typed_legacy_backlog, so the accepted_legacy_taxonomy
    # route no longer lists it as a blocked capability.
    assert route["blocked_capabilities"] == []


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


def test_doctor_compat_mode_does_not_dispatch_migration(tmp_path):
    project = _make_compat_mode_project(tmp_path)

    scan = _doctor_scan(project)
    route = scan["maintenance_route"]

    assert route["guard"]["project_shape"] == "accepted_legacy_taxonomy"
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["mutates_project"] is False
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"
    assert route["primary_action"].get("delegate_skill") != "sweetclaude:migrate"
    assert scan["migration_recommendations"] == []
