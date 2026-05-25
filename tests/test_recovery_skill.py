from pathlib import Path


def test_recover_skill_delegates_to_recovery_script_and_keeps_safety_gates():
    skill = (Path(__file__).parents[1] / "skills" / "recover" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "sweetclaude:recover" in skill
    assert "scripts/recovery/recover_project.py" in skill
    assert "diagnose --project-dir . --pretty" in skill
    assert "plan --project-dir . --pretty" in skill
    assert "execute --project-dir . --approve --pretty" in skill
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
