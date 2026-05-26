#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release readiness gate for SweetClaude tags."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from evidence import validate_receipt
from maintenance.capability_manifest import channel_config, expected_ref, required_release_checks


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
    config = channel_config(channel)
    expected_major = int(config["major_version"])
    channel_ref = expected_ref(channel)
    prerelease_required = bool(config.get("prerelease_required"))
    prerelease_allowed = bool(config.get("prerelease_allowed", True))

    if _has_prerelease(version) and not prerelease_allowed:
        raise ValueError(f"{channel} channel cannot release prerelease versions")
    if prerelease_required and not _has_prerelease(version):
        raise ValueError(f"{channel} channel releases must use an explicit prerelease suffix")
    if _major(version) != expected_major:
        raise ValueError(
            f"current {channel} channel is {channel_ref}; {channel} releases must be {expected_major}.x"
        )
    if branch and branch != channel_ref:
        raise ValueError(f"{channel} releases must be prepared from {channel_ref}")



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
    missing = sorted(required_release_checks() - checks)
    if missing:
        raise ValueError(
            "Release evidence receipt is missing required checks: " + ", ".join(missing)
        )
    return receipt


def _git(project_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _is_git_repo(project_dir: Path) -> bool:
    completed = _git(project_dir, "rev-parse", "--is-inside-work-tree", check=False)
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def _validate_git_state(project_dir: Path, *, tag: str, branch: str) -> dict:
    if not _is_git_repo(project_dir):
        return {"checked": False, "reason": "not-a-git-work-tree"}

    actual_branch = _git(project_dir, "branch", "--show-current").stdout.strip()
    if not actual_branch:
        raise ValueError("release must be prepared from a named git branch, not detached HEAD")
    if actual_branch != branch:
        raise ValueError(f"current git branch mismatch: expected {branch}, got {actual_branch}")

    upstream = _git(
        project_dir,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    if upstream.returncode != 0:
        raise ValueError(f"release branch {branch} must track origin/{branch}")
    upstream_name = upstream.stdout.strip()
    expected_upstream = f"origin/{branch}"
    if upstream_name != expected_upstream:
        raise ValueError(
            f"release branch upstream mismatch: expected {expected_upstream}, got {upstream_name}"
        )

    dirty = _git(project_dir, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        raise ValueError("release checkout has tracked modifications")

    head_tags = {
        line.strip()
        for line in _git(project_dir, "tag", "--points-at", "HEAD").stdout.splitlines()
        if line.strip()
    }
    if tag not in head_tags:
        raise ValueError(f"release tag {tag} must point at HEAD")

    return {
        "checked": True,
        "branch": actual_branch,
        "upstream": upstream_name,
        "head_tags": sorted(head_tags),
    }


def check_release_readiness(
    project_dir: Path,
    *,
    tag: str,
    channel: str,
    receipt_path: str | Path,
    branch: str,
) -> dict:
    project_dir = project_dir.resolve()
    version = _version_from_tag(tag)
    _validate_channel(version, channel, branch)
    _metadata_version(project_dir, version)
    receipt = _validate_release_receipt(receipt_path, tag)
    git_state = _validate_git_state(project_dir, tag=tag, branch=branch)
    return {
        "ok": True,
        "tag": tag,
        "version": version,
        "channel": channel,
        "branch": branch,
        "git": git_state,
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
    p_check.add_argument("--branch", required=True)

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
