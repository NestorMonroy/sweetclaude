#!/usr/bin/env python3
"""Tests for init_workflow precondition checks (ISSUE-221).

Verifies that both small_story_controller and large_story_controller
refuse to init when:
- not on the main branch
- working tree has uncommitted changes
- another workflow is already active (cross-controller)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from small_story_controller import (
    _check_init_preconditions as small_check,
    _detect_main_branch as small_detect_main,
    _is_git_repo as small_is_git_repo,
)
from large_story_controller import (
    _check_init_preconditions as large_check,
    _detect_main_branch as large_detect_main,
    _is_git_repo as large_is_git_repo,
)


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


def _write_workflow(path: Path, workflow_id: str, owner: str, status: str = "define") -> None:
    workflows_dir = path / ".sweetclaude" / "state" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / f"{workflow_id}.yaml").write_text(
        yaml.safe_dump({
            "workflow_id": workflow_id,
            "state_owner": owner,
            "requires_success_criteria_contract": True,
            "status": status,
        })
    )
    _git(path, "add", "-A")
    _git(path, "commit", "-m", f"add workflow {workflow_id}")


class TestIsGitRepo:
    def test_git_repo(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        assert small_is_git_repo(tmp_path) is True
        assert large_is_git_repo(tmp_path) is True

    def test_not_git_repo(self, tmp_path: Path) -> None:
        assert small_is_git_repo(tmp_path) is False
        assert large_is_git_repo(tmp_path) is False


class TestDetectMainBranch:
    def test_detects_main(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="main")
        assert small_detect_main(tmp_path) == "main"
        assert large_detect_main(tmp_path) == "main"

    def test_detects_master(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="master")
        assert small_detect_main(tmp_path) == "master"
        assert large_detect_main(tmp_path) == "master"

    def test_fallback_to_main(self, tmp_path: Path) -> None:
        assert small_detect_main(tmp_path) == "main"


class TestNotOnMain:
    def test_blocks_on_feature_branch(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _git(tmp_path, "checkout", "-b", "feature/foo")
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_not_on_main"
        assert "feature/foo" in result["message"]

    def test_blocks_on_feature_branch_large(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _git(tmp_path, "checkout", "-b", "feature/foo")
        result = large_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_not_on_main"

    def test_passes_on_main(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        result = small_check(tmp_path)
        assert result is None

    def test_passes_on_master(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, branch="master")
        result = small_check(tmp_path)
        assert result is None

    def test_blocks_detached_head(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
        _git(tmp_path, "checkout", commit)
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_not_on_main"
        assert "(detached)" in result["message"]


class TestDirtyTree:
    def test_blocks_uncommitted_changes(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("dirty\n")
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_dirty_tree"

    def test_blocks_staged_changes(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "staged.txt").write_text("staged\n")
        _git(tmp_path, "add", "staged.txt")
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_dirty_tree"

    def test_passes_clean_tree(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        result = small_check(tmp_path)
        assert result is None

    def test_blocks_uncommitted_large(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("dirty\n")
        result = large_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_dirty_tree"


class TestInflightWorkflow:
    def test_blocks_active_small_workflow(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _write_workflow(tmp_path, "ISSUE-100", "small_story_controller")
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_inflight_workflow"
        assert "ISSUE-100" in result["message"]

    def test_blocks_active_large_workflow_from_small(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _write_workflow(tmp_path, "ISSUE-200", "large_story_controller")
        result = small_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_inflight_workflow"
        assert "ISSUE-200" in result["message"]
        assert "large_story_controller" in result["message"]

    def test_blocks_active_small_workflow_from_large(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _write_workflow(tmp_path, "ISSUE-100", "small_story_controller")
        result = large_check(tmp_path)
        assert result is not None
        assert result["code"] == "blocked_inflight_workflow"
        assert "small_story_controller" in result["message"]

    def test_ignores_completed_workflow(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _write_workflow(tmp_path, "ISSUE-100", "small_story_controller", status="complete")
        result = small_check(tmp_path)
        assert result is None

    def test_passes_no_workflows(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        result = small_check(tmp_path)
        assert result is None


class TestEmptyRepo:
    def test_passes_git_repo_with_no_commits(self, tmp_path: Path) -> None:
        _git(tmp_path, "init")
        result = small_check(tmp_path)
        assert result is None

    def test_passes_git_repo_with_no_commits_large(self, tmp_path: Path) -> None:
        _git(tmp_path, "init")
        result = large_check(tmp_path)
        assert result is None


class TestNonGitRepo:
    def test_passes_non_git_directory(self, tmp_path: Path) -> None:
        result = small_check(tmp_path)
        assert result is None

    def test_passes_non_git_directory_large(self, tmp_path: Path) -> None:
        result = large_check(tmp_path)
        assert result is None
