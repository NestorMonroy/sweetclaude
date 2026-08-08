"""End-to-end snapshot, migrate, rollback coverage (ISSUE-253).

This is the path bootstrap can reach without asking the user
(skills/bootstrap/SKILL.md lines 106, 117, and 125). If migration corrupts a
project, rollback is the only way back, so rollback must be proven to restore
byte-identical state rather than assumed to.

Every fixture is a self-contained git repo under tmp_path. MigrationRunner
scopes all git calls with `git -C <project_dir>`, so `git reset --hard` during
rollback cannot touch the repo these tests run from.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))

from runner import MigrationRunner, SnapshotInfo  # noqa: E402

REGISTRY = REPO_ROOT / "config" / "migration-registry.yaml"


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args],
                          capture_output=True, text=True, timeout=30)


def _tree_digest(root: Path) -> dict[str, str]:
    """Content hash of every file under root, excluding git internals and the
    backup tarballs the snapshot itself creates."""
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/backups/" in f"/{rel}":
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def v1_project(tmp_path: Path) -> Path:
    """A committed git project carrying v1 state on disk.

    `.sweetclaude/` is gitignored, matching a real project. That separation
    matters: it means the tarball is the ONLY thing that can restore state
    files, and `git reset --hard` is the only thing that can restore tracked
    content. If both covered the same files, a rollback test would still pass
    with either mechanism broken.
    """
    project = tmp_path / "proj"
    state = project / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (project / ".gitignore").write_text(".sweetclaude/\n", encoding="utf-8")

    (state / "phase.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "phase": "IMPLEMENT",
        "work_type": "refactor",
        "deference_level": "collaborative",
        "project_type": "existing-code",
        "safety_snapshot": "pre-sweetclaude",
    }), encoding="utf-8")
    (state / "skills.yaml").write_text(
        yaml.safe_dump({"schema_version": 1}), encoding="utf-8")
    (project / "README.md").write_text("tracked content\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q", "-b", "main", str(project)],
                   capture_output=True, text=True, timeout=30)
    _git(project, "config", "user.email", "test@test.invalid")
    _git(project, "config", "user.name", "Test")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "initial")
    return project


def _runner(project: Path) -> MigrationRunner:
    return MigrationRunner(project_dir=str(project), registry_path=str(REGISTRY))


# --- snapshot ------------------------------------------------------------

def test_snapshot_creates_verified_tarball_and_git_tag(v1_project: Path) -> None:
    snap = _runner(v1_project).create_snapshot()

    assert Path(snap.tarball_path).exists(), "tarball must exist on disk"
    assert snap.tarball_verified is True, "runner must verify the tarball it wrote"
    assert snap.git_tag_created is True
    assert _git(v1_project, "rev-parse", "--verify", snap.git_tag).returncode == 0
    assert ".sweetclaude" in snap.paths_in_tarball


def test_snapshot_verifies_clean(v1_project: Path) -> None:
    runner = _runner(v1_project)
    ok, reason = runner.verify_snapshot(runner.create_snapshot())
    assert ok, reason


def test_verify_snapshot_rejects_a_deleted_tarball(v1_project: Path) -> None:
    """The guard that stops rollback from running against a missing archive."""
    runner = _runner(v1_project)
    snap = runner.create_snapshot()
    Path(snap.tarball_path).unlink()

    ok, reason = runner.verify_snapshot(snap)
    assert not ok
    assert reason


def test_snapshot_in_non_git_project_still_produces_a_tarball(tmp_path: Path) -> None:
    """Not every project is a git repo. Snapshot must not require one."""
    project = tmp_path / "nogit"
    (project / ".sweetclaude" / "state").mkdir(parents=True)
    (project / ".sweetclaude" / "state" / "skills.yaml").write_text(
        yaml.safe_dump({"schema_version": 1}), encoding="utf-8")

    snap = _runner(project).create_snapshot()
    assert Path(snap.tarball_path).exists()
    assert snap.git_tag_created is False


# --- the contract that matters ------------------------------------------

def test_rollback_restores_the_project_byte_identical(v1_project: Path) -> None:
    runner = _runner(v1_project)

    before = _tree_digest(v1_project)
    snap = runner.create_snapshot()

    results = runner.run()
    assert results, "migration should have had work to do on a v1 project"
    after_migrate = _tree_digest(v1_project)
    assert after_migrate != before, (
        "migration changed nothing, so this test would pass even if rollback "
        "were a no-op — fixture is not exercising the path"
    )

    ok, reason = runner.rollback(snap)
    assert ok, f"rollback failed: {reason}"

    assert _tree_digest(v1_project) == before, (
        "rollback did not restore the project to its pre-migration content"
    )


def test_rollback_restores_gitignored_state_through_the_tarball(v1_project: Path) -> None:
    """`.sweetclaude/` is gitignored, so `git reset --hard` cannot bring it
    back. Only the tarball can. This fails if tar extraction is skipped."""
    runner = _runner(v1_project)
    phase = v1_project / ".sweetclaude" / "state" / "phase.yaml"

    assert _git(v1_project, "check-ignore", "-q", str(phase)).returncode == 0, (
        "fixture invalid: .sweetclaude/ must be gitignored for this test to "
        "isolate the tarball leg of rollback"
    )

    before = phase.read_bytes()
    snap = runner.create_snapshot()
    runner.run()
    assert phase.read_bytes() != before, "migration did not change the state file"

    ok, reason = runner.rollback(snap)
    assert ok, f"rollback failed: {reason}"
    assert phase.read_bytes() == before, "tarball did not restore gitignored state"


def test_rollback_restores_tracked_content_through_git(v1_project: Path) -> None:
    """Tracked content outside `.sweetclaude/` is not in the tarball, so only
    `git reset --hard <tag>` can restore it. This fails if the reset is
    skipped."""
    runner = _runner(v1_project)
    tracked = v1_project / "README.md"

    before = tracked.read_bytes()
    snap = runner.create_snapshot()

    tracked.write_text("clobbered after snapshot\n", encoding="utf-8")
    _git(v1_project, "add", "-A")
    _git(v1_project, "commit", "-q", "-m", "post-snapshot change")

    ok, reason = runner.rollback(snap)
    assert ok, f"rollback failed: {reason}"
    assert tracked.read_bytes() == before, "git reset did not restore tracked content"


def test_rollback_restores_uncommitted_work(v1_project: Path) -> None:
    """Snapshot stashes uncommitted changes so `git reset --hard` cannot eat
    them. Rollback must put them back."""
    runner = _runner(v1_project)
    scratch = v1_project / "uncommitted.md"
    scratch.write_text("work in progress\n", encoding="utf-8")
    (v1_project / "README.md").write_text("locally edited\n", encoding="utf-8")

    before = _tree_digest(v1_project)
    snap = runner.create_snapshot()
    runner.run()

    ok, reason = runner.rollback(snap)
    assert ok, f"rollback failed: {reason}"
    assert _tree_digest(v1_project) == before, "uncommitted work was not restored"


def test_rollback_refuses_when_snapshot_cannot_be_verified(v1_project: Path) -> None:
    """Fail closed. A rollback that silently no-ops and reports success is
    worse than one that refuses."""
    runner = _runner(v1_project)
    snap = runner.create_snapshot()
    Path(snap.tarball_path).unlink()

    ok, reason = runner.rollback(snap)
    assert not ok
    assert "verification failed" in (reason or "")


def test_rollback_refuses_a_snapshot_pointing_at_a_missing_git_tag(v1_project: Path) -> None:
    runner = _runner(v1_project)
    snap = runner.create_snapshot()
    _git(v1_project, "tag", "-d", snap.git_tag)

    ok, reason = runner.rollback(snap)
    assert not ok, "rollback proceeded against a tag that no longer exists"
    assert reason


# --- migrate -------------------------------------------------------------

def test_migration_reaches_target_version(v1_project: Path) -> None:
    runner = _runner(v1_project)
    runner.run()

    phase = yaml.safe_load((v1_project / ".sweetclaude" / "state" / "phase.yaml").read_text())
    assert phase["schema_version"] == 2
    assert phase["active_work_item"]["type"] == "tech-debt"


def test_migration_is_idempotent(v1_project: Path) -> None:
    """Bootstrap line 125 retries a migration whose status was left failed.
    A second run over already-migrated files must not corrupt them."""
    runner = _runner(v1_project)
    runner.run()
    after_first = _tree_digest(v1_project)

    _runner(v1_project).run()
    assert _tree_digest(v1_project) == after_first, (
        "re-running migration over migrated files changed them"
    )


def test_plan_reports_work_without_touching_disk(v1_project: Path) -> None:
    runner = _runner(v1_project)
    before = _tree_digest(v1_project)

    plans = runner.plan()
    assert plans, "plan() found no work on a v1 project"
    assert _tree_digest(v1_project) == before, "plan() must be read-only"


def test_scan_drift_is_read_only_by_default(v1_project: Path) -> None:
    runner = _runner(v1_project)
    before = _tree_digest(v1_project)

    result = runner.scan_drift()
    assert isinstance(result, dict)
    assert _tree_digest(v1_project) == before, "scan_drift() must not write unless asked"
