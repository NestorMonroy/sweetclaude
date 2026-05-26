import os
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from maintenance.capability_manifest import (  # noqa: E402
    capability_config,
    expected_marketplace,
    expected_ref,
    load_manifest,
    minimum_safe_version,
    project_shape_config,
    required_release_checks,
    validate_manifest,
)


ROOT = Path(__file__).parents[1]


def test_capability_manifest_loads_channel_facts():
    manifest = load_manifest(ROOT / "config" / "capability-manifest.yaml")

    assert expected_ref("stable", manifest) == "stable-3.x"
    assert expected_marketplace("stable", manifest) == "sweetclaude-stable"
    assert expected_ref("beta", manifest) == "beta-4.x"
    assert expected_marketplace("beta", manifest) == "sweetclaude-beta"
    assert minimum_safe_version("beta", manifest) == "4.1.9-beta"


def test_capability_manifest_loads_release_checks():
    checks = required_release_checks()

    assert checks == {
        "tests",
        "channel-isolation",
        "installation-smoke",
        "static-checks",
        "release-metadata",
        "manifest-validation",
    }


def test_capability_manifest_loads_project_shape_routes():
    assert project_shape_config("recovery_required")["guard_status"] == "run-recover"
    assert project_shape_config("flat_bl_backlog")["migrate_allowed"] is True
    assert project_shape_config("typed_legacy_backlog")["guard_status"] == (
        "compatibility-mode"
    )


def test_capability_manifest_loads_capability_contracts():
    recovery = capability_config("recover.stabilize_without_migration")
    migration = capability_config("migrate.flat_bl_to_issue")
    blocked = capability_config("migrate.typed_legacy_backlog")

    assert recovery["delegate_skill"] == "sweetclaude:recover"
    assert "recovery_required" in recovery["supports_project_shapes"]
    assert "snapshot" in recovery["safety_contract"]
    assert migration["delegate_skill"] == "sweetclaude:migrate"
    assert migration["preflight_required"] is True
    assert migration["supports_project_shapes"] == ["flat_bl_backlog"]
    assert blocked["supported"] is False


def test_capability_manifest_validates_capability_shape_references():
    manifest = load_manifest(ROOT / "config" / "capability-manifest.yaml")
    manifest["project_shapes"]["flat_bl_backlog"]["migration_capability"] = (
        "migrate.typed_legacy_backlog"
    )

    try:
        validate_manifest(manifest)
    except ValueError as exc:
        assert "capability does not support shape" in str(exc)
    else:
        raise AssertionError("validate_manifest accepted a mismatched capability shape")


def test_capability_manifest_validate_cli_emits_summary():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "maintenance" / "capability_manifest.py"),
            "validate",
            "--path",
            str(ROOT / "config" / "capability-manifest.yaml"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert "migrate.flat_bl_to_issue" in payload["capabilities"]
