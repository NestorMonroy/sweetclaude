from pathlib import Path


def test_recover_skill_delegates_to_recovery_script_and_keeps_safety_gates():
    skill = (Path(__file__).parents[1] / "skills" / "recover" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "sweetclaude:recover" in skill
    assert "Default user entrypoint: `/sweetclaude:recover`" in skill
    assert "No argument is required" in skill
    assert "scripts/recovery/recover_project.py" in skill
    assert "diagnose --project-dir . --pretty" in skill
    assert "plan --project-dir . --pretty" in skill
    assert "mutation_plan" in skill
    assert "approval_receipt_template" in skill
    assert "execute --project-dir . --approve --approval-receipt" in skill
    assert "resume --run-dir" in skill
    assert "rollback --run-dir" in skill
    assert "Never run `sweetclaude:migrate`" in skill
    assert "Never move, rename, delete, or normalize product artifacts manually" in skill
    assert ".sweetclaude/state/recovery-runs/" in skill


def test_setup_skill_ignores_recovery_run_artifacts_by_default():
    skill = (Path(__file__).parents[1] / "skills" / "setup" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "Keep recovery snapshots and manifests out of source control" in skill
    assert ".sweetclaude/state/recovery-runs/" in skill


def test_status_skill_routes_unsafe_layouts_to_recover_not_migrate():
    skill = (Path(__file__).parents[1] / "skills" / "status" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "guard --project-dir . --pretty" in skill
    assert "Run /sweetclaude:recover" in skill
    assert "Do not run /sweetclaude:migrate yet" in skill
    assert "run `/sweetclaude:migrate` first" not in skill


def test_legacy_project_skills_use_recovery_guard_before_migration():
    root = Path(__file__).parents[1] / "skills"
    guarded_skills = [
        "bootstrap",
        "go",
        "project-backlog",
        "project-backlog-triage",
        "project-gh-import-issues",
        "project-gh-sync-issues",
        "project-issues",
    ]

    for name in guarded_skills:
        skill = (root / name / "SKILL.md").read_text(encoding="utf-8")
        assert "guard --project-dir . --pretty" in skill
        assert "/sweetclaude:recover" in skill
        assert "Run: /sweetclaude:migrate" not in skill


def test_bootstrap_v4_hard_stop_classifies_before_recommending_migrate():
    skill = (
        Path(__file__).parents[1] / "skills" / "bootstrap" / "SKILL.md"
    ).read_text(encoding="utf-8")

    guard_idx = skill.index("guard --project-dir . --pretty")
    migrate_idx = skill.index("Run /sweetclaude:migrate only when the guard says")
    assert guard_idx < migrate_idx
    assert "If the guard says recovery is needed, run: /sweetclaude:recover" in skill
    assert "do not recommend migration" in skill


def test_migrate_skill_runs_preflight_before_lock_and_backup():
    skill = (Path(__file__).parents[1] / "skills" / "migrate" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    preflight_idx = skill.index("preflight --project-dir .")
    assert preflight_idx < skill.index('LOCK_FILE=".sweetclaude/state/migration.lock"')
    assert preflight_idx < skill.index('BACKUP_DIR=".sweetclaude/state/backups"')
    assert "Do not create `migration.lock`, backups, copied files, or migration maps" in skill


def test_doctor_skill_does_not_directly_run_taxonomy_migration():
    skill = (Path(__file__).parents[1] / "skills" / "doctor" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "migrate_taxonomy.py" in skill
    assert "Do not invoke\n`migrate_taxonomy.py`" in skill
    assert "run the script directly" not in skill.lower()


def test_doctor_skill_uses_maintenance_router_as_front_door():
    skill = (Path(__file__).parents[1] / "skills" / "doctor" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "doctor.py maintenance-route --project-dir ." in skill
    assert "Store `maintenance_route`. Doctor is the maintenance front door" in skill
    assert "Run safe recovery" in skill
    assert "Start supported migration" in skill
    assert "No migration is recommended for this project" in skill
    assert "compatibility_adjustments" in skill
    assert "Compatibility mode collapsed {collapsed_count} accepted legacy taxonomy" in skill
    assert "Do not `cat` or print\n`.sweetclaude/state/last-doctor-run.json`" in skill
    assert "Use `menu_default` for skip-menu behavior" in skill
    assert "must not skip the menu by itself" in skill
    assert "Continue in compatibility mode" not in skill
    assert "internal commands such as `recover`,\n`_migrate`" in skill
    assert "Step 1 must already have handled and visibly rendered" in skill
    assert "Do not use it to\npresent a migration prompt unless `maintenance_route.status` is\n`supported-migration-available`" in skill


def test_update_skill_decouples_framework_sync_from_project_mutation():
    skill = (Path(__file__).parents[1] / "skills" / "update" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    capability = (
        Path(__file__).parents[1]
        / "skills"
        / "update"
        / "capability-surface.md"
    ).read_text(encoding="utf-8")

    assert "does not run\nproject-state migrations inline" in skill
    assert "--scan-drift" in skill
    assert "--report-drift-for-skill" not in skill
    assert "No project files were changed by update." in skill
    assert "Do not write `doctor-prompt-pending.json` from update" in skill
    assert "Do not execute its project skill-state migration" in skill
    assert "Skip feature configuration from update" in skill
    assert "Skip plan-directory configuration from update" in skill
    assert "Project-state migration is not run inline" in skill
    assert "invoke `sweetclaude:_migrate`" not in skill
    assert "invoke `sweetclaude:purge`" not in skill
    assert "invoke `sweetclaude:adopt`" not in skill
    assert "mv .sweetclaude" not in skill
    assert "configure-plan-dir.py" not in skill
    assert "Both parts must execute" not in capability
    assert "disabled from update" in capability
    assert "Do not execute these\ncommands from update" in capability


def test_fix_sweetclaude_is_redirect_only():
    skill = (
        Path(__file__).parents[1] / "skills" / "fix-sweetclaude" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "replaced by `/sweetclaude:doctor`" in skill
    assert "Invoke `sweetclaude:doctor` now." in skill
    assert "python3" not in skill
    assert "rm " not in skill
    assert "mv " not in skill
    assert "migrate_taxonomy.py" not in skill


def test_user_docs_route_to_no_arg_recover_not_diagnose_subcommand():
    root = Path(__file__).parents[1]
    docs = [
        root / "README.md",
        root / "docs" / "user-guide" / "install.md",
        root / "docs" / "user-guide" / "beta-rescue.md",
        root / "docs" / "user-guide" / "skills-reference.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "/sweetclaude:recover diagnose" not in text

    rescue = (root / "docs" / "user-guide" / "beta-rescue.md").read_text(encoding="utf-8")
    assert "/sweetclaude:recover" in rescue
    assert "Recovery diagnoses first" in rescue


def test_stale_beta_plugin_guard_is_front_door_for_update_bootstrap_and_doctor():
    root = Path(__file__).parents[1]
    for rel in [
        "skills/update/SKILL.md",
        "skills/bootstrap/SKILL.md",
        "skills/doctor/SKILL.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "SC_PLUGIN_STALE_BETA=true" in text
        assert "SweetClaude beta plugin update required" in text
        assert "{SC_PLUGIN_UPDATE_COMMAND}" in text
        assert "Then restart Claude Code and run:" in text
        assert "/sweetclaude:update" in text
        assert "No project files were changed" in text

    doctor = (root / "skills/doctor/SKILL.md").read_text(encoding="utf-8")
    assert doctor.index("Plugin Update Guard") < doctor.index("Maintenance route preflight")

    bootstrap = (root / "skills/bootstrap/SKILL.md").read_text(encoding="utf-8")
    assert bootstrap.index("SC_PLUGIN_STALE_BETA=true") < bootstrap.index("Handle missing or unparseable file")

    update = (root / "skills/update/SKILL.md").read_text(encoding="utf-8")
    assert update.index("SC_PLUGIN_STALE_BETA=true") < update.index("Read current install state")
