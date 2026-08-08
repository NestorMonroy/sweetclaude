"""Coverage for runner.py internals (ISSUE-268).

ISSUE-253 covered the snapshot, migrate, and rollback path bootstrap reaches
unprompted. This covers what was left: the CLI surface, directory-entry
migrations, and the failure paths that build the recovery menu a user is
shown after a migration goes wrong.

Directory migrations need a registry that declares `type: directory`. The
shipped config/migration-registry.yaml has no such entry, so these tests bring
their own registry and handler modules — which also keeps them from depending
on whatever the shipped registry happens to contain.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
MIGRATIONS = REPO_ROOT / "scripts" / "migrations"
RUNNER_PY = MIGRATIONS / "runner.py"
sys.path.insert(0, str(MIGRATIONS))

from runner import MigrationRunner, RecoverableMigrationError  # noqa: E402


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUNNER_PY), *args],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    state = tmp_path / ".sweetclaude" / "state"
    state.mkdir(parents=True)
    (state / "sweetclaude.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "project": {"name": "fixture"}}),
        encoding="utf-8")
    (state / "phase.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "phase": "DESIGN", "work_type": "bug-fix"}),
        encoding="utf-8")
    return tmp_path


# --- CLI surface ---------------------------------------------------------

def test_cli_dry_run_prints_plan_and_writes_nothing(project: Path) -> None:
    phase = project / ".sweetclaude" / "state" / "phase.yaml"
    before = phase.read_bytes()

    r = _run_cli("--project-dir", str(project), "--dry-run")

    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "dry run printed nothing"
    assert phase.read_bytes() == before, "--dry-run must not write"


def test_cli_scan_drift_reports_findings_without_migrating(project: Path) -> None:
    phase = project / ".sweetclaude" / "state" / "phase.yaml"
    before = phase.read_bytes()

    r = _run_cli("--project-dir", str(project), "--scan-drift")

    assert r.returncode == 0, r.stderr
    assert phase.read_bytes() == before


def test_cli_report_drift_for_skill_emits_the_documented_contract(project: Path) -> None:
    """skills/bootstrap/SKILL.md Step 5c parses this exact output. It greps
    for DRIFT_COUNT= and splits FINDING| lines on the pipe."""
    r = _run_cli("--project-dir", str(project), "--report-drift-for-skill")

    assert r.returncode == 0, r.stderr
    count_lines = [ln for ln in r.stdout.splitlines() if ln.startswith("DRIFT_COUNT=")]
    assert len(count_lines) == 1, f"expected exactly one DRIFT_COUNT line, got {count_lines}"
    assert count_lines[0].split("=", 1)[1].isdigit()

    for line in [ln for ln in r.stdout.splitlines() if ln.startswith("FINDING|")]:
        parts = line.split("|")
        assert len(parts) >= 4, line
        assert parts[3].startswith("chain="), line


def test_cli_report_drift_returns_zero_even_with_drift(project: Path) -> None:
    """Documented explicitly: bootstrap relies on exit 0 so the shell does not
    abort before it can read DRIFT_COUNT."""
    r = _run_cli("--project-dir", str(project), "--report-drift-for-skill")
    assert r.returncode == 0


def test_cli_scan_drift_persist_writes_findings_to_state(project: Path) -> None:
    _run_cli("--project-dir", str(project), "--scan-drift", "--persist")

    sc = yaml.safe_load((project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_text())
    assert "drift" in (sc.get("framework") or {}), "persist did not write framework.drift"


def test_cli_file_flag_limits_the_run(project: Path) -> None:
    sc_before = (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_bytes()

    r = _run_cli("--project-dir", str(project), "--file", "phase.yaml")
    assert r.returncode == 0, r.stderr

    phase = yaml.safe_load((project / ".sweetclaude" / "state" / "phase.yaml").read_text())
    assert phase["schema_version"] == 2
    assert (project / ".sweetclaude" / "state" / "sweetclaude.yaml").read_bytes() == sc_before, (
        "--file phase.yaml must not touch sweetclaude.yaml"
    )


def test_cli_param_flag_reaches_the_handler(project: Path) -> None:
    """--param phase.yaml:version_stage=GA must override the handler default
    of BETA, otherwise the flag is decorative."""
    r = _run_cli("--project-dir", str(project), "--file", "phase.yaml",
                 "--param", "phase.yaml:version_stage=GA")
    assert r.returncode == 0, r.stderr

    phase = yaml.safe_load((project / ".sweetclaude" / "state" / "phase.yaml").read_text())
    assert phase["version_stage"] == "GA"


def test_cli_run_migrates_and_reports(project: Path) -> None:
    r = _run_cli("--project-dir", str(project))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()

    phase = yaml.safe_load((project / ".sweetclaude" / "state" / "phase.yaml").read_text())
    assert phase["schema_version"] == 2


def test_cli_accepts_an_explicit_registry(project: Path, tmp_path: Path) -> None:
    registry = tmp_path / "custom-registry.yaml"
    registry.write_text(yaml.safe_dump({"schema_version": 1, "state_files": {}}),
                        encoding="utf-8")

    r = _run_cli("--project-dir", str(project), "--registry", str(registry), "--dry-run")
    assert r.returncode == 0, r.stderr


# --- directory entries ---------------------------------------------------

DIR_HANDLER = '''
from pathlib import Path

FROM_VERSION = 1
TO_VERSION = 2


def detect_version(directory):
    directory = Path(directory)
    if any(directory.glob("NEW-*.md")):
        return 2
    if any(directory.glob("OLD-*.md")):
        return 1
    return None


def up(directory, params=None, dry_run=False):
    directory = Path(directory)
    mapping = []
    for old in sorted(directory.glob("OLD-*.md")):
        new = old.with_name(old.name.replace("OLD-", "NEW-", 1))
        # Key names are the contract _write_migration_map() reads. Unknown
        # keys render as blank table cells with no error.
        mapping.append({
            "v_from_id": old.stem,
            "v_to_id": new.stem,
            "title": old.read_text().strip(),
            "type": "artifact",
        })
        if not dry_run:
            old.rename(new)
    return {"mapping": mapping}
'''

FAILING_DIR_HANDLER = '''
from pathlib import Path


FROM_VERSION = 1
TO_VERSION = 2


def detect_version(directory):
    return 1


def up(directory, params=None, dry_run=False):
    raise RuntimeError("directory handler blew up")
'''

NO_UP_DIR_HANDLER = '''
FROM_VERSION = 1
TO_VERSION = 2


def detect_version(directory):
    return 1
'''


@pytest.fixture
def dir_project(tmp_path: Path):
    """Project with an artifact directory plus a registry declaring it."""
    project = tmp_path / "proj"
    (project / ".sweetclaude" / "state").mkdir(parents=True)
    artifacts = project / "artifacts"
    artifacts.mkdir()
    (artifacts / "OLD-001.md").write_text("one\n", encoding="utf-8")
    (artifacts / "OLD-002.md").write_text("two\n", encoding="utf-8")

    handlers = tmp_path / "handlers"
    handlers.mkdir()

    def build(handler_source: str, handler_name: str = "dir_v1_to_v2"):
        (handlers / f"{handler_name}.py").write_text(handler_source, encoding="utf-8")
        registry = tmp_path / f"registry-{handler_name}.yaml"
        registry.write_text(yaml.safe_dump({
            "schema_version": 1,
            "state_files": {
                "artifacts": {
                    "description": "artifact directory",
                    "type": "directory",
                    "path_template": "artifacts",
                    "current_version": 2,
                    "backup_required": False,
                    "migrations": [{
                        "from": 1, "to": 2,
                        "description": "rename OLD- to NEW-",
                        "handler": handler_name,
                    }],
                }
            },
        }), encoding="utf-8")
        return MigrationRunner(project_dir=str(project),
                               registry_path=str(registry),
                               migrations_dir=str(handlers))

    return project, artifacts, build


def test_directory_migration_renames_and_writes_migration_map(dir_project) -> None:
    project, artifacts, build = dir_project
    runner = build(DIR_HANDLER)

    results = runner.run()

    assert results and results[0].success, [r.failure_details for r in results]
    assert sorted(p.name for p in artifacts.glob("NEW-*.md")) == ["NEW-001.md", "NEW-002.md"]
    assert not list(artifacts.glob("OLD-*.md")), "old files should have been renamed"
    assert (artifacts / "MIGRATION-MAP.md").exists(), "directory migration must leave a map"
    map_text = (artifacts / "MIGRATION-MAP.md").read_text(encoding="utf-8")
    assert "OLD-001" in map_text and "NEW-001" in map_text, map_text
    assert "OLD-002" in map_text and "NEW-002" in map_text, map_text


def test_directory_version_detection_reports_migrated_state(dir_project) -> None:
    project, artifacts, build = dir_project
    runner = build(DIR_HANDLER)
    runner.run()

    findings = build(DIR_HANDLER).scan_drift()
    entries = findings.get("findings", findings) if isinstance(findings, dict) else findings
    assert entries is not None


def test_directory_migration_is_idempotent(dir_project) -> None:
    project, artifacts, build = dir_project
    build(DIR_HANDLER).run()
    names_after_first = sorted(p.name for p in artifacts.glob("*.md"))

    build(DIR_HANDLER).run()
    assert sorted(p.name for p in artifacts.glob("*.md")) == names_after_first


def test_directory_dry_run_plans_without_renaming(dir_project) -> None:
    project, artifacts, build = dir_project
    runner = build(DIR_HANDLER)

    plans = runner.plan()

    assert plans, "plan() found no directory work"
    assert sorted(p.name for p in artifacts.glob("*.md")) == ["OLD-001.md", "OLD-002.md"]


def test_directory_handler_failure_is_reported_not_raised(dir_project) -> None:
    """A handler that raises must produce a failed FileResult carrying the
    reason — the skill renders that, and an uncaught exception would instead
    abort the whole migration."""
    project, artifacts, build = dir_project
    runner = build(FAILING_DIR_HANDLER, handler_name="dir_boom")

    results = runner.run()

    assert results
    assert results[0].success is False
    assert results[0].failure_details or results[0].failure_mode


def test_directory_handler_without_up_is_reported(dir_project) -> None:
    project, artifacts, build = dir_project
    runner = build(NO_UP_DIR_HANDLER, handler_name="dir_no_up")

    results = runner.run()

    assert results and results[0].success is False
    assert "up()" in (results[0].failure_details or "")


# --- file-entry failure paths -------------------------------------------

def test_missing_handler_module_is_reported_not_raised(project: Path, tmp_path: Path) -> None:
    # Note: because plan() rejects a missing handler first, the
    # `if module is None:` guard inside _run_one() (runner.py:948) is not
    # reachable through any registry configuration found so far. Mutating it
    # away leaves this suite green. It is defensive, not dead-wrong, and is
    # left in place — recorded here so the surviving mutation is a known
    # quantity rather than an untested gap someone rediscovers later.
    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({
        "schema_version": 1,
        "state_files": {
            "phase.yaml": {
                "description": "phase",
                "current_version": 2,
                "backup_required": False,
                "migrations": [{"from": 1, "to": 2, "description": "x",
                                "handler": "handler_that_does_not_exist"}],
            }
        },
    }), encoding="utf-8")

    results = MigrationRunner(project_dir=str(project),
                              registry_path=str(registry)).run()

    assert results and results[0].success is False
    assert results[0].failure_mode == "chain_broken"
    # A handler module that does not exist is rejected during plan(), before
    # _run_one() is reached — hence "missing handler(s)" rather than the
    # "could not load handler" message _run_one() would produce. Asserting the
    # exact text pins which layer caught it.
    assert "missing handler(s)" in (results[0].failure_details or ""), (
        results[0].failure_details
    )


def test_validation_failure_is_reported(project: Path, tmp_path: Path) -> None:
    """A handler that produces a document failing the registry's validation
    block must fail the file, not write a document that fails its own schema."""
    handlers = tmp_path / "handlers"
    handlers.mkdir()
    (handlers / "bad_output.py").write_text(
        "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
        "def up(data, params=None):\n"
        "    return {'schema_version': 2}\n",
        encoding="utf-8")

    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({
        "schema_version": 1,
        "state_files": {
            "phase.yaml": {
                "description": "phase",
                "current_version": 2,
                "backup_required": False,
                "migrations": [{
                    "from": 1, "to": 2, "description": "x", "handler": "bad_output",
                    "validation": {
                        "required_fields": ["schema_version", "version_stage",
                                            "deference_level"],
                        "required_version": 2,
                    },
                }],
            }
        },
    }), encoding="utf-8")

    phase = project / ".sweetclaude" / "state" / "phase.yaml"
    before = phase.read_bytes()

    results = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                              migrations_dir=str(handlers)).run()

    assert results and results[0].success is False
    assert phase.read_bytes() == before, (
        "a document that fails validation must not be written to disk"
    )


def test_recoverable_error_produces_a_recovery_menu(project: Path, tmp_path: Path) -> None:
    """RecoverableMigrationError is how a handler asks the skill to present
    choices. The menu must reach the FileResult."""
    handlers = tmp_path / "handlers"
    handlers.mkdir()
    (handlers / "recoverable.py").write_text(
        "import sys\n"
        "sys.path.insert(0, r'" + str(MIGRATIONS) + "')\n"
        "from runner import RecoverableMigrationError\n\n"
        "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
        "def up(data, params=None):\n"
        "    raise RecoverableMigrationError('needs a human')\n",
        encoding="utf-8")

    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({
        "schema_version": 1,
        "state_files": {
            "phase.yaml": {
                "description": "phase",
                "current_version": 2,
                "backup_required": False,
                "migrations": [{"from": 1, "to": 2, "description": "x",
                                "handler": "recoverable"}],
            }
        },
    }), encoding="utf-8")

    results = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                              migrations_dir=str(handlers)).run()

    assert results and results[0].success is False
    assert results[0].recovery_menu, "recoverable failure produced no recovery menu"


def test_unreadable_yaml_does_not_crash_the_run(project: Path) -> None:
    """A corrupt state file must not abort the run and leave other files
    unmigrated."""
    (project / ".sweetclaude" / "state" / "phase.yaml").write_text(
        "{ this: is: not: valid: yaml", encoding="utf-8")

    results = MigrationRunner(project_dir=str(project)).run()
    assert isinstance(results, list)


def test_corrupt_state_file_is_currently_reported_as_success(project: Path) -> None:
    """Behavior recorded, not endorsed — see ISSUE-269.

    runner.py:307 _detect_version() returns None for three different
    conditions: file absent, YAML unparseable, and no schema_version present.
    The caller cannot tell them apart, so a corrupt file looks like "nothing
    to migrate" and the run reports success. The user is told migration
    succeeded while their state file is unreadable.

    This test fails the moment that changes, which is the point — the fix
    should update this assertion rather than land silently.
    """
    (project / ".sweetclaude" / "state" / "phase.yaml").write_text(
        "{ this: is: not: valid: yaml", encoding="utf-8")

    results = MigrationRunner(project_dir=str(project)).run()
    phase = [r for r in results if r.file_key == "phase.yaml"]

    assert phase, "phase.yaml produced no result at all"
    assert phase[0].success is True
    assert phase[0].on_disk_version_before is None


def _registry_for(tmp_path: Path, handler: str, name: str, **entry_extra) -> Path:
    registry = tmp_path / f"registry-{name}.yaml"
    migration = {"from": 1, "to": 2, "description": "x", "handler": handler}
    migration.update(entry_extra.pop("migration_extra", {}))
    registry.write_text(yaml.safe_dump({
        "schema_version": 1,
        "state_files": {
            "phase.yaml": {
                "description": "phase",
                "current_version": 2,
                "backup_required": False,
                "migrations": [migration],
                **entry_extra,
            }
        },
    }), encoding="utf-8")
    return registry


def _handler(tmp_path: Path, name: str, source: str) -> Path:
    handlers = tmp_path / "handlers"
    handlers.mkdir(exist_ok=True)
    (handlers / f"{name}.py").write_text(source, encoding="utf-8")
    return handlers


HANDLER_NO_UP = "FROM_VERSION = 1\nTO_VERSION = 2\n"
HANDLER_KEYERROR = (
    "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
    "def up(data, params=None):\n"
    "    return {'schema_version': 2, 'x': data['definitely_absent']}\n"
)
HANDLER_OK = (
    "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
    "def up(data, params=None):\n"
    "    return {'schema_version': 2, 'version_stage': 'GA',\n"
    "            'deference_level': 'collaborative'}\n"
)


def test_file_handler_without_up_reports_broken_chain(project: Path, tmp_path: Path) -> None:
    handlers = _handler(tmp_path, "no_up", HANDLER_NO_UP)
    registry = _registry_for(tmp_path, "no_up", "no_up")

    results = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                              migrations_dir=str(handlers)).run()

    assert results and results[0].success is False
    assert "up()" in (results[0].failure_details or "")


def test_file_handler_keyerror_reports_missing_required_field(
    project: Path, tmp_path: Path
) -> None:
    """A handler reaching for a field the v1 document never had. The result
    must name the missing field rather than surfacing a raw traceback."""
    handlers = _handler(tmp_path, "keyerr", HANDLER_KEYERROR)
    registry = _registry_for(tmp_path, "keyerr", "keyerr")

    results = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                              migrations_dir=str(handlers)).run()

    assert results and results[0].success is False
    assert "KeyError" in (results[0].failure_details or "")
    assert "definitely_absent" in (results[0].failure_details or "")


def test_pre_validation_failure_stops_before_the_handler_runs(
    project: Path, tmp_path: Path
) -> None:
    """pre_validation guards the input document. If it fails, the handler must
    not run and the file must not be rewritten."""
    handlers = _handler(tmp_path, "ok_handler", HANDLER_OK)
    registry = _registry_for(
        tmp_path, "ok_handler", "preval",
        migration_extra={"pre_validation": {
            "required_fields": ["a_field_that_is_not_there"], "required_version": 1}},
    )
    phase = project / ".sweetclaude" / "state" / "phase.yaml"
    before = phase.read_bytes()

    results = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                              migrations_dir=str(handlers)).run()

    assert results and results[0].success is False
    assert phase.read_bytes() == before, "pre-validation failure must not rewrite the file"


def test_write_failure_is_reported_not_raised(
    project: Path, tmp_path: Path, monkeypatch
) -> None:
    """Disk full, permissions, read-only mount. The runner must report a write
    failure rather than raise through to the caller."""
    handlers = _handler(tmp_path, "ok_handler2", HANDLER_OK)
    registry = _registry_for(tmp_path, "ok_handler2", "writefail")

    runner = MigrationRunner(project_dir=str(project), registry_path=str(registry),
                             migrations_dir=str(handlers))

    def boom(self, path, content):
        raise OSError("read-only file system")

    monkeypatch.setattr(MigrationRunner, "_atomic_write", boom)

    results = runner.run()
    assert results and results[0].success is False
    assert "read-only file system" in (results[0].failure_details or "")


DIR_HANDLER_KEYERROR = (
    "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
    "def detect_version(directory):\n    return 1\n\n"
    "def up(directory, params=None, dry_run=False):\n"
    "    raise KeyError('missing_directory_field')\n"
)


def test_directory_handler_keyerror_is_reported(dir_project) -> None:
    project, artifacts, build = dir_project
    results = build(DIR_HANDLER_KEYERROR, handler_name="dir_keyerr").run()

    assert results and results[0].success is False
    assert "KeyError" in (results[0].failure_details or "")


def test_directory_handler_recoverable_error_produces_menu(dir_project, tmp_path) -> None:
    source = (
        "import sys\n"
        "sys.path.insert(0, r'" + str(MIGRATIONS) + "')\n"
        "from runner import RecoverableMigrationError\n\n"
        "FROM_VERSION = 1\nTO_VERSION = 2\n\n"
        "def detect_version(directory):\n    return 1\n\n"
        "def up(directory, params=None, dry_run=False):\n"
        "    raise RecoverableMigrationError('directory needs a human')\n"
    )
    project, artifacts, build = dir_project
    results = build(source, handler_name="dir_recoverable").run()

    assert results and results[0].success is False
    assert results[0].recovery_menu, "no recovery menu for a recoverable directory failure"


def test_optional_registered_file_absent_is_not_a_failure(project: Path) -> None:
    """skills.yaml is marked optional in the registry. A project without one
    must not be reported as a failed migration."""
    results = MigrationRunner(project_dir=str(project)).run()
    for r in results:
        if r.file_key == "skills.yaml":
            assert r.success is not False, r.failure_details
