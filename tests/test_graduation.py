import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
RECOVER = REPO_ROOT / "scripts" / "recovery" / "recover_project.py"
V4_COMPAT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "v4-compliant-compat"
SYNCOG_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "syncog-layout"


def _make_compat_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(V4_COMPAT_FIXTURE, project)
    state_dir = project / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sweetclaude.yaml").write_text(
        yaml.safe_dump({
            "framework": {
                "installed_version": "4.2.5-beta",
                "migration_status": "deferred",
            },
            "paths": {"product_base": "docs/product"},
            "recovery": {
                "taxonomy": {
                    "status": "stabilized-without-migration",
                    "migration_required": False,
                    "blind_taxonomy_migration_allowed": False,
                },
            },
        }, default_flow_style=False),
        encoding="utf-8",
    )
    return project


def _make_typed_legacy_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(SYNCOG_FIXTURE, project)
    state_dir = project / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (project / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "schema_version: 1\n"
        "categories:\n"
        "  product:\n"
        "    privacy: private\n"
        "    base_path: docs/product\n",
        encoding="utf-8",
    )
    (state_dir / "sweetclaude.yaml").write_text(
        yaml.safe_dump({
            "framework": {
                "installed_version": "4.2.5-beta",
                "migration_status": "deferred",
            },
            "paths": {"product_base": "docs/product"},
            "recovery": {
                "taxonomy": {
                    "status": "stabilized-without-migration",
                    "migration_required": False,
                    "blind_taxonomy_migration_allowed": False,
                },
            },
        }, default_flow_style=False),
        encoding="utf-8",
    )
    return project


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_cmd(script: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout)


# --- characterize_project v4_compliance ---


def test_v4_compliance_all_pass_for_clean_v4_fixture(tmp_path):
    from recovery.characterize_project import characterize_project

    project = _make_compat_project(tmp_path)
    result = characterize_project(project)
    v4c = result["v4_compliance"]

    assert v4c["is_v4_only"] is True
    assert v4c["old_prefix_count"] == 0
    assert v4c["v4_prefix_count"] >= 3
    assert v4c["has_required_fields"] is True
    assert v4c["canonical_types_only"] is True
    assert v4c["no_duplicates"] is True
    assert v4c["standard_structure"] is True


def test_v4_compliance_detects_old_prefixes(tmp_path):
    from recovery.characterize_project import characterize_project

    project = _make_typed_legacy_project(tmp_path)
    result = characterize_project(project)
    v4c = result["v4_compliance"]

    assert v4c["is_v4_only"] is False
    assert v4c["old_prefix_count"] > 0


# --- graduation_check ---


def test_graduation_check_passes_for_v4_compliant_project(tmp_path):
    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(_make_compat_project(tmp_path)),
    )
    assert result["graduation_allowed"] is True
    assert result["reason"] == "v4-compliant"


def test_graduation_check_blocks_old_prefix_files(tmp_path):
    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(_make_typed_legacy_project(tmp_path)),
    )
    assert result["graduation_allowed"] is False
    assert result["reason"] == "validation-failures"
    blocker_codes = [b["code"] for b in result["blockers"]]
    assert "old-prefix-files-remain" in blocker_codes


def test_graduation_check_blocks_duplicate_ids(tmp_path):
    project = _make_compat_project(tmp_path)
    dupe = project / "docs" / "product" / "backlog" / "ISSUE-001-duplicate.md"
    dupe.write_text(
        "---\nid: ISSUE-001\ntitle: Duplicate\ntype: bug-fix\nstatus: new\n"
        "created: '2026-05-25T00:00:00+00:00'\n---\n\nDuplicate.\n",
        encoding="utf-8",
    )

    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(project),
    )
    assert result["graduation_allowed"] is False
    blocker_codes = [b["code"] for b in result["blockers"]]
    assert "duplicate-ids" in blocker_codes


def test_graduation_check_blocks_legacy_type_aliases(tmp_path):
    project = _make_compat_project(tmp_path)
    legacy = project / "docs" / "product" / "backlog" / "ISSUE-004-legacy-type.md"
    legacy.write_text(
        "---\nid: ISSUE-004\ntitle: Legacy type\ntype: bug\nstatus: new\n"
        "created: '2026-05-25T00:00:00+00:00'\n---\n\nLegacy type.\n",
        encoding="utf-8",
    )

    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(project),
    )
    assert result["graduation_allowed"] is False
    blocker_codes = [b["code"] for b in result["blockers"]]
    assert "legacy-type-aliases" in blocker_codes


def test_graduation_check_rejects_non_compat_project(tmp_path):
    project = _make_compat_project(tmp_path)
    state_path = project / ".sweetclaude" / "state" / "sweetclaude.yaml"
    data = yaml.safe_load(state_path.read_text())
    del data["recovery"]
    data["framework"]["migration_status"] = "complete"
    state_path.write_text(yaml.safe_dump(data, default_flow_style=False))

    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(project),
    )
    assert result["graduation_allowed"] is False
    assert result["reason"] == "not-in-compatibility-mode"


# --- graduate ---


def test_graduate_writes_state_and_marks_complete(tmp_path):
    project = _make_compat_project(tmp_path)

    result = _run_cmd(RECOVER, "graduate", "--project-dir", str(project))
    assert result["status"] == "graduated"
    assert "graduated_at" in result

    state = yaml.safe_load(
        (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text()
    )
    assert state["recovery"]["taxonomy"]["status"] == "graduated"
    assert state["recovery"]["taxonomy"]["compatibility_exited"] is True
    assert state["framework"]["migration_status"] == "complete"


def test_graduate_blocks_when_not_v4_compliant(tmp_path):
    project = _make_typed_legacy_project(tmp_path)

    result = _run_cmd(RECOVER, "graduate", "--project-dir", str(project))
    assert result["status"] == "blocked"


def test_graduate_is_idempotent_check_after_graduation(tmp_path):
    project = _make_compat_project(tmp_path)

    _run_cmd(RECOVER, "graduate", "--project-dir", str(project))

    result = _run_cmd(
        RECOVER, "graduation-check", "--project-dir", str(project),
    )
    assert result["graduation_allowed"] is False
    assert result["reason"] == "already-graduated"


# --- guard routing ---


def test_guard_routes_v4_compat_project_to_graduation_candidate(tmp_path):
    project = _make_compat_project(tmp_path)

    result = _run_cmd(RECOVER, "guard", "--project-dir", str(project))
    assert result["project_shape"] == "graduation_candidate"
    assert result["status"] == "graduation-available"


def test_guard_routes_typed_legacy_to_accepted_legacy(tmp_path):
    project = _make_typed_legacy_project(tmp_path)

    result = _run_cmd(RECOVER, "guard", "--project-dir", str(project))
    assert result["project_shape"] == "accepted_legacy_taxonomy"
    assert result["status"] == "compatibility-mode"


# --- doctor maintenance route ---


def test_doctor_route_graduation_available_for_v4_compat(tmp_path):
    project = _make_compat_project(tmp_path)

    result = _run_cmd(
        DOCTOR, "maintenance-route", "--project-dir", str(project),
    )
    route = result["maintenance_route"]
    assert route["status"] == "graduation-available"
    assert route["primary_action"]["capability_id"] == "recover.graduate_from_compatibility"
    assert route["primary_action"]["mutates_project"] is True


def test_doctor_route_compat_mode_for_typed_legacy(tmp_path):
    project = _make_typed_legacy_project(tmp_path)

    result = _run_cmd(
        DOCTOR, "maintenance-route", "--project-dir", str(project),
    )
    route = result["maintenance_route"]
    assert route["status"] == "compatibility-mode"
    assert route["primary_action"]["capability_id"] == "doctor.compatibility_mode"


# --- read-only guarantees ---


def test_graduation_check_is_read_only(tmp_path):
    project = _make_compat_project(tmp_path)
    before = _file_snapshot(project)

    _run_cmd(RECOVER, "graduation-check", "--project-dir", str(project))

    assert _file_snapshot(project) == before


def test_guard_graduation_routing_is_read_only(tmp_path):
    project = _make_compat_project(tmp_path)
    before = _file_snapshot(project)

    _run_cmd(RECOVER, "guard", "--project-dir", str(project))

    assert _file_snapshot(project) == before


def test_doctor_route_graduation_is_read_only(tmp_path):
    project = _make_compat_project(tmp_path)
    before = _file_snapshot(project)

    _run_cmd(DOCTOR, "maintenance-route", "--project-dir", str(project))

    assert _file_snapshot(project) == before
