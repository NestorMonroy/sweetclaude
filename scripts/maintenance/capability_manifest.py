#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load SweetClaude release-channel and capability safety metadata."""
from __future__ import annotations

import os
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


MANIFEST_RELATIVE_PATH = Path("config") / "capability-manifest.yaml"


def _versionless_config_path() -> Path:
    return Path.home() / ".claude" / "config" / "sweetclaude" / "capability-manifest.yaml"


def _candidate_paths() -> list[Path]:
    script_path = Path(__file__).resolve()
    candidates = [
        # Dev clone and plugin-cache install layout.
        script_path.parents[2] / MANIFEST_RELATIVE_PATH,
        # Versionless installed script layout.
        _versionless_config_path(),
    ]
    explicit = os.environ.get("SWEETCLAUDE_CAPABILITY_MANIFEST")
    if explicit:
        candidates.insert(0, Path(explicit))
    return candidates


def _require_bool(config: dict[str, Any], key: str, context: str) -> None:
    if not isinstance(config.get(key), bool):
        raise ValueError(f"Capability manifest {context}.{key} must be a boolean")


def _require_string_list(config: dict[str, Any], key: str, context: str) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Capability manifest {context}.{key} must be a string list")
    return value


def validate_manifest(data: dict[str, Any]) -> None:
    """Validate the capability manifest graph and high-stakes safety fields."""
    channels = data.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("Capability manifest must define channels")
    for channel, config in channels.items():
        context = f"channels.{channel}"
        if not isinstance(config, dict):
            raise ValueError(f"Capability manifest {context} must be a mapping")
        for key in ("branch", "expected_marketplace"):
            if not isinstance(config.get(key), str) or not config[key]:
                raise ValueError(f"Capability manifest {context}.{key} must be a non-empty string")
        if not isinstance(config.get("major_version"), int):
            raise ValueError(f"Capability manifest {context}.major_version must be an integer")
        _require_bool(config, "prerelease_required", context)
        _require_bool(config, "prerelease_allowed", context)

    release = data.get("release")
    if not isinstance(release, dict):
        raise ValueError("Capability manifest must define release")
    _require_string_list(release, "required_evidence_checks", "release")

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        raise ValueError("Capability manifest must define capabilities")

    project_shapes = data.get("project_shapes")
    if not isinstance(project_shapes, dict) or not project_shapes:
        raise ValueError("Capability manifest must define project_shapes")

    for capability_id, config in capabilities.items():
        context = f"capabilities.{capability_id}"
        if not isinstance(config, dict):
            raise ValueError(f"Capability manifest {context} must be a mapping")
        if not isinstance(config.get("title"), str) or not config["title"]:
            raise ValueError(f"Capability manifest {context}.title must be a non-empty string")
        supported_shapes = _require_string_list(config, "supports_project_shapes", context)
        for shape in supported_shapes:
            if shape not in project_shapes:
                raise ValueError(
                    f"Capability manifest {context}.supports_project_shapes references unknown shape: {shape}"
                )
        _require_bool(config, "mutates_project", context)
        _require_bool(config, "requires_approval", context)
        if config.get("supported") is not None:
            _require_bool(config, "supported", context)
        if config.get("mutates_project") and not config.get("requires_approval"):
            raise ValueError(f"Capability manifest {context} mutates_project requires approval")

    for shape, config in project_shapes.items():
        context = f"project_shapes.{shape}"
        if not isinstance(config, dict):
            raise ValueError(f"Capability manifest {context} must be a mapping")
        if not isinstance(config.get("guard_status"), str) or not config["guard_status"]:
            raise ValueError(f"Capability manifest {context}.guard_status must be a non-empty string")
        _require_bool(config, "migrate_allowed", context)
        for key in ("recovery_capability", "doctor_capability", "migration_capability"):
            capability_id = config.get(key)
            if capability_id is None:
                continue
            if capability_id not in capabilities:
                raise ValueError(f"Capability manifest {context}.{key} references unknown capability: {capability_id}")
            supported_shapes = capabilities[capability_id].get("supports_project_shapes") or []
            if shape not in supported_shapes:
                raise ValueError(
                    f"Capability manifest {context}.{key} capability does not support shape: {shape}"
                )
        for capability_id in config.get("blocked_capabilities") or []:
            if capability_id not in capabilities:
                raise ValueError(
                    f"Capability manifest {context}.blocked_capabilities references unknown capability: {capability_id}"
                )


def load_manifest(path: Path | str | None = None) -> dict[str, Any]:
    candidates = [Path(path)] if path else _candidate_paths()
    manifest_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Capability manifest not found: {manifest_path}") from None
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid capability manifest YAML: {manifest_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Capability manifest must be a mapping: {manifest_path}")
    if data.get("schema_version") != 1:
        raise ValueError("Capability manifest schema_version must be 1")
    validate_manifest(data)
    return data


def channel_config(channel: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    data = manifest or load_manifest()
    channels = data.get("channels") or {}
    config = channels.get(channel)
    if not isinstance(config, dict):
        raise ValueError(f"Unknown SweetClaude channel: {channel}")
    return config


def expected_ref(channel: str, manifest: dict[str, Any] | None = None) -> str:
    return str(channel_config(channel, manifest).get("branch", "") or "")


def expected_marketplace(channel: str, manifest: dict[str, Any] | None = None) -> str:
    return str(channel_config(channel, manifest).get("expected_marketplace", "") or "")


def minimum_safe_version(channel: str, manifest: dict[str, Any] | None = None) -> str:
    return str(channel_config(channel, manifest).get("minimum_safe_version", "") or "")


def required_release_checks(manifest: dict[str, Any] | None = None) -> set[str]:
    data = manifest or load_manifest()
    release = data.get("release") or {}
    checks = release.get("required_evidence_checks")
    if not isinstance(checks, list) or not all(isinstance(check, str) for check in checks):
        raise ValueError("Capability manifest release.required_evidence_checks must be a string list")
    return set(checks)


def capability_config(
    capability_id: str, manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = manifest or load_manifest()
    capabilities = data.get("capabilities") or {}
    config = capabilities.get(capability_id)
    if not isinstance(config, dict):
        raise ValueError(f"Unknown SweetClaude capability: {capability_id}")
    return config


def project_shape_config(
    shape: str, manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = manifest or load_manifest()
    shapes = data.get("project_shapes") or {}
    config = shapes.get(shape)
    if not isinstance(config, dict):
        raise ValueError(f"Unknown SweetClaude project shape: {shape}")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SweetClaude capability manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--path", type=Path)
    validate.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            manifest = load_manifest(args.path)
            result = {
                "ok": True,
                "schema_version": manifest["schema_version"],
                "channels": sorted(manifest["channels"].keys()),
                "capabilities": sorted(manifest["capabilities"].keys()),
                "project_shapes": sorted(manifest["project_shapes"].keys()),
            }
            print(json.dumps(result, indent=2 if args.pretty else None))
            return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
