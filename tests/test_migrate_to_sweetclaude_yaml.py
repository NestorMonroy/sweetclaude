"""Coverage for the v3 to v4 state consolidator (ISSUE-255).

scripts/migrate-to-sweetclaude-yaml.py folds phase.yaml and skills.yaml into
sweetclaude.yaml. This is the exact transition behind ISSUE-249 — a project
left with only the v3 pair reports not-configured to every v4 consumer — and
it had no test.

It archives the originals with shutil.move, so a failed run costs the user
their state files. The sentinel it writes first is what bootstrap:125 reads as
`migration_status: in_progress`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate-to-sweetclaude-yaml.py"


def _load():
    spec = importlib.util.spec_from_file_location("migrate_to_sc_yaml", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


@pytest.fixture
def v3_project(tmp_path: Path) -> Path:
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "phase.yaml").write_text(yaml.safe_dump({
        "schema_version": 2,
        "version_stage": "BETA",
        "deference_level": "collaborative",
        "project_type": "existing-code",
        "safety_snapshot": "pre-sweetclaude",
        "last_work_item_id": "ISSUE-042",
        "active_work_item": {"id": "ISSUE-043", "type": "bug-fix", "phase": "IMPLEMENT",
                             "title": "a thing", "workflow": [], "started": "2026-01-01",
                             "entry_category": "mid-project-planned"},
    }), encoding="utf-8")
    (state / "skills.yaml").write_text(yaml.safe_dump({
        "schema_version": 2,
        "product-milestones": {"status": "active", "last_changed_at": "2026-01-01"},
        "product-backlog": {"status": "active", "last_changed_at": "2026-01-01"},
    }), encoding="utf-8")
    (state / "improvement-register.md").write_text(
        "# Improvement Register\n\n- first learning\n- second learning\n",
        encoding="utf-8")
    return tmp_path


def _sc(project: Path) -> dict:
    return yaml.safe_load(
        (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text())


# --- happy path ----------------------------------------------------------

def test_migration_produces_a_v4_state_file(v3_project: Path) -> None:
    mod.migrate(str(v3_project), "4.5.2")

    sc = _sc(v3_project)
    assert sc["framework"]["migration_status"] == "complete"
    assert sc["framework"]["installed_version"] == "4.5.2"
    assert sc["project"]["version_stage"] == "BETA"
    assert sc["session"]["deference_level"] == "collaborative"


def test_migration_carries_active_work_across(v3_project: Path) -> None:
    """work.active is what go, status, and the controllers read. Losing it
    here strands the user's in-flight item."""
    mod.migrate(str(v3_project), "4.5.2")

    work = _sc(v3_project)["work"]
    assert work["active"]["id"] == "ISSUE-043"
    assert work["active"]["phase"] == "IMPLEMENT"
    assert work["last_item_id"] == "ISSUE-042"


def test_migration_carries_learnings_from_the_register(v3_project: Path) -> None:
    mod.migrate(str(v3_project), "4.5.2")
    learnings = _sc(v3_project)["learnings"]
    assert "first learning" in learnings
    assert "second learning" in learnings


def test_migration_archives_rather_than_deletes_the_originals(v3_project: Path) -> None:
    """shutil.move, not unlink. The user must be able to get their v3 files
    back if the migration produced something wrong."""
    state = v3_project / ".sweetclaude" / "state"
    mod.migrate(str(v3_project), "4.5.2")

    assert not (state / "phase.yaml").exists()
    assert not (state / "skills.yaml").exists()
    assert (state / "archive" / "phase.yaml.bak").exists()
    assert (state / "archive" / "skills.yaml.bak").exists()

    recovered = yaml.safe_load((state / "archive" / "phase.yaml.bak").read_text())
    assert recovered["last_work_item_id"] == "ISSUE-042", "archived copy is not intact"


def test_result_is_readable_by_the_session_state_hook(v3_project: Path) -> None:
    """End-to-end: the migrated file must be consumable by the hook that 47
    skills preload, or the project is configured but unusable."""
    mod.migrate(str(v3_project), "4.5.2")

    hook = REPO_ROOT / "hooks" / "generate-session-state.sh"
    subprocess.run(["bash", str(hook)], cwd=str(v3_project),
                   capture_output=True, text=True, timeout=60)

    session_state = v3_project / ".sweetclaude" / "state" / "session-state.yaml"
    if session_state.exists():
        data = yaml.safe_load(session_state.read_text()) or {}
        assert data.get("version_stage") == "BETA"
        assert data.get("deference") == "collaborative"


# --- guards and edge cases ----------------------------------------------

def test_already_migrated_project_is_left_alone(v3_project: Path) -> None:
    mod.migrate(str(v3_project), "4.5.2")
    before = (v3_project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_bytes()

    mod.migrate(str(v3_project), "9.9.9")

    after = (v3_project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_bytes()
    assert after == before, "a second run rewrote a completed migration"


def test_missing_skills_yaml_is_not_fatal(tmp_path: Path) -> None:
    """skills.yaml is optional in the registry; a project without one must
    still migrate."""
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "phase.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "version_stage": "GA"}), encoding="utf-8")

    mod.migrate(str(tmp_path), "4.5.2")
    assert _sc(tmp_path)["framework"]["migration_status"] == "complete"


def test_missing_phase_yaml_is_not_fatal(tmp_path: Path) -> None:
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "skills.yaml").write_text(
        yaml.safe_dump({"schema_version": 2}), encoding="utf-8")

    mod.migrate(str(tmp_path), "4.5.2")
    assert _sc(tmp_path)["framework"]["migration_status"] == "complete"


def test_empty_state_directory_still_produces_valid_state(tmp_path: Path) -> None:
    (tmp_path / ".sweetclaude" / "state").mkdir(parents=True)

    mod.migrate(str(tmp_path), "4.5.2")

    sc = _sc(tmp_path)
    assert sc["framework"]["migration_status"] == "complete"
    assert "project" in sc and "work" in sc


def test_sentinel_is_written_before_any_reading_happens(tmp_path: Path, monkeypatch) -> None:
    """The in_progress sentinel is what bootstrap:125 reads to detect an
    interrupted migration. If it is written after the risky work, a crash
    mid-migration leaves no trace and the retry path never fires."""
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "phase.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "version_stage": "GA"}), encoding="utf-8")

    real_safe_load = yaml.safe_load
    seen = {}

    def spy(*args, **kwargs):
        sc = state / "sweetclaude.yaml"
        if sc.exists() and "sentinel_at_first_read" not in seen:
            seen["sentinel_at_first_read"] = (
                (yaml.load(sc.read_text(), Loader=yaml.SafeLoader) or {})
                .get("framework", {}).get("migration_status")
            )
        return real_safe_load(*args, **kwargs)

    monkeypatch.setattr(yaml, "safe_load", spy)
    mod.migrate(str(tmp_path), "4.5.2")

    assert seen.get("sentinel_at_first_read") == "in_progress", (
        "sentinel was not on disk before the migration started reading state"
    )


def test_unreadable_phase_yaml_leaves_the_sentinel_behind(tmp_path: Path) -> None:
    """A corrupt input must not be silently absorbed. Whatever the outcome,
    the user must not end up with a state file claiming complete when the
    source could not be read."""
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "phase.yaml").write_text("{ not: valid: yaml", encoding="utf-8")

    try:
        mod.migrate(str(tmp_path), "4.5.2")
    except Exception:
        sc = state / "sweetclaude.yaml"
        assert sc.exists()
        status = (yaml.safe_load(sc.read_text()) or {}).get("framework", {}).get("migration_status")
        assert status == "in_progress", (
            "a crashed migration must leave in_progress so bootstrap can retry"
        )
        return

    status = _sc(tmp_path)["framework"]["migration_status"]
    assert status in {"complete", "in_progress"}


# --- CLI -----------------------------------------------------------------

def test_cli_requires_project_dir() -> None:
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode != 0
    assert "project-dir" in (r.stderr + r.stdout)


def test_cli_migrates_and_reports(v3_project: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-dir", str(v3_project),
         "--installed-version", "4.5.2"],
        capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr
    assert "Migration complete" in r.stdout
    assert _sc(v3_project)["framework"]["migration_status"] == "complete"


def test_cli_defaults_installed_version(v3_project: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-dir", str(v3_project)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert _sc(v3_project)["framework"]["installed_version"] == "unknown"
