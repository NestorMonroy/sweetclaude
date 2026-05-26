import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from release_gate import check_release_readiness


ROOT = Path(__file__).parents[1]
REQUIRED_CHECKS = [
    "tests",
    "channel-isolation",
    "installation-smoke",
    "static-checks",
    "release-metadata",
]


def _write_release_project(project_dir: Path, version: str) -> None:
    (project_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (project_dir / "package.json").write_text(
        json.dumps({"name": "sweetclaude", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (project_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "sweetclaude", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (project_dir / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] -- 2026-05-25\n\n- Test release.\n",
        encoding="utf-8",
    )


def _write_release_receipt(project_dir: Path, tag: str, checks=None, status="pass") -> Path:
    checks = checks or REQUIRED_CHECKS
    receipt = {
        "schema_version": 1,
        "receipt_type": "release",
        "subject_id": f"release:{tag}",
        "status": status,
        "created_at": "2026-05-25T12:00:00Z",
        "checks": [
            {
                "name": name,
                "status": "pass",
                "command": f"verify {name}",
                "summary": f"{name} passed",
            }
            for name in checks
        ],
    }
    path = project_dir / ".sweetclaude" / "state" / "evidence" / f"{tag}-release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def _git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_release_git_state(
    project_dir: Path,
    *,
    branch: str,
    tag: str | None = None,
    upstream: str | None = None,
) -> None:
    _git(project_dir, "init")
    _git(project_dir, "config", "user.email", "tests@sweetclaude.local")
    _git(project_dir, "config", "user.name", "SweetClaude Tests")
    _git(project_dir, "remote", "add", "origin", "https://example.invalid/sweetclaude.git")
    _git(project_dir, "checkout", "-b", branch)
    _git(project_dir, "add", ".")
    _git(project_dir, "commit", "-m", "release candidate")
    if tag:
        _git(project_dir, "tag", tag)
    upstream = upstream or f"origin/{branch}"
    _git(project_dir, "update-ref", f"refs/remotes/{upstream}", "HEAD")
    remote, remote_branch = upstream.split("/", 1)
    _git(project_dir, "config", f"branch.{branch}.remote", remote)
    _git(project_dir, "config", f"branch.{branch}.merge", f"refs/heads/{remote_branch}")


def test_beta_release_readiness_accepts_valid_receipt_and_metadata(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")

    result = check_release_readiness(
        tmp_path,
        tag="v4.1.7-beta",
        channel="beta",
        branch="beta-4.x",
        receipt_path=receipt,
    )

    assert result["ok"] is True
    assert result["version"] == "4.1.7-beta"
    assert result["git"]["checked"] is False
    assert result["checks"] == sorted(REQUIRED_CHECKS)


def test_release_readiness_accepts_matching_git_branch_upstream_and_tag(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")
    _init_release_git_state(tmp_path, branch="beta-4.x", tag="v4.1.7-beta")

    result = check_release_readiness(
        tmp_path,
        tag="v4.1.7-beta",
        channel="beta",
        branch="beta-4.x",
        receipt_path=receipt,
    )

    assert result["ok"] is True
    assert result["git"]["checked"] is True
    assert result["git"]["branch"] == "beta-4.x"
    assert result["git"]["upstream"] == "origin/beta-4.x"
    assert "v4.1.7-beta" in result["git"]["head_tags"]


@pytest.mark.parametrize("actual_branch", ["main", "evidence-gates-beta"])
def test_release_readiness_rejects_wrong_actual_git_branch(tmp_path, actual_branch):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")
    _init_release_git_state(tmp_path, branch=actual_branch, tag="v4.1.7-beta")

    with pytest.raises(ValueError, match="current git branch mismatch"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_release_readiness_rejects_wrong_git_upstream(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")
    _init_release_git_state(
        tmp_path,
        branch="beta-4.x",
        tag="v4.1.7-beta",
        upstream="origin/evidence-gates-beta",
    )

    with pytest.raises(ValueError, match="upstream mismatch"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_release_readiness_rejects_missing_head_tag(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")
    _init_release_git_state(tmp_path, branch="beta-4.x")

    with pytest.raises(ValueError, match="must point at HEAD"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_stable_release_rejects_beta_version(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")

    with pytest.raises(ValueError, match="stable channel cannot release prerelease"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="stable",
            branch="stable-3.x",
            receipt_path=receipt,
        )


def test_beta_release_rejects_stable_version(tmp_path):
    _write_release_project(tmp_path, "4.1.7")
    receipt = _write_release_receipt(tmp_path, "v4.1.7")

    with pytest.raises(ValueError, match="beta channel releases must use"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_release_readiness_rejects_metadata_drift(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "sweetclaude", "version": "4.1.6-beta"}) + "\n",
        encoding="utf-8",
    )
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")

    with pytest.raises(ValueError, match="plugin.json version mismatch"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_release_readiness_rejects_missing_required_receipt_checks(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(
        tmp_path,
        "v4.1.7-beta",
        checks=["tests", "channel-isolation"],
    )

    with pytest.raises(ValueError, match="missing required checks"):
        check_release_readiness(
            tmp_path,
            tag="v4.1.7-beta",
            channel="beta",
            branch="beta-4.x",
            receipt_path=receipt,
        )


def test_release_gate_cli_returns_json_success(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")

    completed = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "release_gate.py"),
            "check",
            "--project-dir",
            str(tmp_path),
            "--tag",
            "v4.1.7-beta",
            "--channel",
            "beta",
            "--branch",
            "beta-4.x",
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["ok"] is True


def test_release_gate_cli_validates_actual_git_branch(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")
    receipt = _write_release_receipt(tmp_path, "v4.1.7-beta")
    _init_release_git_state(tmp_path, branch="evidence-gates-beta", tag="v4.1.7-beta")

    completed = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "release_gate.py"),
            "check",
            "--project-dir",
            str(tmp_path),
            "--tag",
            "v4.1.7-beta",
            "--channel",
            "beta",
            "--branch",
            "beta-4.x",
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    out = json.loads(completed.stdout)
    assert out["ok"] is False
    assert "current git branch mismatch" in out["error"]


def test_release_gate_cli_fails_closed_without_receipt(tmp_path):
    _write_release_project(tmp_path, "4.1.7-beta")

    completed = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "release_gate.py"),
            "check",
            "--project-dir",
            str(tmp_path),
            "--tag",
            "v4.1.7-beta",
            "--channel",
            "beta",
            "--branch",
            "beta-4.x",
            "--receipt",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    out = json.loads(completed.stdout)
    assert out["ok"] is False
    assert "not found" in out["error"].lower()
