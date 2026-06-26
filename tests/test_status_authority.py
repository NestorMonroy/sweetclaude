"""
Tests for ISSUE-227 — User-Set Status Is Authoritative.

Covers:
  Part 1: CLI set/set-terminal tags user changes as source=manual by default.
  Part 2: sync_parent_status does not silently regress milestone/epic parents;
          doctor check_derived_status emits report-only (not auto) for milestone/epic regressions.
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


# ---------------------------------------------------------------------------
# TestNoSilentRegressionForParents (Part 2 — milestone/epic, source: auto)
# ---------------------------------------------------------------------------

class TestNoSilentRegressionForParents:
    """sync_parent_status must block regressions for milestone/epic parents with source=auto.

    Regression predicate (design doc):
    - derived rank < stored rank (e.g. active->new, done->new, done->active), OR
    - stored == on-hold (deliberate pause; must never be moved off)
    Forward progressions (derived rank > stored rank) must still be applied.
    """

    # --- Regression cases: must NOT apply ---

    def test_milestone_active_to_new_is_blocked(self, tmp_path):
        """Milestone source=auto status=active, children all new → derived=new. Must stay active."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_milestone(
            project_dir,
            "roadmap/milestones/MS-21-test.md",
            "MS-21", "active",
        )

        result = sync_parent_status(
            str(path), ["new", "new"], "test", project_dir=str(project_dir)
        )

        assert result is False, (
            "Regression active→new must not be applied to a milestone (should return False)"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "active", (
            f"Milestone status must remain active after blocked regression; got {fm['status']!r}"
        )

    def test_milestone_done_to_new_is_blocked(self, tmp_path):
        """Milestone source=auto status=done, child new → derived=new. Must stay done."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_milestone(
            project_dir,
            "roadmap/milestones/MS-22-test.md",
            "MS-22", "done",
        )

        result = sync_parent_status(
            str(path), ["new"], "test", project_dir=str(project_dir)
        )

        assert result is False, (
            "Regression done→new must not be applied to a milestone (should return False)"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "done", (
            f"Milestone status must remain done after blocked regression; got {fm['status']!r}"
        )

    def test_milestone_on_hold_not_moved_to_active(self, tmp_path):
        """Milestone source=auto status=on-hold, child active → derived=active. on-hold is sticky."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_milestone(
            project_dir,
            "roadmap/milestones/MS-23-test.md",
            "MS-23", "on-hold",
        )

        result = sync_parent_status(
            str(path), ["active"], "test", project_dir=str(project_dir)
        )

        assert result is False, (
            "on-hold milestone must not be moved to active by sync (should return False)"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "on-hold", (
            f"on-hold milestone must remain on-hold; got {fm['status']!r}"
        )

    @pytest.mark.parametrize("stored,child_statuses,description,epic_id,ms_id", [
        ("active", ["new", "new"], "active->new is a regression",   "EP-24", "MS-24"),
        ("done",   ["new"],        "done->new is a regression",     "EP-25", "MS-25"),
        ("on-hold", ["active"],   "on-hold is sticky",              "EP-26", "MS-26"),
    ])
    def test_epic_regression_blocked(self, tmp_path, stored, child_statuses,
                                     description, epic_id, ms_id):
        """Epic source=auto regressions are also blocked (parametrized)."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_epic(
            project_dir,
            f"roadmap/epics/{epic_id}-test.md",
            epic_id, stored,
            milestone_id=ms_id,
        )

        result = sync_parent_status(
            str(path), child_statuses, "test", project_dir=str(project_dir)
        )

        assert result is False, (
            f"Epic regression must not be applied: {description}; got result={result}"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == stored, (
            f"Epic status must remain {stored!r} after blocked regression; "
            f"got {fm['status']!r}. Case: {description}"
        )

    # --- Forward progression case: MUST apply ---

    def test_milestone_forward_progression_is_applied(self, tmp_path):
        """Milestone source=auto status=new, child active → derived=active. Forward must be applied."""
        project_dir = _setup_project_dir(tmp_path)
        path = _make_milestone(
            project_dir,
            "roadmap/milestones/MS-27-test.md",
            "MS-27", "new",
        )

        result = sync_parent_status(
            str(path), ["active"], "test", project_dir=str(project_dir)
        )

        assert result is True, (
            "Forward progression new→active must be applied to milestone (should return True)"
        )
        fm = _read_frontmatter(path)
        assert fm["status"] == "active", (
            f"Milestone must be updated to active after forward progression; got {fm['status']!r}"
        )


# ---------------------------------------------------------------------------
# TestDoctorOffersNotAutoForParentRegression (Part 2 — doctor)
# ---------------------------------------------------------------------------

class TestDoctorOffersNotAutoForParentRegression:
    """doctor check_derived_status must not emit fix_type=auto for milestone/epic regressions.

    For a milestone/epic parent with source=auto whose children derive a
    regression (derived rank < stored rank, or stored=on-hold), the finding
    must be fix_type != 'auto' (report-only or equivalent offer).

    For a forward divergence, auto behavior may remain.
    """

    @pytest.fixture(autouse=True)
    def fake_home(self, tmp_path, monkeypatch):
        """Minimal fake home for doctor tests (mirrors test_doctor.py pattern)."""
        home = tmp_path / "home"
        claude_dir = home / ".claude"

        hooks_dir = claude_dir / "hooks" / "sweetclaude"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "hooks.json").write_text(json.dumps({"hooks": []}))

        rules_dir = claude_dir / "rules" / "sweetclaude"
        rules_dir.mkdir(parents=True)
        for rf in ["interaction-model.md", "phase-gates.md", "tdd-levels.md"]:
            (rules_dir / rf).write_text(f"# {rf}\nPlaceholder content.")

        (claude_dir / "settings.json").write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
        }))

        plugins_dir = claude_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "plugins": {
                "sweetclaude/sweetclaude": [{"version": "4.0.8-beta"}],
            },
        }))

        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: home))
        return home

    def _build_state(self, tmp_path, roadmap_files):
        """Build a ProjectState using the test_doctor build_fixture helper."""
        _tests_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        if _tests_dir not in sys.path:
            sys.path.insert(0, _tests_dir)

        from test_doctor import build_fixture
        from doctor import build_project_state

        project_dir = build_fixture(tmp_path, overrides={"roadmap_files": roadmap_files})
        return build_project_state(project_dir)

    def test_milestone_regression_finding_is_not_auto(self, tmp_path):
        """Milestone source=auto status=active, children all new → regression.
        Doctor finding must NOT be fix_type='auto'."""
        from doctor import check_derived_status

        state = self._build_state(tmp_path, roadmap_files=[
            {
                "name": "milestones/MS-31-test.md",
                "frontmatter": {
                    "id": "MS-31",
                    "title": "D1 Milestone",
                    "type": "milestone",
                    "status": "active",
                    "created": "2026-06-26",
                    "target_release": "v1.0",
                    # source absent = defaults to auto in doctor logic
                },
            },
            {
                "name": "epics/EP-31-test.md",
                "frontmatter": {
                    "id": "EP-31",
                    "title": "D1 Epic",
                    "type": "epic",
                    "status": "new",
                    "created": "2026-06-26",
                    "milestone": "MS-31",
                },
            },
        ])

        findings = check_derived_status(state)
        ms_findings = [f for f in findings if "MS-31" in f.id]
        assert len(ms_findings) >= 1, (
            "Expected at least one finding for MS-31 (active→new regression)"
        )
        for f in ms_findings:
            assert f.fix_type != "auto", (
                f"Milestone regression finding must not be fix_type='auto'; "
                f"got fix_type={f.fix_type!r} for finding {f.id}"
            )

    def test_epic_regression_finding_is_not_auto(self, tmp_path):
        """Epic source=auto status=active, children all new → regression.
        Doctor finding must NOT be fix_type='auto'."""
        from doctor import check_derived_status

        state = self._build_state(tmp_path, roadmap_files=[
            {
                "name": "epics/EP-32-test.md",
                "frontmatter": {
                    "id": "EP-32",
                    "title": "D2 Epic",
                    "type": "epic",
                    "status": "active",
                    "created": "2026-06-26",
                    "milestone": "MS-32",
                    # source absent = defaults to auto in doctor logic
                },
            },
            {
                "name": "issues/ISSUE-320-test.md",
                "frontmatter": {
                    "id": "ISSUE-320",
                    "title": "D2 Issue",
                    "type": "enhancement",
                    "status": "new",
                    "created": "2026-06-26",
                    "epic": "EP-32",
                },
            },
        ])

        findings = check_derived_status(state)
        ep_findings = [f for f in findings if "EP-32" in f.id]
        assert len(ep_findings) >= 1, (
            "Expected at least one finding for EP-32 (active→new regression)"
        )
        for f in ep_findings:
            assert f.fix_type != "auto", (
                f"Epic regression finding must not be fix_type='auto'; "
                f"got fix_type={f.fix_type!r} for finding {f.id}"
            )

    def test_milestone_done_to_new_regression_is_not_auto(self, tmp_path):
        """Milestone source=auto status=done, epic child new → regression done→new.
        Doctor finding must NOT be fix_type='auto'."""
        from doctor import check_derived_status

        state = self._build_state(tmp_path, roadmap_files=[
            {
                "name": "milestones/MS-33-test.md",
                "frontmatter": {
                    "id": "MS-33",
                    "title": "D3 Milestone",
                    "type": "milestone",
                    "status": "done",
                    "created": "2026-06-26",
                    "target_release": "v2.0",
                },
            },
            {
                "name": "epics/EP-33-test.md",
                "frontmatter": {
                    "id": "EP-33",
                    "title": "D3 Epic",
                    "type": "epic",
                    "status": "new",
                    "created": "2026-06-26",
                    "milestone": "MS-33",
                },
            },
            {
                "name": "issues/ISSUE-330-test.md",
                "frontmatter": {
                    "id": "ISSUE-330",
                    "title": "D3 Issue",
                    "type": "enhancement",
                    "status": "new",
                    "created": "2026-06-26",
                    "epic": "EP-33",
                },
            },
        ])

        findings = check_derived_status(state)
        ms_findings = [f for f in findings if "MS-33" in f.id]
        assert len(ms_findings) >= 1, (
            "Expected at least one finding for MS-33 (done→new regression)"
        )
        for f in ms_findings:
            assert f.fix_type != "auto", (
                f"Milestone done→new regression finding must not be fix_type='auto'; "
                f"got fix_type={f.fix_type!r} for finding {f.id}"
            )

    def test_epic_forward_divergence_may_remain_auto(self, tmp_path):
        """Epic source=auto status=new, children active → forward divergence.
        Current auto behavior for forward progressions may remain (fix_type=auto is acceptable here).
        Test documents that forward divergences still surface a finding of some kind."""
        from doctor import check_derived_status

        state = self._build_state(tmp_path, roadmap_files=[
            {
                "name": "epics/EP-34-test.md",
                "frontmatter": {
                    "id": "EP-34",
                    "title": "D4 Epic",
                    "type": "epic",
                    "status": "new",
                    "created": "2026-06-26",
                    "milestone": "MS-34",
                },
            },
            {
                "name": "issues/ISSUE-340-test.md",
                "frontmatter": {
                    "id": "ISSUE-340",
                    "title": "D4 Issue",
                    "type": "enhancement",
                    "status": "active",
                    "created": "2026-06-26",
                    "epic": "EP-34",
                },
            },
        ])

        findings = check_derived_status(state)
        ep_findings = [f for f in findings if "EP-34" in f.id]
        assert len(ep_findings) >= 1, (
            "Expected at least one finding for EP-34 (forward divergence new→active)"
        )
        for f in ep_findings:
            assert f.fix_type in ("auto", "report-only", "prompted"), (
                f"Unknown fix_type {f.fix_type!r} for EP-34 forward finding"
            )
