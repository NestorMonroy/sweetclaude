#!/usr/bin/env python3
"""Tests for configurable trunk branch (ISSUE-225).

Covers:
- TestConfiguredTrunk: project.trunk_branch in sweetclaude.yaml overrides git detection
- TestFallbackWhenUnset: absent/empty trunk_branch preserves existing git-derived behavior
- TestInitHonorsConfiguredTrunk: init preconditions allow/block based on configured trunk
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path setup: this test lives in an agent worktree whose scripts/ directory
# is sparse.  Walk up to the main repo root (4 parents up from this file)
# so imports resolve against the real scripts/.
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
# .claude/worktrees/<agent>/tests/test_*.py  →  parents[3] = .claude/worktrees/<agent>
# parents[4] = main repo root
_CANDIDATE_SCRIPTS = _THIS_FILE.parents[4] / "scripts"
if _CANDIDATE_SCRIPTS.is_dir() and str(_CANDIDATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CANDIDATE_SCRIPTS))

# Fallback: worktree-local scripts (handles running from the main repo)
_LOCAL_SCRIPTS = _THIS_FILE.parents[1] / "scripts"
if _LOCAL_SCRIPTS.is_dir() and str(_LOCAL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SCRIPTS))

from small_story_controller import (
    _detect_main_branch as small_detect_main,
    init_workflow as small_init_workflow,
)
from large_story_controller import (
    _detect_main_branch as large_detect_main,
    init_workflow as large_init_workflow,
)
from success_criteria_contracts import compute_success_criteria_contract_hash


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(path), capture_output=True, text=True, timeout=10,
    )


def _init_git_repo(path: Path, branch: str = "main") -> None:
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("init\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")


def _checkout_new_branch(path: Path, branch: str) -> None:
    r = _git(path, "checkout", "-b", branch)
    assert r.returncode == 0, f"checkout -b {branch} failed: {r.stderr}"
    # Commit a file so the branch has a commit and git status is clean.
    (path / f".branch-marker-{branch.replace('/', '-')}").write_text(f"{branch}\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", f"on branch {branch}")


# ---------------------------------------------------------------------------
# sweetclaude.yaml helpers
# ---------------------------------------------------------------------------

def _write_sweetclaude_yaml(project: Path, data: dict) -> None:
    sc_dir = project / ".sweetclaude" / "state"
    sc_dir.mkdir(parents=True, exist_ok=True)
    (sc_dir / "sweetclaude.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Contract + backlog helpers (mirrors test_small_story_gate.py conventions)
# ---------------------------------------------------------------------------

def _make_contract(story_id: str, controller_kind: str = "small-story") -> dict:
    criterion = {
        "id": "SC-001",
        "outcome_id": "OUTCOME-001",
        "statement": "The completion validator returns status success.",
        "binary_predicate": "completion validator returns status success",
        "measurement_type": "schema_check",
        "measurement_procedure": "Run completion validator.",
        "evidence_artifact": (
            f".sweetclaude/reports/{controller_kind}/{story_id}/evidence/SC-001.json"
        ),
        "evidence_owner": "controller",
        "pass_condition": "validator status equals success",
        "fail_condition": "validator status does not equal success",
        "allowed_phase_to_measure": "implementation",
        "amendment_policy": "human_approved_only",
        "backlog_routing": "Backlog any new concern.",
    }
    contract: dict[str, Any] = {
        "story_id": story_id,
        "story_title": "Trunk branch config test story",
        "story_objective": "Prove trunk branch config is honored in init preconditions.",
        "expected_outcomes": [
            {"id": "OUTCOME-001", "statement": "Init preconditions honor configured trunk."}
        ],
        "non_goals": [
            {"id": "NONGOAL-001", "statement": "Do not test downstream review."}
        ],
        "success_criteria": [criterion],
        "contract_freeze": {
            "frozen_at": "2026-06-26T12:00:00Z",
            "frozen_by": "test",
            "contract_hash": "",
        },
    }
    contract["contract_freeze"]["contract_hash"] = compute_success_criteria_contract_hash(contract)
    return contract


def _write_contract(project: Path, contract: dict) -> Path:
    contract_path = project / ".sweetclaude" / "contracts" / "success-criteria-contract.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return contract_path


def _write_backlog_file(project: Path, story_id: str) -> None:
    backlog_dir = project / "docs" / "product" / "backlog"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    (backlog_dir / f"{story_id}-test.md").write_text(
        f"---\nid: {story_id}\nstatus: new\n---\nTest backlog item.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# TestConfiguredTrunk
# ---------------------------------------------------------------------------

class TestConfiguredTrunk:
    """When project.trunk_branch is set in sweetclaude.yaml,
    _detect_main_branch returns that value — ignoring what git says."""

    def test_small_controller_returns_configured_trunk(self, tmp_path: Path) -> None:
        # Repo whose actual default branch is "main", but config says "beta-4.x"
        _init_git_repo(tmp_path, branch="main")
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": "beta-4.x"}})

        result = small_detect_main(tmp_path)

        assert result == "beta-4.x", (
            f"Expected 'beta-4.x' from config, got '{result}'. "
            "_detect_main_branch must read project.trunk_branch from sweetclaude.yaml."
        )

    def test_large_controller_returns_configured_trunk(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": "beta-4.x"}})

        result = large_detect_main(tmp_path)

        assert result == "beta-4.x", (
            f"Expected 'beta-4.x' from config, got '{result}'. "
            "_detect_main_branch must read project.trunk_branch from sweetclaude.yaml."
        )

    def test_configured_trunk_wins_over_git_origin_head(self, tmp_path: Path) -> None:
        """Even with a real origin/HEAD pointing elsewhere, config wins."""
        # Set up a bare remote so origin/HEAD resolves to "main"
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(remote)],
            capture_output=True,
        )

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local, branch="main")
        _git(local, "remote", "add", "origin", str(remote))
        _git(local, "push", "-u", "origin", "main")
        _git(local, "remote", "set-head", "origin", "main")

        # Sanity: without config, git resolves "main"
        without_config = small_detect_main(local)
        assert without_config == "main"

        # Now override via config
        _write_sweetclaude_yaml(local, {"project": {"trunk_branch": "release/4.x"}})

        result_small = small_detect_main(local)
        result_large = large_detect_main(local)

        assert result_small == "release/4.x", (
            f"small_detect_main should return 'release/4.x', got '{result_small}'"
        )
        assert result_large == "release/4.x", (
            f"large_detect_main should return 'release/4.x', got '{result_large}'"
        )

    def test_no_git_repo_still_returns_configured_trunk(self, tmp_path: Path) -> None:
        """Config is honored even in a non-git directory."""
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": "custom-trunk"}})

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "custom-trunk"
        assert result_large == "custom-trunk"


# ---------------------------------------------------------------------------
# TestFallbackWhenUnset
# ---------------------------------------------------------------------------

class TestFallbackWhenUnset:
    """When project.trunk_branch is absent/empty, _detect_main_branch
    falls back to the existing git-derived logic (backward compatibility)."""

    def test_no_sweetclaude_yaml_falls_back_to_git_main(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        # Deliberately do NOT write sweetclaude.yaml

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "main", f"Expected git-derived 'main', got '{result_small}'"
        assert result_large == "main", f"Expected git-derived 'main', got '{result_large}'"

    def test_project_block_without_trunk_branch_key_falls_back(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        # project: block exists but trunk_branch key is absent
        _write_sweetclaude_yaml(tmp_path, {"project": {"version_stage": "beta"}})

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "main", (
            f"Expected git-derived 'main' when trunk_branch key absent, got '{result_small}'"
        )
        assert result_large == "main", (
            f"Expected git-derived 'main' when trunk_branch key absent, got '{result_large}'"
        )

    def test_empty_string_trunk_branch_falls_back(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": ""}})

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "main", (
            f"Expected git-derived 'main' when trunk_branch is empty string, got '{result_small}'"
        )
        assert result_large == "main", (
            f"Expected git-derived 'main' when trunk_branch is empty string, got '{result_large}'"
        )

    def test_whitespace_only_trunk_branch_falls_back(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": "   "}})

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "main", (
            f"Expected git-derived 'main' when trunk_branch is whitespace, got '{result_small}'"
        )
        assert result_large == "main", (
            f"Expected git-derived 'main' when trunk_branch is whitespace, got '{result_large}'"
        )

    def test_null_trunk_branch_falls_back(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": None}})

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "main"
        assert result_large == "main"

    def test_master_repo_without_config_detected_correctly(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="master")

        result_small = small_detect_main(tmp_path)
        result_large = large_detect_main(tmp_path)

        assert result_small == "master"
        assert result_large == "master"


# ---------------------------------------------------------------------------
# TestInitHonorsConfiguredTrunk
# ---------------------------------------------------------------------------

class TestInitHonorsConfiguredTrunk:
    """init_workflow must use the configured trunk branch when deciding
    whether the current branch passes the precondition check.

    On-trunk with config set: must NOT return blocked_not_on_main.
    Off-trunk: MUST return blocked_not_on_main.
    """

    def _setup_project_on_branch(
        self,
        tmp_path: Path,
        trunk_branch: str,
        current_branch: str,
        story_id: str,
        controller_kind: str = "small-story",
    ) -> Path:
        """Create a git repo, write all init prerequisites, land on current_branch."""
        # Init the repo on trunk_branch
        _init_git_repo(tmp_path, branch=trunk_branch)

        # Pre-create the off-trunk branch if needed (while still on trunk)
        if current_branch != trunk_branch:
            _checkout_new_branch(tmp_path, current_branch)
            # Return to trunk to write setup files cleanly
            _git(tmp_path, "checkout", trunk_branch)

        # Write sweetclaude.yaml with configured trunk
        _write_sweetclaude_yaml(tmp_path, {"project": {"trunk_branch": trunk_branch}})
        _write_backlog_file(tmp_path, story_id)
        contract = _make_contract(story_id, controller_kind)
        _write_contract(tmp_path, contract)

        # Commit all setup files so tree is clean
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "test setup files")

        # Move to the desired current branch
        if current_branch != trunk_branch:
            _git(tmp_path, "checkout", current_branch)

        return tmp_path

    # -- small_story_controller -----------------------------------------------

    def test_small_on_configured_trunk_not_blocked_by_branch(self, tmp_path: Path) -> None:
        """On the configured trunk, init must not be blocked by branch check."""
        story_id = "ISSUE-225"
        project = self._setup_project_on_branch(
            tmp_path,
            trunk_branch="beta-4.x",
            current_branch="beta-4.x",
            story_id=story_id,
            controller_kind="small-story",
        )

        result = small_init_workflow(project_dir=project, workflow_id=story_id)

        assert result.get("code") != "blocked_not_on_main", (
            f"init_workflow must not return blocked_not_on_main when on the configured "
            f"trunk branch 'beta-4.x'. Got: {result}"
        )

    def test_small_off_configured_trunk_blocked_by_branch(self, tmp_path: Path) -> None:
        """Off the configured trunk, init must be blocked with blocked_not_on_main."""
        story_id = "ISSUE-225"
        project = self._setup_project_on_branch(
            tmp_path,
            trunk_branch="beta-4.x",
            current_branch="feature-x",
            story_id=story_id,
            controller_kind="small-story",
        )

        result = small_init_workflow(project_dir=project, workflow_id=story_id)

        assert result.get("code") == "blocked_not_on_main", (
            f"init_workflow must return blocked_not_on_main when on 'feature-x' "
            f"and configured trunk is 'beta-4.x'. Got: {result}"
        )

    # -- large_story_controller -----------------------------------------------

    def test_large_on_configured_trunk_not_blocked_by_branch(self, tmp_path: Path) -> None:
        """On the configured trunk, large init must not be blocked by branch check."""
        story_id = "ISSUE-225"
        project = self._setup_project_on_branch(
            tmp_path,
            trunk_branch="beta-4.x",
            current_branch="beta-4.x",
            story_id=story_id,
            controller_kind="large-story",
        )

        result = large_init_workflow(project_dir=project, workflow_id=story_id)

        assert result.get("code") != "blocked_not_on_main", (
            f"large init_workflow must not return blocked_not_on_main when on the configured "
            f"trunk branch 'beta-4.x'. Got: {result}"
        )

    def test_large_off_configured_trunk_blocked_by_branch(self, tmp_path: Path) -> None:
        """Off the configured trunk, large init must be blocked with blocked_not_on_main."""
        story_id = "ISSUE-225"
        project = self._setup_project_on_branch(
            tmp_path,
            trunk_branch="beta-4.x",
            current_branch="feature-x",
            story_id=story_id,
            controller_kind="large-story",
        )

        result = large_init_workflow(project_dir=project, workflow_id=story_id)

        assert result.get("code") == "blocked_not_on_main", (
            f"large init_workflow must return blocked_not_on_main when on 'feature-x' "
            f"and configured trunk is 'beta-4.x'. Got: {result}"
        )

    # -- git-derived default (no config) is unaffected ------------------------

    def test_small_default_git_derived_trunk_still_works(self, tmp_path: Path) -> None:
        """Without config, the git-derived default 'main' is still the trunk."""
        story_id = "ISSUE-225"
        _init_git_repo(tmp_path, branch="main")
        _write_backlog_file(tmp_path, story_id)
        contract = _make_contract(story_id, "small-story")
        _write_contract(tmp_path, contract)
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "test setup files")

        result = small_init_workflow(project_dir=tmp_path, workflow_id=story_id)

        assert result.get("code") != "blocked_not_on_main", (
            f"Without trunk config, on 'main', init must not be blocked by branch. Got: {result}"
        )

    def test_large_default_git_derived_trunk_still_works(self, tmp_path: Path) -> None:
        """Without config, the git-derived default 'main' is still the trunk for large."""
        story_id = "ISSUE-225"
        _init_git_repo(tmp_path, branch="main")
        _write_backlog_file(tmp_path, story_id)
        contract = _make_contract(story_id, "large-story")
        _write_contract(tmp_path, contract)
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "test setup files")

        result = large_init_workflow(project_dir=tmp_path, workflow_id=story_id)

        assert result.get("code") != "blocked_not_on_main", (
            f"Without trunk config, on 'main', large init must not be blocked by branch. Got: {result}"
        )
