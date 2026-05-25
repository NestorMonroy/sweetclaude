#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release readiness gate for SweetClaude tags."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from evidence import validate_receipt


REQUIRED_RELEASE_CHECKS = {
    "tests",
    "channel-isolation",
    "installation-smoke",
    "static-checks",
    "release-metadata",
}


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Required file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _version_from_tag(tag: str) -> str:
    if not tag.startswith("v"):
        raise ValueError("Release tag must start with 'v'")
    version = tag[1:]
    if not re.match(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$", version):
        raise ValueError(f"Release tag has invalid semantic version: {tag}")
    return version


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def _has_prerelease(version: str) -> bool:
    return "-" in version


def _validate_channel(version: str, channel: str, branch: str | None) -> None:
    if channel not in {"stable", "beta"}:
        raise ValueError("channel must be 'stable' or 'beta'")

    if channel == "stable":
        if _has_prerelease(version):
            raise ValueError("stable channel cannot release prerelease versions")
        if _major(version) != 3:
            raise ValueError("current stable channel is stable-3.x; stable releases must be 3.x")
        if branch and branch != "stable-3.x":
            raise ValueError("stable releases must be prepared from stable-3.x")
        return

    if not _has_prerelease(version):
        raise ValueError("beta channel releases must use an explicit prerelease suffix")
    if _major(version) != 4:
        raise ValueError("current beta channel is beta-4.x; beta releases must be 4.x")
    if branch and branch != "beta-4.x":
        raise ValueError("beta releases must be prepared from beta-4.x")


def _metadata_version(project_dir: Path, version: str) -> None:
    package = _load_json(project_dir / "package.json")
    package_version = package.get("version")
    if package_version != version:
        raise ValueError(f"package.json version mismatch: expected {version}, got {package_version}")

    plugin = _load_json(project_dir / ".claude-plugin" / "plugin.json")
    plugin_version = plugin.get("version")
    if plugin_version != version:
        raise ValueError(
            f".claude-plugin/plugin.json version mismatch: expected {version}, got {plugin_version}"
        )

    changelog = project_dir / "CHANGELOG.md"
    try:
        changelog_text = changelog.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError("CHANGELOG.md is required before release") from None
    if f"## [{version}]" not in changelog_text:
        raise ValueError(f"CHANGELOG.md is missing release section [{version}]")


def _validate_release_receipt(receipt_path: str | Path, tag: str) -> dict:
    receipt = validate_receipt(
        receipt_path,
        subject_id=f"release:{tag}",
        receipt_type="release",
    )
    checks = {
        str(check.get("name", "")).strip()
        for check in receipt.get("checks", [])
        if isinstance(check, dict)
    }
    missing = sorted(REQUIRED_RELEASE_CHECKS - checks)
    if missing:
        raise ValueError(
            "Release evidence receipt is missing required checks: " + ", ".join(missing)
        )
    return receipt


def check_release_readiness(
    project_dir: Path,
    *,
    tag: str,
    channel: str,
    receipt_path: str | Path,
    branch: str | None = None,
) -> dict:
    project_dir = project_dir.resolve()
    version = _version_from_tag(tag)
    _validate_channel(version, channel, branch)
    _metadata_version(project_dir, version)
    receipt = _validate_release_receipt(receipt_path, tag)
    return {
        "ok": True,
        "tag": tag,
        "version": version,
        "channel": channel,
        "branch": branch,
        "receipt": str(Path(receipt_path)),
        "checks": sorted(str(c.get("name", "")) for c in receipt.get("checks", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SweetClaude release readiness gate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--project-dir", required=True, type=Path)
    p_check.add_argument("--tag", required=True)
    p_check.add_argument("--channel", required=True, choices=["stable", "beta"])
    p_check.add_argument("--receipt", required=True)
    p_check.add_argument("--branch", default=None)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "check":
            result = check_release_readiness(
                args.project_dir,
                tag=args.tag,
                channel=args.channel,
                receipt_path=args.receipt,
                branch=args.branch,
            )
            print(json.dumps(result))
            return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
