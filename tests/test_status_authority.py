"""
Tests for ISSUE-227 — User-Set Status Is Authoritative.

Covers:
  Part 1: CLI set/set-terminal tags user changes as source=manual by default,
          so the existing source-guard protects them from derivation overwrite.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from status import (
    sync_parent_status,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATUS_SCRIPT = str(_REPO_ROOT / "scripts" / "status.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frontmatter_file(path: Path, frontmatter: dict, body: str = "## Description\nTest item.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, default_flow_style=False)
    path.write_text(f"---\n{fm_text}---\n\n{body}", encoding="utf-8")
    return path


def _read_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8").lstrip("﻿")
    parts = raw.split("---", 2)
    assert len(parts) >= 3, f"No valid frontmatter in {path}"
    return yaml.safe_load(parts[1])


def _setup_project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".sweetclaude" / "metrics").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sweetclaude" / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sweetclaude" / "product" / "backlog").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sweetclaude" / "product" / "roadmap").mkdir(parents=True, exist_ok=True)
    privacy_path = tmp_path / ".sweetclaude" / "artifact-privacy.yaml"
    privacy_path.write_text(yaml.safe_dump({
        "categories": {"product": {"base_path": ".sweetclaude/product"}},
    }))
    return tmp_path


def _make_issue(project_dir: Path, rel_path: str, item_id: str, status: str,
                extra: dict | None = None) -> Path:
    """Create an enhancement-type issue file with valid schema."""
    path = project_dir / rel_path
    fm: dict = {
        "id": item_id,
        "title": f"Test issue {item_id}",
        "type": "enhancement",
        "status": status,
        "created": "2026-06-26",
    }
    if extra:
        fm.update(extra)
    _frontmatter_file(path, fm)
    return path


def _make_epic(project_dir: Path, rel_path: str, epic_id: str, status: str,
               milestone_id: str = "MS-01", extra: dict | None = None) -> Path:
    """Create an epic file with valid schema (epic requires milestone field)."""
    path = project_dir / rel_path
    fm: dict = {
        "id": epic_id,
        "title": f"Test epic {epic_id}",
        "type": "epic",
        "status": status,
        "created": "2026-06-26",
        "milestone": milestone_id,
    }
    if extra:
        fm.update(extra)
    _frontmatter_file(path, fm)
    return path


def _make_milestone(project_dir: Path, rel_path: str, ms_id: str, status: str,
                    extra: dict | None = None) -> Path:
    """Create a milestone file with valid schema (milestone requires target_release field)."""
    path = project_dir / rel_path
    fm: dict = {
        "id": ms_id,
        "title": f"Test milestone {ms_id}",
        "type": "milestone",
        "status": status,
        "created": "2026-06-26",
        "target_release": "v1.0",
    }
    if extra:
        fm.update(extra)
    _frontmatter_file(path, fm)
    return path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _STATUS_SCRIPT] + args,
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# TestUserChangeTaggedManual (Part 1)
# ---------------------------------------------------------------------------

class TestUserChangeTaggedManual:
    """CLI set and set-terminal must write source=manual when --source is omitted."""

    def test_cli_set_no_source_writes_manual(self, tmp_path):
        """set with no --source must record source: manual in frontmatter."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_issue(project_dir, "backlog/ISSUE-301-test.md", "ISSUE-301", "new")

        result = _run_cli([
            "set",
            "--file", str(path),
            "--status", "active",
            "--actor", "test",
            "--project-dir", str(project_dir),
        ])
        assert result.returncode == 0, f"CLI failed: {result.stdout} {result.stderr}"

        fm = _read_frontmatter(path)
        assert fm.get("source") == "manual", (
            f"Expected source=manual after CLI set with no --source, got: {fm.get('source')!r}"
        )

    def test_cli_set_terminal_no_source_writes_manual(self, tmp_path):
        """set-terminal with no --source must record source: manual in the moved file."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_issue(
            project_dir, "roadmap/issues/ISSUE-302-test.md", "ISSUE-302", "active"
        )

        result = _run_cli([
            "set-terminal",
            "--file", str(path),
            "--status", "declined",
            "--actor", "test",
            "--project-dir", str(project_dir),
            "--allow-missing-evidence",
        ])
        assert result.returncode == 0, f"CLI failed: {result.stdout} {result.stderr}"

        # declined from roadmap/issues goes to roadmap/issues/done (terminal dir)
        candidates = [
            project_dir / "roadmap" / "issues" / "done" / "ISSUE-302-test.md",
            project_dir / "roadmap" / "issues" / "archived" / "ISSUE-302-test.md",
        ]
        moved = next((p for p in candidates if p.exists()), None)
        assert moved is not None, (
            f"Moved file not found after set-terminal declined; searched: {candidates}"
        )

        fm = _read_frontmatter(moved)
        assert fm.get("source") == "manual", (
            f"Expected source=manual after CLI set-terminal with no --source, got: {fm.get('source')!r}"
        )

    def test_cli_set_explicit_source_auto_still_records_auto(self, tmp_path):
        """Passing --source auto must record source: auto (override still works)."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_issue(project_dir, "backlog/ISSUE-303-test.md", "ISSUE-303", "new")

        result = _run_cli([
            "set",
            "--file", str(path),
            "--status", "active",
            "--actor", "test",
            "--project-dir", str(project_dir),
            "--source", "auto",
        ])
        assert result.returncode == 0, f"CLI failed: {result.stdout} {result.stderr}"

        fm = _read_frontmatter(path)
        assert fm.get("source") == "auto", (
            f"Expected source=auto when --source auto passed, got: {fm.get('source')!r}"
        )

    def test_cli_set_explicit_source_manual_records_manual(self, tmp_path):
        """Passing --source manual explicitly must also record source: manual."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_issue(project_dir, "backlog/ISSUE-304-test.md", "ISSUE-304", "new")

        result = _run_cli([
            "set",
            "--file", str(path),
            "--status", "active",
            "--actor", "test",
            "--project-dir", str(project_dir),
            "--source", "manual",
        ])
        assert result.returncode == 0, f"CLI failed: {result.stdout} {result.stderr}"

        fm = _read_frontmatter(path)
        assert fm.get("source") == "manual", (
            f"Expected source=manual when --source manual passed, got: {fm.get('source')!r}"
        )


# ---------------------------------------------------------------------------
# TestManualProtectedFromDerivation (Part 1 effect)
# ---------------------------------------------------------------------------

class TestManualProtectedFromDerivation:
    """sync_parent_status must not overwrite a file whose source=manual."""

    def test_sync_does_not_overwrite_manual_milestone(self, tmp_path):
        """Milestone with source=manual and status=active is not regressed when children are new."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_milestone(
            project_dir,
            "roadmap/milestones/MS-11-test.md",
            "MS-11", "active",
            extra={"source": "manual"},
        )

        result = sync_parent_status(
            str(path), ["new", "new"], "test", project_dir=str(project_dir)
        )

        assert result is False, (
            "sync_parent_status must return False for source=manual files"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "active", (
            f"source=manual file must not be modified; status changed to {fm['status']!r}"
        )

    def test_sync_does_not_overwrite_manual_epic(self, tmp_path):
        """Epic with source=manual and status=active is not regressed when children are new."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_epic(
            project_dir,
            "roadmap/epics/EP-11-test.md",
            "EP-11", "active",
            extra={"source": "manual"},
        )

        result = sync_parent_status(
            str(path), ["new", "new"], "test", project_dir=str(project_dir)
        )

        assert result is False, (
            "sync_parent_status must return False for source=manual epic"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "active", (
            f"source=manual epic must not be modified; got {fm['status']!r}"
        )

