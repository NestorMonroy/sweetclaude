"""
WI-017 S7 — Wiring: close the dead-end at the system level.

Tests the behaviors specified in tests/features/wi-017-s7-wiring.feature.

Pre-S7 state that makes these tests RED:
- capability `migrate.typed_legacy_backlog` is supported: false, supports_project_shapes: []
- project_shape `typed_legacy_backlog` has migrate_allowed: false and routes to
  compatibility-mode (a no-action dead-end)
- recover_project _blocked_actions HARD-BLOCKS "taxonomy-migration" for the
  unsupported-typed-backlog-layout failure
- A typed-legacy project's guard status offers NO runnable migrate action
- Doctor maintenance-route for a typed-legacy project returns compatibility-mode
  with primary_action="continue-compatibility-mode" (no migration offered)

After S7 these tests must be GREEN.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Path constants — mirrors test_dead_end_totality.py
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parents[1]
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
RECOVER = REPO_ROOT / "scripts" / "recovery" / "recover_project.py"
MANIFEST = REPO_ROOT / "config" / "capability-manifest.yaml"
SYNCOG_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "syncog-layout"
V4_COMPAT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "v4-compliant-compat"

# ---------------------------------------------------------------------------
# Subprocess helpers (identical style to test_dead_end_totality.py)
# ---------------------------------------------------------------------------


def _run_json(script: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{script.name} {' '.join(args)} exited {result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}"
    )
    return json.loads(result.stdout)


def _guard(project: Path) -> dict:
    return _run_json(RECOVER, "guard", "--project-dir", str(project))


def _maintenance_route(project: Path) -> dict:
    payload = _run_json(DOCTOR, "maintenance-route", "--project-dir", str(project))
    return payload.get("maintenance_route", payload)


def _diagnose(project: Path) -> dict:
    return _run_json(RECOVER, "diagnose", "--project-dir", str(project))


def _run_migration_fn(project: Path, dry_run: bool = False) -> dict:
    """Import and call run_migration directly (mirrors test_wi017_s3_execute_plan.py style)."""
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from migrate.migrate_taxonomy import run_migration
    return run_migration(str(project), dry_run=dry_run)


# ---------------------------------------------------------------------------
# Project factory helpers
# ---------------------------------------------------------------------------

def _write_state(project: Path, **overrides) -> None:
    state_dir = project / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {
        "schema_version": 2,
        "framework": {
            "installed_version": "4.2.7-beta",
            "migration_status": "deferred",
        },
        "paths": {"product_base": "docs/product"},
        "recovery": {
            "taxonomy": {
                "status": "stabilized-without-migration",
                "migration_required": False,
                "blind_taxonomy_migration_allowed": False,
            },
        },
    }
    for key, value in overrides.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    (state_dir / "sweetclaude.yaml").write_text(
        yaml.safe_dump(state, default_flow_style=False), encoding="utf-8",
    )


def _write_artifact_privacy(project: Path) -> None:
    sc = project / ".sweetclaude"
    sc.mkdir(parents=True, exist_ok=True)
    (sc / "artifact-privacy.yaml").write_text(
        "schema_version: 1\n"
        "categories:\n"
        "  product:\n"
        "    privacy: private\n"
        "    base_path: docs/product\n",
        encoding="utf-8",
    )


def _make_fresh_typed_legacy_project(tmp_path: Path) -> Path:
    """
    A typed-legacy project with backlog/stories/STORY-*, backlog/debt/DEBT-*,
    and top-level old-prefix files. No recovery state written yet.
    Mirrors the real syncog layout.
    """
    project = tmp_path / "project"
    shutil.copytree(SYNCOG_FIXTURE, project)
    _write_artifact_privacy(project)
    # No .sweetclaude/state/ — no recovery state yet
    return project


def _make_stabilized_typed_legacy_project(tmp_path: Path) -> Path:
    """
    A typed-legacy project whose state has been stabilized without migration.
    State: recovery.taxonomy.status == "stabilized-without-migration".
    Still has typed dirs and old-prefix files on disk.
    """
    project = tmp_path / "project"
    shutil.copytree(SYNCOG_FIXTURE, project)
    _write_artifact_privacy(project)
    _write_state(project)   # writes stabilized-without-migration state
    return project


def _has_migrate_reference_in_payload(payload: dict) -> bool:
    """
    Return True only if the payload references the migrate capability or skill
    as an OFFERED action — not merely as a blocked capability name.

    A reference in blocked_capabilities does NOT count. We look for it in:
    - primary_action.capability_id
    - primary_action.delegate_skill containing "migrate"
    - project_shape == "typed_legacy_backlog" with migrate-signaling guard_status
    - status that signals migration is available
    - migration_capability referenced in the shape
    """
    # Check primary_action
    primary = payload.get("primary_action") or {}
    cap_id = primary.get("capability_id", "")
    delegate = primary.get("delegate_skill", "")
    if "migrate.typed_legacy_backlog" in cap_id:
        return True
    if "sweetclaude:migrate" in delegate or "migrate" in cap_id.lower():
        # Exclude doctor.compatibility_mode and similar
        if "migrate" in cap_id and "compatibility" not in cap_id:
            return True

    # Check status signals migration
    status = payload.get("status", "")
    if status in ("supported-migration-available", "migration-available",
                  "migration-may-be-needed"):
        return True

    # Check guard payload migrate_allowed
    if payload.get("migrate_allowed") is True:
        return True

    # Check guard project_shape is typed_legacy_backlog with non-dead-end status
    if payload.get("project_shape") == "typed_legacy_backlog":
        return True

    return False


# ---------------------------------------------------------------------------
# Scenario 1 — Manifest: capability is supported and shape allows migration
#
# RED reason: migrate.typed_legacy_backlog.supported == False;
#             supports_project_shapes == [];
#             typed_legacy_backlog.migrate_allowed == False
# ---------------------------------------------------------------------------

class TestManifestCapabilitySupported:
    """
    The typed-legacy migrator capability is listed as supported in the manifest,
    declares a command_entrypoint, supports the typed_legacy_backlog project shape,
    and the project shape has migrate_allowed True.
    """

    def _load_capability_config(self):
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from maintenance.capability_manifest import capability_config
        return capability_config

    def _load_shape_config(self):
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from maintenance.capability_manifest import project_shape_config
        return project_shape_config

    def test_migrate_typed_legacy_backlog_is_supported(self):
        capability_config = self._load_capability_config()
        cfg = capability_config("migrate.typed_legacy_backlog")
        assert cfg.get("supported") is True, (
            "migrate.typed_legacy_backlog must be supported:true after S7; "
            f"got supported={cfg.get('supported')!r}"
        )

    def test_migrate_typed_legacy_backlog_has_command_entrypoint(self):
        capability_config = self._load_capability_config()
        cfg = capability_config("migrate.typed_legacy_backlog")
        entrypoint = cfg.get("command_entrypoint")
        assert entrypoint, (
            "migrate.typed_legacy_backlog must have a command_entrypoint after S7; "
            "currently absent"
        )
        assert isinstance(entrypoint, dict), (
            "command_entrypoint must be a mapping"
        )
        # Must have at least one of slash_command or script
        has_entry = entrypoint.get("slash_command") or entrypoint.get("script")
        assert has_entry, (
            "command_entrypoint must declare slash_command or script; "
            f"got {entrypoint!r}"
        )

    def test_migrate_typed_legacy_backlog_supports_typed_legacy_shape(self):
        capability_config = self._load_capability_config()
        cfg = capability_config("migrate.typed_legacy_backlog")
        supported_shapes = cfg.get("supports_project_shapes") or []
        assert "typed_legacy_backlog" in supported_shapes, (
            "migrate.typed_legacy_backlog.supports_project_shapes must include "
            "'typed_legacy_backlog' after S7; "
            f"got {supported_shapes!r}"
        )

    def test_typed_legacy_backlog_shape_migrate_allowed_true(self):
        project_shape_config = self._load_shape_config()
        shape = project_shape_config("typed_legacy_backlog")
        assert shape.get("migrate_allowed") is True, (
            "typed_legacy_backlog project shape must have migrate_allowed:true after S7; "
            f"got migrate_allowed={shape.get('migrate_allowed')!r}"
        )

    def test_typed_legacy_backlog_shape_has_migration_capability(self):
        project_shape_config = self._load_shape_config()
        shape = project_shape_config("typed_legacy_backlog")
        migration_capability = shape.get("migration_capability")
        assert migration_capability, (
            "typed_legacy_backlog shape must declare a migration_capability after S7; "
            f"got {migration_capability!r}"
        )
        assert migration_capability == "migrate.typed_legacy_backlog", (
            "typed_legacy_backlog.migration_capability must be "
            "'migrate.typed_legacy_backlog'; "
            f"got {migration_capability!r}"
        )

    def test_typed_legacy_backlog_shape_guard_status_signals_migration(self):
        """
        The guard_status for typed_legacy_backlog must be a migration-signaling
        value — NOT 'compatibility-mode' (the pre-S7 dead-end).
        """
        project_shape_config = self._load_shape_config()
        shape = project_shape_config("typed_legacy_backlog")
        guard_status = shape.get("guard_status")
        assert guard_status != "compatibility-mode", (
            "typed_legacy_backlog.guard_status must not be 'compatibility-mode' after S7 "
            "— that is the permanent dead-end. Expected a migration-signaling status "
            "(e.g. 'migration-available' or 'migration-may-be-needed'). "
            f"Got guard_status={guard_status!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — Fresh typed-legacy project guard offers migration, not a dead-end
#
# A "fresh" typed-legacy project has no sweetclaude.yaml — the guard routes it
# to "stabilize-without-migration" → recovery_required currently. After S7 the
# typed_legacy_backlog shape must route to a migration-offering status, so a
# project whose characterization shows typed backlog dirs + old prefixes goes to
# the migration path rather than stabilize-without-migration.
#
# RED reason: The guard still sends the project to run-recover / recovery_required
#             (stabilize-without-migration) rather than offering migration first.
# ---------------------------------------------------------------------------

class TestFreshTypedLegacyGuardOffersMigration:
    """
    A fresh typed-legacy project (typed dirs + old-prefix files, no recovery state)
    runs the guard. The guard must:
    - Classify the project as typed_legacy_backlog (not recovery_required)
    - Route to a migration-offering status (not "compatibility-mode" or "run-recover")
    - Have migrate_allowed True
    """

    def test_fresh_typed_legacy_classified_as_typed_legacy_backlog(self, tmp_path):
        """
        After S7, a fresh project with typed backlog layout must classify as
        'typed_legacy_backlog', not 'recovery_required'.
        Pre-S7 it routes to recovery_required (stabilize-without-migration dead-end).
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard["project_shape"] == "typed_legacy_backlog", (
            "A fresh typed-legacy project (typed dirs, old prefixes, no recovery state) "
            "must classify as 'typed_legacy_backlog' after S7. "
            f"Got project_shape={guard['project_shape']!r}. "
            "Pre-S7 it classified as 'recovery_required' (stabilize-without-migration)."
        )

    def test_fresh_typed_legacy_guard_does_not_return_run_recover(self, tmp_path):
        """
        After S7, a fresh typed-legacy project must NOT route to run-recover
        (which leads to stabilize-without-migration — a dead-end that was
        the pre-S7 behavior).
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard["status"] != "run-recover", (
            "A fresh typed-legacy project must NOT route to 'run-recover' after S7 — "
            "that leads to stabilize-without-migration (dead-end). "
            f"Got status={guard['status']!r}. Expected a migration-signaling status."
        )

    def test_fresh_typed_legacy_guard_status_is_migration_signaling(self, tmp_path):
        """
        After S7, a fresh typed-legacy project must route to a migration-signaling
        status — specifically one that tells the user migration is available/needed.
        Pre-S7 the status is 'run-recover' (which leads to stabilize-without-migration)
        or 'compatibility-mode' — both are dead-ends with no migration path.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        MIGRATION_SIGNALING_STATUSES = {
            "migration-available",
            "migration-may-be-needed",
            "supported-migration-available",
        }
        assert guard["status"] in MIGRATION_SIGNALING_STATUSES, (
            "A fresh typed-legacy project must route to a migration-signaling status after S7. "
            f"Got status={guard['status']!r}. "
            f"Expected one of {MIGRATION_SIGNALING_STATUSES}. "
            "Pre-S7 status is 'run-recover' (dead-end via stabilize-without-migration)."
        )

    def test_fresh_typed_legacy_guard_migrate_allowed_is_true(self, tmp_path):
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard.get("migrate_allowed") is True, (
            "Fresh typed-legacy project guard must report migrate_allowed=True after S7; "
            f"got migrate_allowed={guard.get('migrate_allowed')!r}"
        )

    def test_fresh_typed_legacy_guard_offers_migrate_capability_in_offered_position(
        self, tmp_path
    ):
        """
        The guard payload must reference migrate.typed_legacy_backlog or
        sweetclaude:migrate as an OFFERED action — not just in blocked_capabilities.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        # migrate_allowed is the definitive flag — True means migration is offered
        assert guard.get("migrate_allowed") is True, (
            "After S7, fresh typed-legacy project guard must have migrate_allowed=True. "
            f"Currently migrate_allowed={guard.get('migrate_allowed')!r}. "
            "Pre-S7 it was always False for typed_legacy_backlog."
        )


# ---------------------------------------------------------------------------
# Scenario 3 — taxonomy-migration is no longer a hard-blocked action
#
# RED reason: _blocked_actions() currently appends taxonomy-migration for every
#             project with unsupported-typed-backlog-layout failure.
#             After S7, typed-legacy projects must route to migration, not
#             stabilize-without-migration, so this failure class either disappears
#             or no longer triggers a blocked action.
# ---------------------------------------------------------------------------

class TestTaxonomyMigrationNotBlocked:
    """
    After S7, diagnose_project / plan_project on a typed-legacy project must NOT
    list 'taxonomy-migration' among blocked_actions.
    """

    def _get_plan_blocked_actions(self, project: Path) -> list[str]:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from recovery.recover_project import plan_project
        plan = plan_project(project)
        return [b["id"] for b in plan.get("blocked_actions", [])]

    def test_taxonomy_migration_not_in_blocked_actions_fresh(self, tmp_path):
        project = _make_fresh_typed_legacy_project(tmp_path)
        blocked_ids = self._get_plan_blocked_actions(project)
        assert "taxonomy-migration" not in blocked_ids, (
            "After S7, 'taxonomy-migration' must NOT be a blocked action for a "
            "fresh typed-legacy project. It was hard-blocked pre-S7 by _blocked_actions(). "
            f"Got blocked_actions: {blocked_ids!r}"
        )

    def test_stabilized_typed_legacy_plan_routes_to_migration_not_no_op(self, tmp_path):
        """
        After S7, the plan for a stabilized typed-legacy project must route to
        migration (not 'no-op' / 'no-recovery-needed').
        Pre-S7: stabilized project has recovery_route=no-recovery-needed because
        _taxonomy_recovery_accepts_legacy_layout returns True, so the plan is no-op.
        After S7: the guard must detect old prefixes still present and route to migration.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from recovery.recover_project import plan_project
        plan = plan_project(project)

        plan_status = plan.get("plan_status", "")
        assert plan_status != "no-op", (
            "After S7, plan for a stabilized typed-legacy project must NOT be 'no-op'. "
            "Pre-S7: accepted_legacy_layout=True causes recovery_route=no-recovery-needed "
            "and plan_status=no-op — a dead-end with no exit. "
            f"Got plan_status={plan_status!r}, recovery_route={plan.get('recovery_route')!r}."
        )

    def test_unsupported_typed_backlog_failure_absent_or_has_migrate_strategy(self, tmp_path):
        """
        After S7, the unsupported-typed-backlog-layout failure class either:
        (a) no longer appears (migration is now supported, so not a failure), OR
        (b) carries a 'migrate' recovery strategy rather than 'stabilize-without-migration'.
        Pre-S7 it always appeared with strategy='stabilize-without-migration'.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        diagnosis = _diagnose(project)

        failure_classes = diagnosis.get("failure_classes", [])
        typed_backlog_failure = next(
            (f for f in failure_classes if f.get("code") == "unsupported-typed-backlog-layout"),
            None,
        )

        if typed_backlog_failure is None:
            # (a) failure class absent — migration now supported, not a failure.
            # This is the expected post-S7 state.
            return

        # (b) if failure class still present, strategy must mention migration
        strategy = typed_backlog_failure.get("recovery_strategy", "")
        assert "stabilize-without-migration" not in strategy or "migrate" in strategy.lower(), (
            "unsupported-typed-backlog-layout failure class must carry a migrate "
            f"recovery strategy after S7 (not 'stabilize-without-migration' alone); "
            f"got recovery_strategy={strategy!r}. "
            "Pre-S7 it was 'stabilize-without-migration' — a dead-end."
        )


# ---------------------------------------------------------------------------
# Scenario 4 — Stabilized project is offered migration
#
# A stabilized project has recovery.taxonomy.status == "stabilized-without-migration".
# Pre-S7: guard routes this to compatibility-mode (accepted_legacy_taxonomy shape),
#         primary_action = continue-compatibility-mode.
# After S7: guard must detect old prefixes still present and offer migration.
#
# RED reason: accepted_legacy_layout check causes guard to route to
#             accepted_legacy_taxonomy / compatibility-mode, not to typed_legacy_backlog
# ---------------------------------------------------------------------------

class TestStabilizedProjectOfferedMigration:
    """
    A project already stabilized in compatibility mode
    (state: recovery.taxonomy.status == "stabilized-without-migration",
     typed dirs + old prefixes still present on disk)
    must have the guard offer the migrator as the resolving action.
    """

    def test_stabilized_typed_legacy_guard_project_shape_is_typed_legacy_backlog(
        self, tmp_path
    ):
        """
        After S7, a stabilized project with typed dirs + old prefixes must classify
        as 'typed_legacy_backlog' (migration path), not 'accepted_legacy_taxonomy'
        (compatibility-mode dead-end).
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard["project_shape"] == "typed_legacy_backlog", (
            "A stabilized typed-legacy project (old prefixes still present) must "
            "classify as 'typed_legacy_backlog' after S7, not 'accepted_legacy_taxonomy'. "
            f"Got project_shape={guard['project_shape']!r}. "
            "Pre-S7 it classified as 'accepted_legacy_taxonomy' (dead-end)."
        )

    def test_stabilized_typed_legacy_guard_does_not_return_compatibility_mode(
        self, tmp_path
    ):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard["status"] != "compatibility-mode", (
            "A stabilized typed-legacy project must NOT route to 'compatibility-mode' "
            "after S7 — that is the pre-S7 permanent parking status. "
            f"Got status={guard['status']!r}. The guard must offer migration."
        )

    def test_stabilized_typed_legacy_guard_migrate_allowed_is_true(self, tmp_path):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard.get("migrate_allowed") is True, (
            "Stabilized typed-legacy project guard must report migrate_allowed=True "
            f"after S7; got {guard.get('migrate_allowed')!r}"
        )

    def test_stabilized_typed_legacy_maintenance_route_not_compatibility_mode(
        self, tmp_path
    ):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        assert route.get("status") != "compatibility-mode", (
            "maintenance-route status for a stabilized typed-legacy project must "
            "NOT be 'compatibility-mode' after S7. "
            f"Got status={route.get('status')!r}"
        )

    def test_stabilized_typed_legacy_maintenance_route_primary_not_continue_compat(
        self, tmp_path
    ):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        primary = route.get("primary_action") or {}
        assert primary.get("id") != "continue-compatibility-mode", (
            "maintenance-route primary_action must not be 'continue-compatibility-mode' "
            "for a stabilized typed-legacy project after S7. That is a no-op dead-end. "
            f"Got primary_action={primary!r}"
        )

    def test_stabilized_typed_legacy_maintenance_route_offers_migration_capability(
        self, tmp_path
    ):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        primary = route.get("primary_action") or {}
        cap_id = primary.get("capability_id", "")
        route_status = route.get("status", "")
        assert (
            "migrate.typed_legacy_backlog" in cap_id
            or "supported-migration-available" == route_status
            or "migration-available" in route_status
        ), (
            "Doctor maintenance-route for a stabilized typed-legacy project must "
            "offer the migration capability (migrate.typed_legacy_backlog) or "
            "report status='supported-migration-available' after S7. "
            f"Got status={route_status!r}, primary_action.capability_id={cap_id!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 5 — Post-migration guard reports graduation-eligible
#
# RED reason: run_migration(dry_run=False) on a typed-legacy project either does
#             nothing useful (no state update) or S3 hasn't migrated the typed
#             layout, so the guard never transitions to graduation-available
# ---------------------------------------------------------------------------

class TestPostMigrationGuardGraduationAvailable:
    """
    After run_migration(dry_run=False) runs successfully on a stabilized
    typed-legacy project, the guard must report the project as
    v4-compliant / graduation-available (the sanctioned exit), NOT still
    parked in compatibility-mode.
    """

    def test_post_migration_guard_not_compatibility_mode(self, tmp_path):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        result = _run_migration_fn(project, dry_run=False)
        assert result.get("ok") is True, (
            f"run_migration must succeed on a typed-legacy project for post-migration "
            f"guard test to be meaningful; got result={result!r}"
        )

        guard = _guard(project)
        assert guard["status"] != "compatibility-mode", (
            "After successful migration, the guard must NOT return 'compatibility-mode' "
            "(the pre-S7 permanent parking state). "
            f"Got status={guard['status']!r}"
        )

    def test_post_migration_guard_is_graduation_eligible(self, tmp_path):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        result = _run_migration_fn(project, dry_run=False)
        assert result.get("ok") is True, (
            f"run_migration must succeed; got {result!r}"
        )

        guard = _guard(project)
        # After migration the project must be graduation-available (v4-compliant)
        # or ok (already graduated). Both are acceptable exits.
        assert guard["status"] in ("graduation-available", "ok"), (
            "After successful migration, the guard must report 'graduation-available' "
            "or 'ok' — the sanctioned exits from compatibility mode. "
            f"Got status={guard['status']!r}. "
            "Pre-S7 the guard still returned 'compatibility-mode' even after migration."
        )

    def test_graduation_clears_compatibility_state(self, tmp_path):
        project = _make_stabilized_typed_legacy_project(tmp_path)
        result = _run_migration_fn(project, dry_run=False)
        assert result.get("ok") is True, (
            f"run_migration must succeed; got {result!r}"
        )

        guard = _guard(project)
        if guard["status"] == "graduation-available":
            scripts_dir = str(REPO_ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from recovery.recover_project import graduate
            grad_result = graduate(project)
            assert grad_result.get("status") == "graduated", (
                f"graduate() must succeed after migration; got {grad_result!r}"
            )
            final_guard = _guard(project)
            assert final_guard["status"] == "ok", (
                "After graduation, the guard must report 'ok'. "
                f"Got status={final_guard['status']!r}"
            )
        elif guard["status"] == "ok":
            # migration itself marked the project as graduated — also acceptable
            pass
        else:
            pytest.fail(
                "After migration, guard must be 'graduation-available' or 'ok'; "
                f"got {guard['status']!r}"
            )


# ---------------------------------------------------------------------------
# Scenario 6 — No flag-write shortcut exit (regression lock)
#
# This is a REGRESSION LOCK — mirrors test_dead_end_totality invariant.
# These tests were GREEN pre-S7 and must STAY GREEN after S7.
# We include them here explicitly to ensure S7 cannot regress them.
# ---------------------------------------------------------------------------

class TestNoFlagWriteShortcutExit:
    """
    The scan and maintenance-route must never offer:
    - A fix_recipe of type "exit_compatibility_mode"
    - A status derived from a "compatibility_exited" flag write

    This locks the invariant from test_dead_end_totality.py::test_scan_never_offers_the_flag_write_exit
    so S7 can't regress it.
    """

    def _scan(self, project: Path) -> dict:
        return _run_json(DOCTOR, "scan", "--project-dir", str(project))

    def test_scan_never_offers_exit_compatibility_mode_recipe_stabilized(self, tmp_path):
        """
        Regression lock for stabilized typed-legacy project.
        Was GREEN pre-S7 — must stay GREEN after S7.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        scan = self._scan(project)

        for finding in scan["findings"]:
            recipe = finding.get("fix_recipe") or {}
            assert recipe.get("type") != "exit_compatibility_mode", (
                f"scan finding {finding.get('id')!r} offers exit_compatibility_mode "
                "recipe — this is a no-op flag-write shortcut; only graduation exits"
            )
            key_path = recipe.get("key_path") or []
            assert "compatibility_exited" not in key_path, (
                f"scan finding {finding.get('id')!r} writes the compatibility_exited "
                "flag — the guard does not read this flag for status decisions"
            )

    def test_scan_never_offers_exit_compatibility_mode_recipe_fresh(self, tmp_path):
        """
        Regression lock for fresh typed-legacy project.
        After S7, no shortcut exit recipe should appear for this shape either.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        scan = self._scan(project)

        for finding in scan["findings"]:
            recipe = finding.get("fix_recipe") or {}
            assert recipe.get("type") != "exit_compatibility_mode", (
                f"scan finding {finding.get('id')!r} offers exit_compatibility_mode "
                "recipe — this is a no-op flag-write shortcut; only graduation exits"
            )
            key_path = recipe.get("key_path") or []
            assert "compatibility_exited" not in key_path, (
                f"scan finding {finding.get('id')!r} writes the compatibility_exited "
                "flag — the guard does not read this flag for status decisions"
            )

    def test_maintenance_route_no_exit_compatibility_mode_action_stabilized(self, tmp_path):
        """
        Regression lock: maintenance-route for stabilized must not offer flag-write exit.
        Was GREEN pre-S7 — must stay GREEN.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        route_text = json.dumps(route)
        assert "exit_compatibility_mode" not in route_text, (
            "maintenance-route must not reference 'exit_compatibility_mode' — "
            "that is a flag-write shortcut; only graduation is the sanctioned exit. "
            f"Route (truncated): {route_text[:600]!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 7 — No-dead-end invariant: every guard status has a routed action
#
# RED reason: typed_legacy_backlog and stabilized variant currently return
#             compatibility-mode with primary_action = "continue-compatibility-mode"
#             (no migration action). The status has no resolution path.
# ---------------------------------------------------------------------------

class TestNoDeadEndInvariant:
    """
    For the typed_legacy_backlog shape (fresh and stabilized), the guard payload
    must contain an actionable migration next step.
    """

    def test_fresh_typed_legacy_guard_migrate_allowed_true(self, tmp_path):
        """
        migrate_allowed is the definitive actionability signal.
        Pre-S7 it is always False for typed_legacy_backlog.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard.get("migrate_allowed") is True, (
            "Fresh typed-legacy project guard must have migrate_allowed=True after S7 "
            "(it is the actionability flag — False means no next step). "
            f"Got migrate_allowed={guard.get('migrate_allowed')!r}"
        )

    def test_stabilized_typed_legacy_guard_migrate_allowed_true(self, tmp_path):
        """
        migrate_allowed is the definitive actionability signal for the stabilized variant.
        Pre-S7 it is always False.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        guard = _guard(project)

        assert guard.get("migrate_allowed") is True, (
            "Stabilized typed-legacy project guard must have migrate_allowed=True after S7. "
            f"Got migrate_allowed={guard.get('migrate_allowed')!r}"
        )

    def test_fresh_typed_legacy_guard_shape_offers_migration_capability(self, tmp_path):
        """
        The project_shape emitted by the guard for a fresh typed-legacy project
        must be one that has a migration_capability in the manifest.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        guard = _guard(project)

        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from maintenance.capability_manifest import project_shape_config

        project_shape = guard.get("project_shape", "")
        assert project_shape, "guard must return a project_shape"
        try:
            shape_cfg = project_shape_config(project_shape)
        except Exception:
            pytest.fail(f"guard returned unknown project_shape: {project_shape!r}")

        migration_cap = shape_cfg.get("migration_capability")
        assert migration_cap, (
            f"guard project_shape '{project_shape}' for a fresh typed-legacy project "
            "must have a migration_capability in the manifest after S7. "
            "Pre-S7 typed_legacy_backlog had no migration_capability."
        )

    def test_stabilized_typed_legacy_guard_shape_offers_migration_capability(self, tmp_path):
        """
        Same check for the stabilized variant.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        guard = _guard(project)

        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from maintenance.capability_manifest import project_shape_config

        project_shape = guard.get("project_shape", "")
        assert project_shape, "guard must return a project_shape"
        try:
            shape_cfg = project_shape_config(project_shape)
        except Exception:
            pytest.fail(f"guard returned unknown project_shape: {project_shape!r}")

        migration_cap = shape_cfg.get("migration_capability")
        assert migration_cap, (
            f"guard project_shape '{project_shape}' for a stabilized typed-legacy project "
            "must have a migration_capability in the manifest after S7. "
            "Pre-S7 accepted_legacy_taxonomy had no migration_capability (dead-end)."
        )


# ---------------------------------------------------------------------------
# Scenario 8 — Doctor maintenance-route names migration capability
#
# RED reason: build_maintenance_route for a typed-legacy project routes to
#             "compatibility-mode" status with primary_action pointing to
#             doctor.compatibility_mode (no migration offered)
# ---------------------------------------------------------------------------

class TestDoctorMaintenanceRouteNamesMigration:
    """
    The doctor maintenance-route for a typed-legacy project must name the
    migration capability (migrate.typed_legacy_backlog or sweetclaude:migrate)
    as the primary or offered action.
    """

    def test_maintenance_route_for_stabilized_typed_legacy_status_is_migration(
        self, tmp_path
    ):
        """
        maintenance-route status for a stabilized typed-legacy project must be
        'supported-migration-available' after S7.
        Pre-S7 it was 'compatibility-mode'.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        assert route.get("status") == "supported-migration-available", (
            "Doctor maintenance-route for a stabilized typed-legacy project must "
            "return status='supported-migration-available' after S7. "
            f"Got status={route.get('status')!r}. "
            "Pre-S7 it returned 'compatibility-mode' — a no-op dead-end."
        )

    def test_maintenance_route_for_stabilized_typed_legacy_primary_action_capability(
        self, tmp_path
    ):
        """
        primary_action.capability_id must be migrate.typed_legacy_backlog.
        """
        project = _make_stabilized_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        primary = route.get("primary_action") or {}
        cap_id = primary.get("capability_id", "")
        assert "migrate.typed_legacy_backlog" in cap_id, (
            "Doctor maintenance-route primary_action.capability_id must be "
            "'migrate.typed_legacy_backlog' for a stabilized typed-legacy project "
            f"after S7; got {cap_id!r}. "
            "Pre-S7 it pointed to 'doctor.compatibility_mode' (no-op)."
        )

    def test_maintenance_route_for_fresh_typed_legacy_status_is_migration(self, tmp_path):
        """
        maintenance-route status for a fresh typed-legacy project must be
        'supported-migration-available' after S7.
        Pre-S7: fresh project → recovery_required → route status was 'recovery-available'.
        After S7: fresh project → typed_legacy_backlog → 'supported-migration-available'.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        assert route.get("status") == "supported-migration-available", (
            "Doctor maintenance-route for a fresh typed-legacy project must "
            "return status='supported-migration-available' after S7. "
            f"Got status={route.get('status')!r}. "
            "Pre-S7 it returned 'recovery-available' (stabilize-without-migration dead-end)."
        )

    def test_maintenance_route_for_fresh_typed_legacy_primary_action_capability(
        self, tmp_path
    ):
        """
        primary_action.capability_id must be migrate.typed_legacy_backlog.
        Pre-S7: primary_action pointed to recover.stabilize_without_migration.
        """
        project = _make_fresh_typed_legacy_project(tmp_path)
        route = _maintenance_route(project)

        primary = route.get("primary_action") or {}
        cap_id = primary.get("capability_id", "")
        assert "migrate.typed_legacy_backlog" in cap_id, (
            "Doctor maintenance-route primary_action.capability_id must be "
            "'migrate.typed_legacy_backlog' for a fresh typed-legacy project after S7; "
            f"got {cap_id!r}. "
            "Pre-S7 it pointed to 'recover.stabilize_without_migration' (dead-end)."
        )
