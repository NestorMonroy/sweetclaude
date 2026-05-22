"""
Tests for scripts/doctor.py (ISSUE-177 E5).

Test file structure follows E5 story order:
  E5-S01: Fixture builder
  E5-S02: Per-category scan tests
  E5-S03: Auto-fix tests
  E5-S04: Content-based backup tests
  E5-S05: Post-fix rescan tests
  E5-S06: Archive integrity tests
  E5-S07: Retention tests
  E5-S08: Suppression tests
  E5-S09: Dry-run simulation tests
  E5-S10: Graceful degradation tests
  E5-S11: Early exit test
  E5-S12: Happy-path test
  E5-S13: Manifest completeness test
"""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from pathlib import Path

from doctor import (
    Finding,
    ProjectState,
    RecipeResult,
    DependencyMissing,
    CHECKS,
    build_project_state,
    build_state_summary,
    _scan,
    check_state_integrity,
    check_hook_health,
    check_storage_lint,
    check_migration_currency,
    check_config_compat,
    check_file_diagnostics,
    check_onboarding_state,
    check_env_wiring,
    create_archive,
    backup_content,
    write_diff,
    write_manifest,
    prune_archives,
    execute_recipe,
    auto_fix,
    post_fix_rescan,
    dry_run,
    record_action,
    persist,
    load_suppressions,
    save_suppressions,
    auto_cleanup_suppressions,
)


# ---------------------------------------------------------------------------
# E5-S01: Fixture builder
# ---------------------------------------------------------------------------

def _write_frontmatter_file(path, frontmatter, body=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"---\n{yaml.safe_dump(frontmatter)}---\n{body}"
    path.write_text(content)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
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


def build_fixture(tmp_path, overrides=None):
    overrides = overrides or {}
    project_dir = tmp_path / "project"

    sc = project_dir / ".sweetclaude"
    state_dir = sc / "state"
    state_dir.mkdir(parents=True)

    sc_yaml = overrides.get("sweetclaude_yaml", {
        "phase_schema_version": 2,
        "framework": {"installed_version": "4.0.8-beta"},
    })
    if sc_yaml is not None:
        (state_dir / "sweetclaude.yaml").write_text(yaml.safe_dump(sc_yaml))

    ss = overrides.get("session_state", {
        "paths": {"product_base": ".sweetclaude/product"},
    })
    if ss is not None:
        (state_dir / "session-state.yaml").write_text(yaml.safe_dump(ss))

    ap = overrides.get("artifact_privacy", {
        "categories": {"product": {"base_path": ".sweetclaude/product"}},
    })
    if ap is not None:
        (sc / "artifact-privacy.yaml").write_text(yaml.safe_dump(ap))

    skills = overrides.get("skills_yaml", {"schema_version": 2, "skills": {}})
    if skills is not None:
        (state_dir / "skills.yaml").write_text(yaml.safe_dump(skills))

    product_base = project_dir / ".sweetclaude" / "product"
    (product_base / "backlog").mkdir(parents=True, exist_ok=True)
    (product_base / "roadmap").mkdir(parents=True, exist_ok=True)

    (sc / "plans").mkdir(parents=True, exist_ok=True)

    claude_md = overrides.get("claude_md", "# Project\n\n## SweetClaude\nConfigured.")
    if claude_md is not None:
        (project_dir / "CLAUDE.md").write_text(claude_md)

    (project_dir / "hooks").mkdir(exist_ok=True)

    for bf in overrides.get("backlog_files", []):
        path = product_base / "backlog" / bf["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if "frontmatter" in bf:
            _write_frontmatter_file(path, bf["frontmatter"], bf.get("body", ""))
        else:
            path.write_text(bf.get("content", ""))

    for rf in overrides.get("roadmap_files", []):
        path = product_base / "roadmap" / rf["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if "frontmatter" in rf:
            _write_frontmatter_file(path, rf["frontmatter"], rf.get("body", ""))
        else:
            path.write_text(rf.get("content", ""))

    for hf in overrides.get("hook_files", []):
        path = project_dir / "hooks" / hf["name"]
        path.write_text(hf["content"])

    if "suppressions" in overrides:
        (state_dir / "doctor-suppressions.json").write_text(
            json.dumps(overrides["suppressions"])
        )

    if "settings_local" in overrides:
        local_dir = project_dir / ".claude"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "settings.local.json").write_text(
            json.dumps(overrides["settings_local"])
        )

    return project_dir


@pytest.fixture
def healthy_project(tmp_path, fake_home):
    return build_fixture(tmp_path)


class TestFixtureBuilder:
    def test_healthy_default_zero_findings(self, healthy_project, fake_home):
        state = build_project_state(healthy_project)
        result = _scan(state)
        assert result["findings"] == [], (
            f"Healthy fixture should produce zero findings, got: "
            f"{[f['id'] for f in result['findings']]}"
        )

    def test_healthy_default_no_skipped_categories(self, healthy_project, fake_home):
        state = build_project_state(healthy_project)
        result = _scan(state)
        assert result["skipped_categories"] == []

    def test_fixture_creates_required_directories(self, healthy_project):
        assert (healthy_project / ".sweetclaude" / "state").is_dir()
        assert (healthy_project / ".sweetclaude" / "product" / "backlog").is_dir()
        assert (healthy_project / ".sweetclaude" / "product" / "roadmap").is_dir()
        assert (healthy_project / ".sweetclaude" / "plans").is_dir()
        assert (healthy_project / "hooks").is_dir()

    def test_fixture_creates_required_files(self, healthy_project):
        state_dir = healthy_project / ".sweetclaude" / "state"
        assert (state_dir / "sweetclaude.yaml").exists()
        assert (state_dir / "session-state.yaml").exists()
        assert (state_dir / "skills.yaml").exists()
        assert (healthy_project / ".sweetclaude" / "artifact-privacy.yaml").exists()
        assert (healthy_project / "CLAUDE.md").exists()

    def test_fixture_overrides_backlog_files(self, tmp_path, fake_home):
        project = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        assert (project / ".sweetclaude" / "product" / "backlog" / "ISSUE-001-test.md").exists()

    def test_fixture_overrides_hook_files(self, tmp_path, fake_home):
        project = build_fixture(tmp_path, overrides={
            "hook_files": [{"name": "test-hook.sh", "content": "#!/bin/bash\nexit 0\n"}],
        })
        assert (project / "hooks" / "test-hook.sh").exists()

    def test_fixture_overrides_suppressions(self, tmp_path, fake_home):
        project = build_fixture(tmp_path, overrides={
            "suppressions": [{"finding_id": "test:id", "suppressed_at": "2026-01-01"}],
        })
        data = json.loads(
            (project / ".sweetclaude" / "state" / "doctor-suppressions.json").read_text()
        )
        assert len(data) == 1
        assert data[0]["finding_id"] == "test:id"

    def test_build_project_state_populates_all_fields(self, healthy_project, fake_home):
        state = build_project_state(healthy_project)
        assert state.project_dir == healthy_project
        assert state.sweetclaude_yaml is not None
        assert state.session_state is not None
        assert state.artifact_privacy is not None
        assert state.skills_yaml is not None
        assert state.hooks_json is not None
        assert state.settings_global is not None
        assert state.claude_md_project is not None
        assert state.installed_version == "4.0.8-beta"
        assert len(state.rules_files) == 3


# ---------------------------------------------------------------------------
# State integrity checks (doctor-state-integrity.feature)
# ---------------------------------------------------------------------------

class TestStateIntegrity:
    """
    Tests for check_state_integrity(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-state-integrity.feature.
    """

    # ------------------------------------------------------------------
    # Scenario: Healthy project produces no state_integrity findings
    # ------------------------------------------------------------------

    def test_healthy_project_produces_no_state_integrity_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_state_integrity(state)
        assert findings == [], (
            f"Healthy project should produce 0 state_integrity findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Scenario: sweetclaude.yaml has a YAML parse error
    # ------------------------------------------------------------------

    def test_yaml_parse_error_in_sweetclaude_yaml(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={"sweetclaude_yaml": None})
        sc_yaml_path = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
        sc_yaml_path.write_text("{{bad: yaml: [unclosed")

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 1
        f = findings[0]
        assert f.id == "state-integrity:yaml-parse:sweetclaude.yaml"
        assert f.severity == "error"
        assert f.fix_type == "prompted"
        assert f.fix_recipe["action"] == "prompt"

    # ------------------------------------------------------------------
    # Scenario: session-state.yaml is missing
    # ------------------------------------------------------------------

    def test_missing_session_state_yaml(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={"session_state": None})

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 1
        f = findings[0]
        assert f.id == "state-integrity:missing:session-state.yaml"
        assert f.severity == "warning"
        assert f.fix_type == "auto"
        assert f.fix_recipe["action"] == "run_script"

    # ------------------------------------------------------------------
    # Scenario: phase_schema_version is not 2
    # ------------------------------------------------------------------

    def test_phase_schema_version_not_2(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "sweetclaude_yaml": {
                "phase_schema_version": 1,
                "framework": {"installed_version": "4.0.8-beta"},
            },
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 1
        f = findings[0]
        assert f.id == "state-integrity:schema-version:sweetclaude.yaml"
        assert f.severity == "warning"
        assert f.fix_type == "report-only"

    # ------------------------------------------------------------------
    # Scenario: installed_version drifts from installed_plugins.json
    # ------------------------------------------------------------------

    def test_installed_version_drift(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "3.0.0"},
            },
        })
        # fake_home already has installed_plugins.json reporting "4.0.8-beta"

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 1
        f = findings[0]
        assert f.id == "state-integrity:version-drift:installed_version"
        assert f.severity == "warning"
        assert f.fix_type == "auto"
        assert f.fix_recipe["action"] == "write_field"
        assert f.fix_recipe["key"] == "framework"
        assert f.fix_recipe["value"]["installed_version"] == "4.0.8-beta"

    # ------------------------------------------------------------------
    # Scenario: product_base diverges between artifact-privacy.yaml and
    #           session-state.yaml
    # ------------------------------------------------------------------

    def test_product_base_drift_between_artifact_privacy_and_session_state(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "artifact_privacy": {
                "categories": {"product": {"base_path": ".sweetclaude/product"}},
            },
            "session_state": {
                "paths": {"product_base": "docs/product"},
            },
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 1
        f = findings[0]
        assert f.id == "state-integrity:product-base-drift:session-state"
        assert f.severity == "warning"
        assert f.fix_type == "auto"
        assert f.fix_recipe["action"] == "run_script"
        assert len(f.file_paths) == 2

    # ------------------------------------------------------------------
    # Scenario: sweetclaude.yaml exists but is empty (parsed as None)
    # ------------------------------------------------------------------

    def test_empty_sweetclaude_yaml_does_not_trigger_parse_or_schema_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"sweetclaude_yaml": None})
        sc_yaml_path = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
        sc_yaml_path.write_text("---\n---")

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        yaml_parse_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:yaml-parse")
        ]
        schema_version_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:schema-version")
        ]
        assert yaml_parse_ids == [], (
            f"Expected no yaml-parse findings but got: {yaml_parse_ids}"
        )
        assert schema_version_ids == [], (
            f"Expected no schema-version findings but got: {schema_version_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Both artifact-privacy and session-state are missing
    # ------------------------------------------------------------------

    def test_both_artifact_privacy_and_session_state_missing(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "artifact_privacy": None,
            "session_state": None,
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        missing_findings = [
            f for f in findings if f.id.startswith("state-integrity:missing")
        ]
        assert len(missing_findings) == 1, (
            f"Expected exactly 1 finding with id prefix 'state-integrity:missing', "
            f"got: {[f.id for f in missing_findings]}"
        )

    # ------------------------------------------------------------------
    # Scenario: sweetclaude.yaml does not exist on disk (R1)
    # ------------------------------------------------------------------

    def test_sweetclaude_yaml_absent_skips_parse_schema_and_version_drift(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"sweetclaude_yaml": None})
        # Do NOT write the file — leave it absent entirely

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        yaml_parse_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:yaml-parse")
        ]
        schema_version_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:schema-version")
        ]
        version_drift_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:version-drift")
        ]
        assert yaml_parse_ids == [], (
            f"Expected no yaml-parse findings when file absent, got: {yaml_parse_ids}"
        )
        assert schema_version_ids == [], (
            f"Expected no schema-version findings when file absent, "
            f"got: {schema_version_ids}"
        )
        assert version_drift_ids == [], (
            f"Expected no version-drift findings when file absent, "
            f"got: {version_drift_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Multiple problems produce multiple findings in a single
    #           run (R2)
    # ------------------------------------------------------------------

    def test_multiple_problems_accumulate_findings(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={"sweetclaude_yaml": None, "session_state": None})
        sc_yaml_path = project_dir / ".sweetclaude" / "state" / "sweetclaude.yaml"
        sc_yaml_path.write_text("{{bad: yaml: [unclosed")
        # session-state.yaml is also absent (session_state=None means not written)

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        assert len(findings) == 2
        finding_ids = [f.id for f in findings]
        assert "state-integrity:yaml-parse:sweetclaude.yaml" in finding_ids, (
            f"Expected yaml-parse finding, got: {finding_ids}"
        )
        assert "state-integrity:missing:session-state.yaml" in finding_ids, (
            f"Expected missing session-state finding, got: {finding_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Trailing slashes on product base paths do not trigger
    #           false drift (R3)
    # ------------------------------------------------------------------

    def test_trailing_slash_normalization_no_false_drift(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "artifact_privacy": {
                "categories": {"product": {"base_path": ".sweetclaude/product/"}},
            },
            "session_state": {
                "paths": {"product_base": ".sweetclaude/product"},
            },
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        drift_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:product-base-drift")
        ]
        assert drift_ids == [], (
            f"Trailing slash difference should not trigger drift, got: {drift_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: framework key missing from sweetclaude.yaml skips
    #           version drift (R4)
    # ------------------------------------------------------------------

    def test_missing_framework_key_skips_version_drift(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                # no "framework" key
            },
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        drift_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:version-drift")
        ]
        assert drift_ids == [], (
            f"Missing framework key should skip version-drift check, got: {drift_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: installed_plugins.json absent skips version drift
    #           silently (R5)
    # ------------------------------------------------------------------

    def test_absent_installed_plugins_json_skips_version_drift(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "3.0.0"},
            },
        })

        plugins_json = (
            fake_home / ".claude" / "plugins" / "installed_plugins.json"
        )
        plugins_json.unlink()

        state = build_project_state(project_dir)
        assert state.installed_version is None, (
            f"Expected installed_version to be None when file absent, "
            f"got: {state.installed_version}"
        )

        findings = check_state_integrity(state)

        drift_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:version-drift")
        ]
        assert drift_ids == [], (
            f"Absent installed_plugins.json should skip version-drift silently, "
            f"got: {drift_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: artifact-privacy with null categories skips product
    #           base drift (R6)
    # ------------------------------------------------------------------

    def test_null_categories_in_artifact_privacy_skips_product_base_drift(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "artifact_privacy": {
                "categories": None,
            },
        })

        state = build_project_state(project_dir)
        findings = check_state_integrity(state)

        drift_ids = [
            f.id for f in findings if f.id.startswith("state-integrity:product-base-drift")
        ]
        assert drift_ids == [], (
            f"Null categories should skip product-base-drift check, got: {drift_ids}"
        )


# ---------------------------------------------------------------------------
# Hook health checks (doctor-hook-health.feature)
# ---------------------------------------------------------------------------

class TestHookHealth:
    """
    Tests for check_hook_health(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-hook-health.feature.
    """

    # ------------------------------------------------------------------
    # Scenario: Healthy project produces no hook_health findings
    # ------------------------------------------------------------------

    def test_healthy_project_produces_no_hook_health_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)
        assert findings == [], (
            f"Healthy project should produce 0 hook_health findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # hooks.json checks
    # ------------------------------------------------------------------

    # Scenario: hooks.json is missing
    def test_hooks_json_missing_produces_error_finding(self, tmp_path, fake_home):
        hooks_json_path = (
            fake_home / ".claude" / "hooks" / "sweetclaude" / "hooks.json"
        )
        hooks_json_path.unlink()

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert len(findings) >= 1, f"Expected at least 1 finding, got: {ids}"
        assert "hook-health:missing:hooks.json" in ids, (
            f"Expected finding 'hook-health:missing:hooks.json' in {ids}"
        )

        f = next(x for x in findings if x.id == "hook-health:missing:hooks.json")
        assert f.severity == "error"
        assert f.fix_type == "prompted"
        assert f.fix_recipe["action"] == "prompt"
        assert f.fix_recipe["type"] == "hook_restore"

    # Scenario: hooks.json is empty dict (not None) produces no finding
    def test_hooks_json_empty_dict_produces_no_missing_finding(
        self, tmp_path, fake_home
    ):
        hooks_json_path = (
            fake_home / ".claude" / "hooks" / "sweetclaude" / "hooks.json"
        )
        hooks_json_path.write_text("{}")

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:missing:hooks.json" not in ids, (
            f"Empty dict hooks.json should not produce missing finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Hook script syntax checks
    # ------------------------------------------------------------------

    # Scenario: Hook script with valid syntax produces no finding
    def test_valid_hook_script_produces_no_syntax_finding(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [{"name": "good-hook.sh", "content": "#!/bin/bash\nexit 0\n"}],
        })
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        syntax_ids = [
            f.id for f in findings if f.id.startswith("hook-health:syntax-error")
        ]
        assert syntax_ids == [], (
            f"Valid hook script should produce no syntax-error finding, got: {syntax_ids}"
        )

    # Scenario: Hook script with syntax error produces error finding
    def test_bad_hook_script_produces_syntax_error_finding(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [{"name": "bad-hook.sh", "content": "#!/bin/bash\nif then\n"}],
        })
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:bad-hook.sh" in ids, (
            f"Expected 'hook-health:syntax-error:bad-hook.sh' in {ids}"
        )

        f = next(x for x in findings if x.id == "hook-health:syntax-error:bad-hook.sh")
        assert f.severity == "error"
        assert f.fix_type == "prompted"
        assert f.fix_recipe["type"] == "hook_restore"

    # Scenario: Multiple hook scripts with mixed syntax
    def test_mixed_hook_scripts_only_bad_gets_syntax_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [
                {"name": "good.sh", "content": "#!/bin/bash\nexit 0\n"},
                {"name": "bad.sh", "content": "#!/bin/bash\nif then\n"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:bad.sh" in ids, (
            f"Expected finding for bad.sh in {ids}"
        )
        assert "hook-health:syntax-error:good.sh" not in ids, (
            f"Should not have finding for good.sh, got: {ids}"
        )

    # Scenario: No hook files in project produces no syntax findings
    def test_no_hook_files_produces_no_syntax_findings(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        syntax_ids = [
            f.id for f in findings if f.id.startswith("hook-health:syntax-error")
        ]
        assert syntax_ids == [], (
            f"No hook files should produce no syntax-error findings, got: {syntax_ids}"
        )

    # Scenario: Empty hook file (zero bytes) passes syntax check
    def test_empty_hook_file_passes_syntax_check(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [{"name": "empty.sh", "content": ""}],
        })
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:empty.sh" not in ids, (
            f"Empty hook file should pass syntax check, got: {ids}"
        )

    # Scenario: Binary content in hook file produces syntax error finding
    def test_binary_hook_file_produces_syntax_error_finding(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [
                {
                    "name": "not-bash.sh",
                    "content": "this is not a valid shell script at all \x00\x01",
                }
            ],
        })
        # Write the actual bytes directly (overriding the text write in build_fixture)
        hook_path = project_dir / "hooks" / "not-bash.sh"
        hook_path.write_bytes(b"this is not a valid shell script at all \x00\x01")

        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:not-bash.sh" in ids, (
            f"Binary hook file should produce syntax error finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Exception handling (bash -n timeout/crash)
    # ------------------------------------------------------------------

    # Scenario: bash -n timeout is silently skipped
    def test_timeout_on_bash_syntax_check_is_silently_skipped(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [{"name": "slow.sh", "content": "#!/bin/bash\nexit 0\n"}],
        })

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if any("slow.sh" in str(c) for c in cmd):
                raise subprocess.TimeoutExpired(cmd, 5)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:slow.sh" not in ids, (
            f"TimeoutExpired should be silently skipped, got: {ids}"
        )

    # Scenario: bash -n OSError is silently skipped and other files still checked
    def test_oserror_on_bash_syntax_check_is_silently_skipped(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "hook_files": [
                {"name": "broken.sh", "content": "#!/bin/bash\nexit 0\n"},
                {"name": "good.sh", "content": "#!/bin/bash\nexit 0\n"},
            ],
        })

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if any("broken.sh" in str(c) for c in cmd):
                raise OSError("bash not found")
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:syntax-error:broken.sh" not in ids, (
            f"OSError should be silently skipped for broken.sh, got: {ids}"
        )
        assert "hook-health:syntax-error:good.sh" not in ids, (
            f"OSError on broken.sh should not affect good.sh check, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Rules file checks
    # ------------------------------------------------------------------

    # Scenario: One rules file missing produces one warning
    def test_one_rules_file_missing_produces_one_warning(self, tmp_path, fake_home):
        rules_file = (
            fake_home / ".claude" / "rules" / "sweetclaude" / "interaction-model.md"
        )
        rules_file.unlink()

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert "hook-health:missing-rule:interaction-model.md" in ids, (
            f"Expected finding for missing interaction-model.md in {ids}"
        )

        f = next(
            x for x in findings
            if x.id == "hook-health:missing-rule:interaction-model.md"
        )
        assert f.severity == "warning"
        assert f.fix_type == "prompted"
        assert f.fix_recipe["action"] == "prompt"
        assert f.fix_recipe["type"] == "hook_restore"

    # Scenario: All three rules files missing produces three warnings
    def test_all_three_rules_files_missing_produces_three_warnings(
        self, tmp_path, fake_home
    ):
        rules_dir = fake_home / ".claude" / "rules" / "sweetclaude"
        for rf in ["interaction-model.md", "phase-gates.md", "tdd-levels.md"]:
            (rules_dir / rf).unlink()

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        rule_ids = [
            f.id for f in findings if f.id.startswith("hook-health:missing-rule")
        ]
        assert len(rule_ids) >= 3, (
            f"Expected at least 3 missing-rule findings, got: {rule_ids}"
        )
        assert "hook-health:missing-rule:interaction-model.md" in rule_ids
        assert "hook-health:missing-rule:phase-gates.md" in rule_ids
        assert "hook-health:missing-rule:tdd-levels.md" in rule_ids

    # ------------------------------------------------------------------
    # Interaction: multiple check blocks fire together
    # ------------------------------------------------------------------

    # Scenario: hooks.json missing and rules file missing accumulate findings
    def test_hooks_json_missing_and_rules_file_missing_accumulate_findings(
        self, tmp_path, fake_home
    ):
        hooks_json_path = (
            fake_home / ".claude" / "hooks" / "sweetclaude" / "hooks.json"
        )
        hooks_json_path.unlink()

        rules_file = (
            fake_home / ".claude" / "rules" / "sweetclaude" / "tdd-levels.md"
        )
        rules_file.unlink()

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_hook_health(state)

        ids = [f.id for f in findings]
        assert len(findings) >= 2, (
            f"Expected at least 2 findings, got: {ids}"
        )
        assert "hook-health:missing:hooks.json" in ids, (
            f"Expected hooks.json finding in {ids}"
        )
        assert "hook-health:missing-rule:tdd-levels.md" in ids, (
            f"Expected tdd-levels.md finding in {ids}"
        )


# ---------------------------------------------------------------------------
# Storage lint checks (doctor-storage-lint.feature)
# ---------------------------------------------------------------------------

def _make_cache_stub(project_dir, next_id="ISSUE-100"):
    """Create a minimal scripts/cache.py stub that returns a safe next_id."""
    cache_script = project_dir / "scripts" / "cache.py"
    cache_script.parent.mkdir(parents=True, exist_ok=True)
    cache_script.write_text(
        f'import json, sys\n'
        f'print(json.dumps({{"next_id": "{next_id}"}}))\n'
    )
    return cache_script


class TestStorageLint:
    """
    Tests for check_storage_lint(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-storage-lint.feature.
    """

    # ------------------------------------------------------------------
    # Negative (healthy)
    # ------------------------------------------------------------------

    # Scenario: Healthy project produces no storage_lint findings
    def test_healthy_project_produces_no_storage_lint_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)
        assert findings == [], (
            f"Healthy project should produce 0 storage_lint findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Cross-location duplicate IDs
    # ------------------------------------------------------------------

    # Scenario: Same ID in both backlog and roadmap produces error
    def test_same_id_in_backlog_and_roadmap_produces_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Dup",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:cross-location-duplicate-id:ISSUE-001" in ids, (
            f"Expected cross-location-duplicate-id finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:cross-location-duplicate-id:ISSUE-001")
        assert f.severity == "error"
        assert f.fix_type == "report-only"

    # Scenario: Different IDs in backlog and roadmap produce no duplicate finding
    def test_different_ids_in_backlog_and_roadmap_no_duplicate_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
            "roadmap_files": [
                {"name": "ISSUE-002-other.md", "frontmatter": {
                    "id": "ISSUE-002", "type": "story", "title": "Other",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        dup_ids = [f.id for f in findings if f.id.startswith("storage-lint:cross-location-duplicate-id")]
        assert dup_ids == [], (
            f"Different IDs should produce no duplicate finding, got: {dup_ids}"
        )

    # Scenario: INDEX.md files are excluded from duplicate ID scan
    def test_index_md_excluded_from_duplicate_id_scan(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "INDEX.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Index",
                }},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Dup",
                }},
            ],
        })
        # No ISSUE-NNN-* backlog files, so no cache.py needed for counter drift
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        dup_ids = [f.id for f in findings if f.id.startswith("storage-lint:cross-location-duplicate-id")]
        assert dup_ids == [], (
            f"INDEX.md should be excluded from duplicate ID scan, got: {dup_ids}"
        )

    # Scenario: MIGRATION-MAP.md files are excluded from duplicate ID scan
    def test_migration_map_excluded_from_duplicate_id_scan(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "MIGRATION-MAP.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Migration map",
                }},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Dup",
                }},
            ],
        })
        # No ISSUE-NNN-* backlog files, so no cache.py needed
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        dup_ids = [f.id for f in findings if f.id.startswith("storage-lint:cross-location-duplicate-id")]
        assert dup_ids == [], (
            f"MIGRATION-MAP.md should be excluded from duplicate ID scan, got: {dup_ids}"
        )

    # Scenario: File with malformed frontmatter excluded from duplicate ID scan
    def test_malformed_frontmatter_excluded_from_duplicate_id_scan(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-broken.md", "content": "no frontmatter here"},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Dup",
                }},
            ],
        })
        # ISSUE-001-broken.md matches ISSUE-(\d+)- so cache.py is required
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        dup_ids = [f.id for f in findings if f.id.startswith("storage-lint:cross-location-duplicate-id")]
        assert dup_ids == [], (
            f"Malformed frontmatter should be excluded from duplicate scan, got: {dup_ids}"
        )

    # ------------------------------------------------------------------
    # Counter drift
    # ------------------------------------------------------------------

    # Scenario: Counter drift raises DependencyMissing when cache.py absent
    def test_counter_drift_raises_dependency_missing_when_cache_absent(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-005-test.md", "frontmatter": {
                    "id": "ISSUE-005", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        # Explicitly do NOT create scripts/cache.py
        state = build_project_state(project_dir)

        with pytest.raises(DependencyMissing):
            check_storage_lint(state)

    # Scenario: No backlog issue files with cache.py absent does not raise
    def test_no_backlog_issue_files_with_cache_absent_does_not_raise(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        # No backlog ISSUE-* files, no cache.py
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)
        assert findings == [], (
            f"No ISSUE files and no cache.py should produce 0 findings, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Counter drift detected when file max exceeds cache max
    def test_counter_drift_detected_when_file_max_exceeds_cache_max(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-010-test.md", "frontmatter": {
                    "id": "ISSUE-010", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        cache_script = project_dir / "scripts" / "cache.py"
        cache_script.parent.mkdir(parents=True, exist_ok=True)
        cache_script.write_text(
            'import json, sys\n'
            'print(json.dumps({"next_id": "ISSUE-005"}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:counter-drift:issue" in ids, (
            f"Expected counter-drift finding when file max > cache max, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:counter-drift:issue")
        assert f.severity == "warning"
        assert f.fix_type == "auto"
        assert f.fix_recipe["action"] == "rebuild_cache"

    # Scenario: No drift when cache max matches or exceeds file max
    def test_no_drift_when_cache_max_exceeds_file_max(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-003-test.md", "frontmatter": {
                    "id": "ISSUE-003", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        cache_script = project_dir / "scripts" / "cache.py"
        cache_script.parent.mkdir(parents=True, exist_ok=True)
        cache_script.write_text(
            'import json, sys\n'
            'print(json.dumps({"next_id": "ISSUE-010"}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:counter-drift:issue" not in ids, (
            f"Cache max >= file max should produce no drift finding, got: {ids}"
        )

    # Scenario: Counter drift exact boundary — file max equals cache max
    def test_counter_drift_exact_boundary_no_finding(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-005-test.md", "frontmatter": {
                    "id": "ISSUE-005", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        cache_script = project_dir / "scripts" / "cache.py"
        cache_script.parent.mkdir(parents=True, exist_ok=True)
        # next_id "ISSUE-006" means cache_max = 6-1 = 5 == file_max of 5: no drift
        cache_script.write_text(
            'import json, sys\n'
            'print(json.dumps({"next_id": "ISSUE-006"}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:counter-drift:issue" not in ids, (
            f"Exact boundary (file max == cache max) should produce no drift finding, got: {ids}"
        )

    # Scenario: Subprocess exception during counter drift silently suppresses drift
    def test_subprocess_exception_silently_suppresses_drift(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-010-test.md", "frontmatter": {
                    "id": "ISSUE-010", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        cache_script = project_dir / "scripts" / "cache.py"
        cache_script.parent.mkdir(parents=True, exist_ok=True)
        cache_script.write_text('raise RuntimeError("broken")\n')

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:counter-drift:issue" not in ids, (
            f"Subprocess exception should silently suppress drift finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # V3 file remnants
    # ------------------------------------------------------------------

    # Scenario: BL-prefixed files on v4 produce warning
    def test_bl_prefixed_files_on_v4_produce_warning(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "BL-001-old.md", "content": "# Old item"},
            ],
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "4.0.8-beta"},
            },
        })
        # BL-001-old.md does not match ISSUE-(\d+)- so no cache.py needed
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:v3-files-present:backlog" in ids, (
            f"Expected v3-files-present finding for BL-prefix files on v4, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:v3-files-present:backlog")
        assert f.severity == "warning"
        assert f.fix_type == "prompted"

    # Scenario: BL-prefixed files on v3 do not produce warning
    def test_bl_prefixed_files_on_v3_no_warning(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "BL-001-old.md", "content": "# Old item"},
            ],
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "3.2.1"},
            },
        })
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:v3-files-present:backlog" not in ids, (
            f"BL-prefix files on v3 should not produce v3-files-present finding, got: {ids}"
        )

    # Scenario: sweetclaude.yaml absent with BL-files does not flag v3 remnants
    def test_sweetclaude_yaml_absent_with_bl_files_no_v3_flag(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "BL-001-old.md", "content": "# Old item"},
            ],
            "sweetclaude_yaml": None,
        })
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:v3-files-present:backlog" not in ids, (
            f"Absent sweetclaude.yaml should not flag v3 remnants, got: {ids}"
        )

    # Scenario: BL-file in subdirectory not detected by non-recursive glob
    def test_bl_file_in_subdirectory_not_detected(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "done/BL-001-old.md", "content": "# Old item"},
            ],
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "4.0.8-beta"},
            },
        })
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:v3-files-present:backlog" not in ids, (
            f"BL-file in subdirectory should not be detected by non-recursive glob, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Done/status mismatch: backlog done/ directory
    # ------------------------------------------------------------------

    # Scenario: File in done/ without done status produces mismatch warning
    def test_file_in_done_without_done_status_produces_mismatch_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "done/ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        # done/ISSUE-001-test.md is found by rglob so cache.py is needed
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" in ids, (
            f"Expected done-status-mismatch finding for active file in done/, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:done-status-mismatch:ISSUE-001-test.md")
        assert f.severity == "warning"
        assert f.fix_type == "prompted"

    # Scenario: File in done/ with status "done" produces no mismatch
    def test_file_in_done_with_done_status_no_mismatch(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "done/ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "done",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" not in ids, (
            f"File in done/ with status 'done' should not produce mismatch, got: {ids}"
        )

    # Scenario: File in done/ with status "abandoned" produces no mismatch
    def test_file_in_done_with_abandoned_status_no_mismatch(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "done/ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "abandoned",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" not in ids, (
            f"File in done/ with status 'abandoned' should not produce mismatch, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Done/status mismatch: backlog root (reverse)
    # ------------------------------------------------------------------

    # Scenario: File in backlog root with done status produces mismatch warning
    def test_file_in_backlog_root_with_done_status_produces_mismatch_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "done",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" in ids, (
            f"Expected done-status-mismatch for root file with done status, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:done-status-mismatch:ISSUE-001-test.md")
        assert f.fix_recipe["action"] == "prompt"
        assert f.fix_recipe["type"] == "file_move"

    # Scenario: File in backlog root with active status produces no mismatch
    def test_file_in_backlog_root_with_active_status_no_mismatch(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" not in ids, (
            f"Root file with active status should produce no mismatch, got: {ids}"
        )

    # Scenario: File in backlog root with abandoned status produces mismatch warning
    def test_file_in_backlog_root_with_abandoned_status_produces_mismatch_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "abandoned",
                }},
            ],
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" in ids, (
            f"Root file with abandoned status should produce mismatch finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:done-status-mismatch:ISSUE-001-test.md")
        assert f.fix_recipe["type"] == "file_move"

    # Scenario: File in archived/ directory with done status not flagged
    def test_file_in_archived_directory_with_done_status_not_flagged(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "archived/ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "done",
                }},
            ],
        })
        # archived/ISSUE-001-test.md is found by rglob so cache.py is needed
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" not in ids, (
            f"File in archived/ with done status should not be flagged, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Done/status mismatch: roadmap issues
    # ------------------------------------------------------------------

    # Scenario: Roadmap issue with done status outside done/ produces mismatch
    def test_roadmap_issue_done_status_outside_done_produces_mismatch(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        issues_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "issues"
        issues_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            issues_dir / "ISSUE-001-test.md",
            {"id": "ISSUE-001", "type": "story", "title": "Test", "status": "done"},
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" in ids, (
            f"Roadmap issue with done status outside done/ should produce mismatch, got: {ids}"
        )

    # Scenario: Roadmap issue in done/ directory is not flagged
    def test_roadmap_issue_in_done_directory_not_flagged(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path)
        done_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "issues" / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            done_dir / "ISSUE-001-test.md",
            {"id": "ISSUE-001", "type": "story", "title": "Test", "status": "done"},
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" not in ids, (
            f"Roadmap issue in done/ should not be flagged, got: {ids}"
        )

    # Scenario: Roadmap issue with abandoned status outside done/ produces mismatch
    def test_roadmap_issue_abandoned_status_outside_done_produces_mismatch(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        issues_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "issues"
        issues_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            issues_dir / "ISSUE-001-test.md",
            {"id": "ISSUE-001", "type": "story", "title": "Test", "status": "abandoned"},
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:done-status-mismatch:ISSUE-001-test.md" in ids, (
            f"Roadmap issue with abandoned status outside done/ should produce mismatch, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Epic missing completion criteria
    # ------------------------------------------------------------------

    # Scenario: Active epic without completion_criteria produces info finding
    def test_active_epic_without_completion_criteria_produces_info_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        epics_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "epics"
        epics_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            epics_dir / "EP-001-test.md",
            {"id": "EP-001", "type": "epic", "title": "Test", "status": "active"},
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert "storage-lint:epic-missing-criteria:EP-001" in ids, (
            f"Expected epic-missing-criteria finding for active epic without criteria, got: {ids}"
        )

        f = next(x for x in findings if x.id == "storage-lint:epic-missing-criteria:EP-001")
        assert f.severity == "info"
        assert f.fix_type == "report-only"

    # Scenario: Done epic without completion_criteria is not flagged
    def test_done_epic_without_completion_criteria_not_flagged(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        epics_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "epics"
        epics_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            epics_dir / "EP-001-test.md",
            {"id": "EP-001", "type": "epic", "title": "Test", "status": "done"},
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        epic_ids = [f.id for f in findings if f.id.startswith("storage-lint:epic-missing-criteria")]
        assert epic_ids == [], (
            f"Done epic without criteria should not be flagged, got: {epic_ids}"
        )

    # Scenario: Active epic with completion_criteria produces no finding
    def test_active_epic_with_completion_criteria_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        epics_dir = project_dir / ".sweetclaude" / "product" / "roadmap" / "epics"
        epics_dir.mkdir(parents=True, exist_ok=True)
        _write_frontmatter_file(
            epics_dir / "EP-001-test.md",
            {
                "id": "EP-001",
                "type": "epic",
                "title": "Test",
                "status": "active",
                "completion_criteria": [{"text": "criterion 1"}],
            },
        )

        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        epic_ids = [f.id for f in findings if f.id.startswith("storage-lint:epic-missing-criteria")]
        assert epic_ids == [], (
            f"Active epic with completion_criteria should produce no finding, got: {epic_ids}"
        )

    # ------------------------------------------------------------------
    # Interaction: multiple check blocks fire together
    # ------------------------------------------------------------------

    # Scenario: Duplicate ID and v3 file findings accumulate
    def test_duplicate_id_and_v3_file_findings_accumulate(self, tmp_path, fake_home):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
                {"name": "BL-001-old.md", "content": "# Old item"},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Dup",
                }},
            ],
            "sweetclaude_yaml": {
                "phase_schema_version": 2,
                "framework": {"installed_version": "4.0.8-beta"},
            },
        })
        _make_cache_stub(project_dir)
        state = build_project_state(project_dir)
        findings = check_storage_lint(state)

        ids = [f.id for f in findings]
        assert len(findings) >= 2, (
            f"Expected at least 2 findings for combined conditions, got: {ids}"
        )
        assert "storage-lint:cross-location-duplicate-id:ISSUE-001" in ids, (
            f"Expected cross-location-duplicate-id finding, got: {ids}"
        )
        assert "storage-lint:v3-files-present:backlog" in ids, (
            f"Expected v3-files-present finding, got: {ids}"
        )


# ---------------------------------------------------------------------------
# Migration currency checks (doctor-migration-currency.feature)
# ---------------------------------------------------------------------------

class TestMigrationCurrency:
    """
    Tests for check_migration_currency(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-migration-currency.feature.
    """

    # ------------------------------------------------------------------
    # Negative (healthy)
    # ------------------------------------------------------------------

    # Scenario: Healthy project produces no migration_currency findings
    def test_healthy_project_produces_no_migration_currency_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)
        assert findings == [], (
            f"Healthy project should produce 0 migration_currency findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Stale drift marker
    # ------------------------------------------------------------------

    # Scenario: pending-drift-decision.yaml exists produces info finding
    def test_pending_drift_decision_yaml_exists_produces_info_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        drift_marker = project_dir / ".sweetclaude" / "state" / "pending-drift-decision.yaml"
        drift_marker.write_text("drift: true\n")

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:stale-drift-marker:pending-drift-decision.yaml" in ids, (
            f"Expected stale-drift-marker finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "migration-currency:stale-drift-marker:pending-drift-decision.yaml")
        assert f.severity == "info"
        assert f.fix_type == "auto"
        assert f.fix_recipe["action"] == "delete_file"

    # Scenario: No drift marker produces no stale-drift finding
    def test_no_drift_marker_produces_no_stale_drift_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        stale_ids = [f.id for f in findings if f.id.startswith("migration-currency:stale-drift-marker")]
        assert stale_ids == [], (
            f"No drift marker should produce no stale-drift finding, got: {stale_ids}"
        )

    # ------------------------------------------------------------------
    # Schema drift via migration runner
    # ------------------------------------------------------------------

    # Scenario: Migration runner absent skips schema drift check
    def test_migration_runner_absent_skips_schema_drift_check(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        # Explicitly do NOT create scripts/migrations/runner.py
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Absent migration runner should skip schema drift check, got: {schema_ids}"
        )

    # Scenario: Migration runner reports schema drift produces warning
    def test_migration_runner_reports_schema_drift_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(
            'import json; print(json.dumps({"findings": [{"file": "test.yaml", "message": "needs upgrade"}]}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_findings = [f for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert len(schema_findings) >= 1, (
            f"Expected at least 1 schema-drift finding, got: {[f.id for f in findings]}"
        )

        first = schema_findings[0]
        assert first.severity == "warning"
        assert first.fix_type == "prompted"

    # Scenario: Migration runner returns empty findings list
    def test_migration_runner_returns_empty_findings_list(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import json; print(json.dumps({"findings": []}))\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Empty findings list should produce no schema-drift findings, got: {schema_ids}"
        )

    # Scenario: Migration runner subprocess times out is silently skipped
    def test_migration_runner_timeout_is_silently_skipped(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import time; time.sleep(30)\n')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if "runner.py" in str(cmd):
                raise subprocess.TimeoutExpired(cmd, 15)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Timeout should be silently skipped, got: {schema_ids}"
        )

    # Scenario: Migration runner returns invalid JSON is silently skipped
    def test_migration_runner_invalid_json_is_silently_skipped(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('print("not json")\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Invalid JSON from runner should be silently skipped, got: {schema_ids}"
        )

    # Scenario: Migration runner exits non-zero is silently skipped
    def test_migration_runner_exits_nonzero_is_silently_skipped(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import sys; sys.exit(1)\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Non-zero exit from runner should be silently skipped, got: {schema_ids}"
        )

    # Scenario: Migration runner returns JSON list directly
    def test_migration_runner_returns_json_list_directly(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(
            'import json; print(json.dumps([{"file": "test.yaml", "message": "needs upgrade"}]))\n'
        )

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_findings = [f for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert len(schema_findings) >= 1, (
            f"JSON list format should produce at least 1 schema-drift finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Migration runner returns valid JSON of unexpected type is silently skipped
    def test_migration_runner_unexpected_json_type_is_silently_skipped(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import json; print(json.dumps("unexpected string"))\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Unexpected JSON type should be silently skipped, got: {schema_ids}"
        )

    # Scenario: Migration runner OSError is silently skipped
    def test_migration_runner_oserror_is_silently_skipped(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path)
        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import json; print(json.dumps({"findings": []}))\n')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if "runner.py" in str(cmd):
                raise OSError("runner not executable")
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"OSError from runner should be silently skipped, got: {schema_ids}"
        )

    # Scenario: Migration runner timeout does not prevent orphan scan (S4)
    def test_migration_runner_timeout_does_not_prevent_orphan_scan(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path)

        runner_path = project_dir / "scripts" / "migrations" / "runner.py"
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text('import time; time.sleep(30)\n')

        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text(
            'import json; print(json.dumps({"orphans": [{"file": "orphan.md"}]}))\n'
        )

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if "runner.py" in str(cmd):
                raise subprocess.TimeoutExpired(cmd, 15)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        schema_ids = [f.id for f in findings if f.id.startswith("migration-currency:schema-drift")]
        assert schema_ids == [], (
            f"Runner timeout should produce no schema-drift findings, got: {schema_ids}"
        )

        orphan_ids = [f.id for f in findings if f.id == "migration-currency:orphans:scan"]
        assert len(orphan_ids) >= 1, (
            f"Runner timeout should not prevent orphan scan, got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Taxonomy drift (old-prefixed files)
    # ------------------------------------------------------------------

    # Scenario: STORY-prefixed file in backlog produces taxonomy drift warning
    def test_story_prefixed_file_produces_taxonomy_drift_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "STORY-001-old.md", "content": "# Old story"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Expected taxonomy-drift finding for STORY-prefix, got: {ids}"
        )

        f = next(x for x in findings if x.id == "migration-currency:taxonomy-drift:old-prefixes")
        assert f.severity == "warning"
        assert f.fix_type == "prompted"

    # Scenario: BUG-prefixed file in backlog produces taxonomy drift warning
    def test_bug_prefixed_file_produces_taxonomy_drift_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "BUG-001-old.md", "content": "# Old bug"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Expected taxonomy-drift finding for BUG-prefix, got: {ids}"
        )

    # Scenario: DEBT-prefixed file in backlog produces taxonomy drift warning
    def test_debt_prefixed_file_produces_taxonomy_drift_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "DEBT-001-old.md", "content": "# Old debt"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Expected taxonomy-drift finding for DEBT-prefix, got: {ids}"
        )

    # Scenario: CHORE-prefixed file in backlog produces taxonomy drift warning
    def test_chore_prefixed_file_produces_taxonomy_drift_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "CHORE-001-old.md", "content": "# Old chore"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Expected taxonomy-drift finding for CHORE-prefix, got: {ids}"
        )

    # Scenario: ISSUE-prefixed file does not produce taxonomy drift
    def test_issue_prefixed_file_does_not_produce_taxonomy_drift(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {
                    "name": "ISSUE-001-test.md",
                    "frontmatter": {"id": "ISSUE-001"},
                }
            ],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        taxonomy_ids = [f.id for f in findings if f.id.startswith("migration-currency:taxonomy-drift")]
        assert taxonomy_ids == [], (
            f"ISSUE-prefix should not produce taxonomy-drift finding, got: {taxonomy_ids}"
        )

    # Scenario: Mid-filename prefix does not match taxonomy drift
    def test_mid_filename_prefix_does_not_match_taxonomy_drift(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "old-STORY-001.md", "content": "# Not a match"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        taxonomy_ids = [f.id for f in findings if f.id.startswith("migration-currency:taxonomy-drift")]
        assert taxonomy_ids == [], (
            f"Mid-filename prefix should not produce taxonomy-drift finding, got: {taxonomy_ids}"
        )

    # Scenario: Backlog directory absent produces no taxonomy drift finding
    def test_backlog_directory_absent_produces_no_taxonomy_drift_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        backlog_dir = project_dir / ".sweetclaude" / "product" / "backlog"
        shutil.rmtree(backlog_dir)

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        taxonomy_ids = [f.id for f in findings if f.id.startswith("migration-currency:taxonomy-drift")]
        assert taxonomy_ids == [], (
            f"Absent backlog directory should produce no taxonomy-drift finding, got: {taxonomy_ids}"
        )

    # Scenario: Old-prefixed file in backlog subdirectory detected by rglob
    def test_old_prefixed_file_in_subdirectory_detected_by_rglob(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "stories/STORY-001-old.md", "content": "# Old story in subdir"}],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Old-prefix in subdirectory should be detected by rglob, got: {ids}"
        )

    # Scenario: Multiple old-prefixed files produce single taxonomy drift finding
    def test_multiple_old_prefixed_files_produce_single_taxonomy_drift_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "STORY-001-old.md", "content": "# Old story"},
                {"name": "BUG-002-old.md", "content": "# Old bug"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        matching = [f for f in findings if f.id == "migration-currency:taxonomy-drift:old-prefixes"]
        assert len(matching) == 1, (
            f"Multiple old-prefix files should produce exactly 1 taxonomy-drift finding, "
            f"got: {len(matching)}"
        )

    # ------------------------------------------------------------------
    # Orphan scan
    # ------------------------------------------------------------------

    # Scenario: Orphan scan script absent skips orphan check
    def test_orphan_scan_script_absent_skips_orphan_check(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        # Explicitly do NOT create scripts/migrate/migrate-v3-to-v4.py
        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        orphan_ids = [f.id for f in findings if f.id.startswith("migration-currency:orphans")]
        assert orphan_ids == [], (
            f"Absent orphan script should skip orphan check, got: {orphan_ids}"
        )

    # Scenario: Orphan scan finds orphans produces warning
    def test_orphan_scan_finds_orphans_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text(
            'import json; print(json.dumps({"orphans": [{"file": "orphan.md"}]}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:orphans:scan" in ids, (
            f"Expected orphans:scan finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "migration-currency:orphans:scan")
        assert f.severity == "warning"
        assert f.fix_type == "prompted"

    # Scenario: Orphan scan finds no orphans produces no finding
    def test_orphan_scan_finds_no_orphans_produces_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text(
            'import json; print(json.dumps({"orphans": []}))\n'
        )

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        ids = [f.id for f in findings]
        assert "migration-currency:orphans:scan" not in ids, (
            f"Empty orphans list should produce no finding, got: {ids}"
        )

    # Scenario: Orphan scan subprocess timeout is silently skipped
    def test_orphan_scan_timeout_is_silently_skipped(
        self, tmp_path, fake_home, monkeypatch
    ):
        project_dir = build_fixture(tmp_path)
        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text('import time; time.sleep(30)\n')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if "migrate-v3-to-v4.py" in str(cmd):
                raise subprocess.TimeoutExpired(cmd, 15)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        orphan_ids = [f.id for f in findings if f.id.startswith("migration-currency:orphans")]
        assert orphan_ids == [], (
            f"Orphan scan timeout should be silently skipped, got: {orphan_ids}"
        )

    # Scenario: Orphan scan returns invalid JSON is silently skipped
    def test_orphan_scan_invalid_json_is_silently_skipped(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text('print("not json")\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        orphan_ids = [f.id for f in findings if f.id.startswith("migration-currency:orphans")]
        assert orphan_ids == [], (
            f"Invalid JSON from orphan script should be silently skipped, got: {orphan_ids}"
        )

    # Scenario: Orphan scan exits non-zero is silently skipped
    def test_orphan_scan_exits_nonzero_is_silently_skipped(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        orphan_script = project_dir / "scripts" / "migrate" / "migrate-v3-to-v4.py"
        orphan_script.parent.mkdir(parents=True, exist_ok=True)
        orphan_script.write_text('import sys; sys.exit(1)\n')

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        orphan_ids = [f.id for f in findings if f.id.startswith("migration-currency:orphans")]
        assert orphan_ids == [], (
            f"Non-zero orphan exit should be silently skipped, got: {orphan_ids}"
        )

    # ------------------------------------------------------------------
    # Interaction: multiple check blocks fire together
    # ------------------------------------------------------------------

    # Scenario: Drift marker and taxonomy drift findings accumulate
    def test_drift_marker_and_taxonomy_drift_findings_accumulate(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [{"name": "STORY-001-old.md", "content": "# Old story"}],
        })
        drift_marker = project_dir / ".sweetclaude" / "state" / "pending-drift-decision.yaml"
        drift_marker.write_text("drift: true\n")

        state = build_project_state(project_dir)
        findings = check_migration_currency(state)

        assert len(findings) >= 2, (
            f"Expected at least 2 findings with both conditions, "
            f"got: {[f.id for f in findings]}"
        )

        ids = [f.id for f in findings]
        assert "migration-currency:stale-drift-marker:pending-drift-decision.yaml" in ids, (
            f"Expected stale-drift-marker finding in {ids}"
        )
        assert "migration-currency:taxonomy-drift:old-prefixes" in ids, (
            f"Expected taxonomy-drift finding in {ids}"
        )


# ---------------------------------------------------------------------------
# Config compat checks (doctor-config-compat.feature)
# ---------------------------------------------------------------------------

class TestConfigCompat:
    """
    Tests for check_config_compat(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-config-compat.feature.
    """

    # ------------------------------------------------------------------
    # Negative (healthy)
    # ------------------------------------------------------------------

    # Scenario: Healthy project produces no config_compat findings
    def test_healthy_project_produces_no_config_compat_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)
        assert findings == [], (
            f"Healthy project should produce 0 config_compat findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # F1: allowedTools missing required tools
    # ------------------------------------------------------------------

    # Scenario: Global settings missing Agent from allowedTools produces error
    def test_global_settings_missing_agent_from_allowed_tools_produces_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": ["Read", "Edit", "Bash", "Write"],
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        ids = [f.id for f in findings]
        assert "config-compat:F1:~/.claude/settings.json:Agent" in ids, (
            f"Expected F1 finding for missing Agent in global settings, got: {ids}"
        )
        f = next(x for x in findings if x.id == "config-compat:F1:~/.claude/settings.json:Agent")
        assert f.severity == "error"
        assert f.fix_type == "prompted"

    # Scenario: Global settings missing Bash from allowedTools produces error
    def test_global_settings_missing_bash_from_allowed_tools_produces_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": ["Read", "Edit", "Agent", "Write"],
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        ids = [f.id for f in findings]
        assert "config-compat:F1:~/.claude/settings.json:Bash" in ids, (
            f"Expected F1 finding for missing Bash in global settings, got: {ids}"
        )

    # Scenario: Global settings missing Write from allowedTools produces error
    def test_global_settings_missing_write_from_allowed_tools_produces_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": ["Read", "Edit", "Agent", "Bash"],
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        ids = [f.id for f in findings]
        assert "config-compat:F1:~/.claude/settings.json:Write" in ids, (
            f"Expected F1 finding for missing Write in global settings, got: {ids}"
        )

    # Scenario: Local settings missing required tool produces error
    def test_local_settings_missing_agent_from_allowed_tools_produces_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "settings_local": {
                "allowedTools": ["Read", "Edit", "Bash", "Write"],
            },
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        ids = [f.id for f in findings]
        assert "config-compat:F1:.claude/settings.local.json:Agent" in ids, (
            f"Expected F1 finding for missing Agent in local settings, got: {ids}"
        )

    # Scenario: AllowedTools containing all required tools produces no F1 finding
    def test_allowed_tools_containing_all_required_tools_produces_no_f1_finding(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": ["Read", "Edit", "Bash", "Write", "Agent"],
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f1_ids = [f.id for f in findings if f.id.startswith("config-compat:F1")]
        assert f1_ids == [], (
            f"All required tools present should produce no F1 finding, got: {f1_ids}"
        )

    # Scenario: No allowedTools key at all produces no F1 finding
    def test_no_allowed_tools_key_produces_no_f1_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f1_ids = [f.id for f in findings if f.id.startswith("config-compat:F1")]
        assert f1_ids == [], (
            f"No allowedTools key should produce no F1 finding, got: {f1_ids}"
        )

    # Scenario: Empty allowedTools list produces F1 for all three required tools
    def test_empty_allowed_tools_produces_f1_for_all_three_required_tools(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": [],
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        ids = [f.id for f in findings]
        assert "config-compat:F1:~/.claude/settings.json:Agent" in ids, (
            f"Expected F1:Agent, got: {ids}"
        )
        assert "config-compat:F1:~/.claude/settings.json:Bash" in ids, (
            f"Expected F1:Bash, got: {ids}"
        )
        assert "config-compat:F1:~/.claude/settings.json:Write" in ids, (
            f"Expected F1:Write, got: {ids}"
        )

    # ------------------------------------------------------------------
    # F2: non-SweetClaude hooks on test files
    # ------------------------------------------------------------------

    # Scenario: Non-SC hook targeting test files produces error
    def test_non_sc_hook_targeting_test_files_produces_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "test",
                        "hooks": [{"command": "run-linter"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_findings = [f for f in findings if f.id.startswith("config-compat:F2")]
        assert len(f2_findings) >= 1, (
            f"Expected at least 1 F2 finding, got: {[f.id for f in findings]}"
        )
        assert f2_findings[0].severity == "error"

    # Scenario: Hook targeting test files with sweetclaude command is not flagged
    def test_hook_with_sweetclaude_command_not_flagged_as_f2(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "test",
                        "hooks": [{"command": "sweetclaude run-tests"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_ids = [f.id for f in findings if f.id.startswith("config-compat:F2")]
        assert f2_ids == [], (
            f"Hook with 'sweetclaude' command should not be flagged as F2, got: {f2_ids}"
        )

    # Scenario: Hook targeting test files with plugin root variable is not flagged
    def test_hook_with_plugin_root_variable_not_flagged_as_f2(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "test",
                        "hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/run-tests"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_ids = [f.id for f in findings if f.id.startswith("config-compat:F2")]
        assert f2_ids == [], (
            f"Hook with '${{CLAUDE_PLUGIN_ROOT}}' command should not be flagged as F2, got: {f2_ids}"
        )

    # Scenario: Hook targeting spec files produces F2 error
    def test_hook_targeting_spec_files_produces_f2_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "spec",
                        "hooks": [{"command": "run-linter"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_findings = [f for f in findings if f.id.startswith("config-compat:F2")]
        assert len(f2_findings) >= 1, (
            f"Hook targeting 'spec' with external command should produce F2 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Hook not targeting test/spec files is not flagged as F2
    def test_hook_not_targeting_test_spec_files_not_flagged_as_f2(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "src",
                        "hooks": [{"command": "run-linter"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_ids = [f.id for f in findings if f.id.startswith("config-compat:F2")]
        assert f2_ids == [], (
            f"Hook targeting 'src' should not be flagged as F2, got: {f2_ids}"
        )

    # ------------------------------------------------------------------
    # F3: direct test runner in hooks
    # ------------------------------------------------------------------

    # Scenario: Hook command containing "pytest" produces F3 error
    def test_hook_with_pytest_command_produces_f3_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "pytest tests/"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f3_findings) >= 1, (
            f"Hook with 'pytest' command should produce F3 finding, "
            f"got: {[f.id for f in findings]}"
        )
        assert f3_findings[0].severity == "error"

    # Scenario: Hook command containing "npm test" produces F3 error
    def test_hook_with_npm_test_command_produces_f3_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "npm test"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f3_findings) >= 1, (
            f"Hook with 'npm test' command should produce F3 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Hook command containing "cargo test" produces F3 error
    def test_hook_with_cargo_test_command_produces_f3_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "cargo test --release"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f3_findings) >= 1, (
            f"Hook with 'cargo test' command should produce F3 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Hook command containing "jest " with trailing space produces F3 error
    def test_hook_with_jest_command_produces_f3_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "jest --coverage"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f3_findings) >= 1, (
            f"Hook with 'jest ' command should produce F3 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Hook command containing "go test" produces F3 error
    def test_hook_with_go_test_command_produces_f3_error(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "go test ./..."}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f3_findings) >= 1, (
            f"Hook with 'go test' command should produce F3 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Hook command not containing any test runner is not flagged as F3
    def test_hook_without_test_runner_not_flagged_as_f3(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "anything",
                        "hooks": [{"command": "echo done"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f3_ids = [f.id for f in findings if f.id.startswith("config-compat:F3")]
        assert f3_ids == [], (
            f"'echo done' should not be flagged as F3, got: {f3_ids}"
        )

    # Scenario: Hook with test matcher and test runner command produces both F2 and F3
    def test_hook_with_test_matcher_and_test_runner_produces_both_f2_and_f3(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "test",
                        "hooks": [{"command": "pytest tests/"}],
                    }
                ]
            },
        }))
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f2_findings = [f for f in findings if f.id.startswith("config-compat:F2")]
        f3_findings = [f for f in findings if f.id.startswith("config-compat:F3")]
        assert len(f2_findings) >= 1, (
            f"Expected at least 1 F2 finding, got: {[f.id for f in findings]}"
        )
        assert len(f3_findings) >= 1, (
            f"Expected at least 1 F3 finding, got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # F4: skip-hooks instructions in text sources
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing "--no-verify" produces F4 error
    def test_claude_md_with_no_verify_produces_f4_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nAlways use --no-verify when committing.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f4_findings = [f for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f4_findings) >= 1, (
            f"Expected at least 1 F4 finding for '--no-verify', "
            f"got: {[f.id for f in findings]}"
        )
        assert f4_findings[0].severity == "error"
        assert f4_findings[0].fix_type == "prompted"

    # Scenario: CLAUDE.md containing "skip hooks" produces F4 error
    def test_claude_md_with_skip_hooks_produces_f4_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nYou can skip hooks if needed.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f4_findings = [f for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f4_findings) >= 1, (
            f"Expected at least 1 F4 finding for 'skip hooks', "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: SweetClaude rules files are excluded from text scanning
    def test_sweetclaude_rules_files_excluded_from_text_scanning(
        self, tmp_path, fake_home
    ):
        rules_path = fake_home / ".claude" / "rules" / "sweetclaude" / "interaction-model.md"
        rules_path.write_text("# Rules\nAlways skip hooks when possible.\n")

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f4_ids = [f.id for f in findings if f.id.startswith("config-compat:F4")]
        assert f4_ids == [], (
            f"SweetClaude rules files should be excluded from text scanning, got: {f4_ids}"
        )

    # Scenario: Non-SweetClaude rules file containing flagged pattern produces finding
    def test_non_sweetclaude_rules_file_with_flagged_pattern_produces_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        state.rules_files["myproject/coding.md"] = "skip hooks always"
        findings = check_config_compat(state)

        f4_findings = [f for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f4_findings) >= 1, (
            f"Non-SC rules file with 'skip hooks' should produce F4 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Global CLAUDE.md containing skip-hooks pattern produces F4 error
    def test_global_claude_md_with_bypass_hooks_produces_f4_error(
        self, tmp_path, fake_home
    ):
        (fake_home / ".claude" / "CLAUDE.md").write_text(
            "bypass hooks when possible\n"
        )
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f4_findings = [f for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f4_findings) >= 1, (
            f"Global CLAUDE.md with 'bypass hooks' should produce F4 finding, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # W1: time-estimate instructions
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing "estimate" produces W1 warning
    def test_claude_md_with_estimate_produces_w1_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nAlways provide an estimate for tasks.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        w1_findings = [f for f in findings if f.id.startswith("config-compat:W1")]
        assert len(w1_findings) >= 1, (
            f"Expected at least 1 W1 finding for 'estimate', "
            f"got: {[f.id for f in findings]}"
        )
        assert w1_findings[0].severity == "warning"

    # Scenario: CLAUDE.md containing "story points" produces W1 warning
    def test_claude_md_with_story_points_produces_w1_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nInclude story points in your output.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        w1_findings = [f for f in findings if f.id.startswith("config-compat:W1")]
        assert len(w1_findings) >= 1, (
            f"Expected at least 1 W1 finding for 'story points', "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # W2: comment-everywhere instructions
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing "always add comments" produces W2 warning
    def test_claude_md_with_always_add_comments_produces_w2_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nAlways add comments to every function.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        w2_findings = [f for f in findings if f.id.startswith("config-compat:W2")]
        assert len(w2_findings) >= 1, (
            f"Expected at least 1 W2 finding for 'always add comments', "
            f"got: {[f.id for f in findings]}"
        )
        assert w2_findings[0].severity == "warning"

    # ------------------------------------------------------------------
    # W3: skip-tests instructions
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing "skip tests" produces W3 warning
    def test_claude_md_with_skip_tests_produces_w3_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nYou can skip tests if the change is small.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        w3_findings = [f for f in findings if f.id.startswith("config-compat:W3")]
        assert len(w3_findings) >= 1, (
            f"Expected at least 1 W3 finding for 'skip tests', "
            f"got: {[f.id for f in findings]}"
        )
        assert w3_findings[0].severity == "warning"

    # ------------------------------------------------------------------
    # W4: skip-confirmation instructions
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing "proceed without asking" produces W4 warning
    def test_claude_md_with_proceed_without_asking_produces_w4_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nProceed without asking for confirmation.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        w4_findings = [f for f in findings if f.id.startswith("config-compat:W4")]
        assert len(w4_findings) >= 1, (
            f"Expected at least 1 W4 finding for 'proceed without asking', "
            f"got: {[f.id for f in findings]}"
        )
        assert w4_findings[0].severity == "warning"

    # ------------------------------------------------------------------
    # I1: duplicate phase-dwelling rule
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing phase-dwelling duplicate produces I1 info
    def test_claude_md_with_phase_dwelling_duplicate_produces_i1_info(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nNever ask if ready to move on.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        i1_findings = [f for f in findings if f.id.startswith("config-compat:I1")]
        assert len(i1_findings) >= 1, (
            f"Expected at least 1 I1 finding for 'never ask if ready to move', "
            f"got: {[f.id for f in findings]}"
        )
        assert i1_findings[0].severity == "info"
        assert i1_findings[0].fix_type == "report-only"

    # ------------------------------------------------------------------
    # I2: duplicate proposal-mode rule
    # ------------------------------------------------------------------

    # Scenario: CLAUDE.md containing proposal-mode duplicate produces I2 info
    def test_claude_md_with_proposal_mode_duplicate_produces_i2_info(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nPropose don't ask.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        i2_findings = [f for f in findings if f.id.startswith("config-compat:I2")]
        assert len(i2_findings) >= 1, (
            f"Expected at least 1 I2 finding for 'propose don\\'t ask', "
            f"got: {[f.id for f in findings]}"
        )
        assert i2_findings[0].severity == "info"
        assert i2_findings[0].fix_type == "report-only"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    # Scenario: Pattern matching is case-insensitive
    def test_pattern_matching_is_case_insensitive(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nSKIP HOOKS in production.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        f4_findings = [f for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f4_findings) >= 1, (
            f"Pattern matching should be case-insensitive; 'SKIP HOOKS' should produce F4, "
            f"got: {[f.id for f in findings]}"
        )

    # Scenario: Info findings have empty fix_recipe
    def test_info_findings_have_empty_fix_recipe(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nPropose don't ask.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        i2_findings = [f for f in findings if f.id.startswith("config-compat:I2")]
        assert len(i2_findings) >= 1, (
            f"Expected at least 1 I2 finding, got: {[f.id for f in findings]}"
        )
        assert not i2_findings[0].fix_recipe, (
            f"I2 finding fix_recipe should be empty, got: {i2_findings[0].fix_recipe}"
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    # Scenario: F1 and F4 findings from different sources accumulate
    def test_f1_and_f4_findings_from_different_sources_accumulate(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({
            "plansDirectory": ".sweetclaude/plans",
            "allowedTools": ["Read", "Edit", "Bash", "Write"],
        }))
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n\nAlways use --no-verify when committing.\n",
        })
        state = build_project_state(project_dir)
        findings = check_config_compat(state)

        assert len(findings) >= 2, (
            f"Expected at least 2 findings for combined F1 + F4 conditions, "
            f"got: {[f.id for f in findings]}"
        )
        f1_ids = [f.id for f in findings if f.id.startswith("config-compat:F1")]
        f4_ids = [f.id for f in findings if f.id.startswith("config-compat:F4")]
        assert len(f1_ids) >= 1, f"Expected at least 1 F1 finding, got: {[f.id for f in findings]}"
        assert len(f4_ids) >= 1, f"Expected at least 1 F4 finding, got: {[f.id for f in findings]}"


# ---------------------------------------------------------------------------
# Onboarding state checks (doctor-onboarding-state.feature)
# ---------------------------------------------------------------------------

class TestOnboardingState:
    """
    Tests for check_onboarding_state(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-onboarding-state.feature.
    """

    # ------------------------------------------------------------------
    # Scenario: Healthy project produces no onboarding_state findings
    # ------------------------------------------------------------------

    def test_healthy_project_produces_no_onboarding_state_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)
        assert findings == [], (
            f"Healthy project should produce 0 onboarding_state findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml missing when state directory exists produces
    #           info finding
    # ------------------------------------------------------------------

    def test_skills_yaml_missing_when_state_dir_exists_produces_info_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"skills_yaml": None})
        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        ids = [f.id for f in findings]
        assert "onboarding-state:missing:skills.yaml" in ids, (
            f"Expected 'onboarding-state:missing:skills.yaml' in {ids}"
        )

        f = next(x for x in findings if x.id == "onboarding-state:missing:skills.yaml")
        assert f.severity == "info", (
            f"Expected severity 'info', got: {f.severity}"
        )
        assert f.fix_type == "prompted", (
            f"Expected fix_type 'prompted', got: {f.fix_type}"
        )
        assert f.fix_recipe["action"] == "prompt", (
            f"Expected fix_recipe action 'prompt', got: {f.fix_recipe.get('action')}"
        )
        assert f.fix_recipe["type"] == "bootstrap", (
            f"Expected fix_recipe type 'bootstrap', got: {f.fix_recipe.get('type')}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml missing when state directory absent produces
    #           no finding
    # ------------------------------------------------------------------

    def test_skills_yaml_missing_when_state_dir_absent_produces_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"skills_yaml": None})
        state_dir = project_dir / ".sweetclaude" / "state"
        shutil.rmtree(state_dir)

        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        missing_ids = [f.id for f in findings if f.id.startswith("onboarding-state:missing")]
        assert missing_ids == [], (
            f"Absent state dir should produce no missing finding, got: {missing_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml with schema_version 1 produces warning
    # ------------------------------------------------------------------

    def test_skills_yaml_schema_version_1_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(
            tmp_path,
            overrides={"skills_yaml": {"schema_version": 1, "skills": {}}},
        )
        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        ids = [f.id for f in findings]
        assert "onboarding-state:schema-v1:skills.yaml" in ids, (
            f"Expected 'onboarding-state:schema-v1:skills.yaml' in {ids}"
        )

        f = next(x for x in findings if x.id == "onboarding-state:schema-v1:skills.yaml")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )
        assert f.fix_type == "prompted", (
            f"Expected fix_type 'prompted', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml with schema_version 2 produces no finding
    # ------------------------------------------------------------------

    def test_skills_yaml_schema_version_2_produces_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        schema_v1_ids = [
            f.id for f in findings if f.id.startswith("onboarding-state:schema-v1")
        ]
        assert schema_v1_ids == [], (
            f"skills.yaml with schema_version 2 should produce no schema-v1 finding, "
            f"got: {schema_v1_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml with no schema_version key produces no
    #           schema finding
    # ------------------------------------------------------------------

    def test_skills_yaml_no_schema_version_key_produces_no_schema_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(
            tmp_path,
            overrides={"skills_yaml": {"skills": {}}},
        )
        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        schema_v1_ids = [
            f.id for f in findings if f.id.startswith("onboarding-state:schema-v1")
        ]
        assert schema_v1_ids == [], (
            f"skills.yaml with no schema_version key should produce no schema-v1 finding, "
            f"got: {schema_v1_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: skills.yaml that is empty (parsed as None) produces
    #           missing finding
    # ------------------------------------------------------------------

    def test_skills_yaml_empty_parsed_as_none_produces_missing_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"skills_yaml": None})
        skills_path = project_dir / ".sweetclaude" / "state" / "skills.yaml"
        skills_path.write_text("")

        state = build_project_state(project_dir)
        findings = check_onboarding_state(state)

        ids = [f.id for f in findings]
        assert "onboarding-state:missing:skills.yaml" in ids, (
            f"Empty skills.yaml (parsed as None) should produce missing finding, "
            f"got: {ids}"
        )


# ---------------------------------------------------------------------------
# Env wiring checks (doctor-env-wiring.feature)
# ---------------------------------------------------------------------------

class TestEnvWiring:
    """
    Tests for check_env_wiring(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-env-wiring.feature.
    """

    # ------------------------------------------------------------------
    # Scenario: Healthy project produces no env_wiring findings
    # ------------------------------------------------------------------

    def test_healthy_project_produces_no_env_wiring_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)
        assert findings == [], (
            f"Healthy project should produce 0 env_wiring findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Scenario: Plans directory missing produces info finding
    # ------------------------------------------------------------------

    def test_plans_directory_missing_produces_info_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        plans_dir = project_dir / ".sweetclaude" / "plans"
        shutil.rmtree(plans_dir)

        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        ids = [f.id for f in findings]
        assert "env-wiring:missing:plans-directory" in ids, (
            f"Expected 'env-wiring:missing:plans-directory' in {ids}"
        )

        f = next(x for x in findings if x.id == "env-wiring:missing:plans-directory")
        assert f.severity == "info", (
            f"Expected severity 'info', got: {f.severity}"
        )
        assert f.fix_type == "auto", (
            f"Expected fix_type 'auto', got: {f.fix_type}"
        )
        assert f.fix_recipe["action"] == "create_dir", (
            f"Expected fix_recipe action 'create_dir', got: {f.fix_recipe.get('action')}"
        )

    # ------------------------------------------------------------------
    # Scenario: Global settings without plansDirectory produces warning
    # ------------------------------------------------------------------

    def test_global_settings_without_plans_directory_produces_warning(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({}))

        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        ids = [f.id for f in findings]
        assert "env-wiring:plans-directory-unset:settings_global" in ids, (
            f"Expected 'env-wiring:plans-directory-unset:settings_global' in {ids}"
        )

        f = next(
            x for x in findings
            if x.id == "env-wiring:plans-directory-unset:settings_global"
        )
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )
        assert f.fix_type == "auto", (
            f"Expected fix_type 'auto', got: {f.fix_type}"
        )
        assert f.fix_recipe["action"] == "write_field", (
            f"Expected fix_recipe action 'write_field', got: {f.fix_recipe.get('action')}"
        )

    # ------------------------------------------------------------------
    # Scenario: Global settings with plansDirectory set produces no finding
    # ------------------------------------------------------------------

    def test_global_settings_with_plans_directory_produces_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        unset_ids = [
            f.id for f in findings
            if f.id.startswith("env-wiring:plans-directory-unset")
        ]
        assert unset_ids == [], (
            f"Global settings with plansDirectory set should produce no unset finding, "
            f"got: {unset_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Local settings without plansDirectory checked when global is absent
    # ------------------------------------------------------------------

    def test_local_settings_checked_when_global_settings_absent(
        self, tmp_path, fake_home
    ):
        (fake_home / ".claude" / "settings.json").unlink()

        project_dir = build_fixture(
            tmp_path,
            overrides={"settings_local": {"someKey": "value"}},
        )
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        ids = [f.id for f in findings]
        assert "env-wiring:plans-directory-unset:settings_local" in ids, (
            f"Expected 'env-wiring:plans-directory-unset:settings_local' in {ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: plansDirectory check stops after first settings source with the key
    # ------------------------------------------------------------------

    def test_plans_directory_check_stops_after_first_source_with_key(
        self, tmp_path, fake_home
    ):
        # Global already has plansDirectory set (via fake_home fixture default).
        # Local settings deliberately lacks plansDirectory.
        project_dir = build_fixture(
            tmp_path,
            overrides={"settings_local": {"someKey": "value"}},
        )
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        unset_ids = [
            f.id for f in findings
            if f.id.startswith("env-wiring:plans-directory-unset")
        ]
        assert unset_ids == [], (
            f"Check should stop after global (which has the key); "
            f"no unset finding expected, got: {unset_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: CLAUDE.md without sweetclaude mention produces warning
    # ------------------------------------------------------------------

    def test_claude_md_without_sweetclaude_mention_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\nNo framework mention here.",
        })
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        ids = [f.id for f in findings]
        assert "env-wiring:claude-md-missing-section:CLAUDE.md" in ids, (
            f"Expected 'env-wiring:claude-md-missing-section:CLAUDE.md' in {ids}"
        )

        f = next(
            x for x in findings
            if x.id == "env-wiring:claude-md-missing-section:CLAUDE.md"
        )
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )
        assert f.fix_type == "report-only", (
            f"Expected fix_type 'report-only', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: CLAUDE.md mentioning sweetclaude produces no finding
    # ------------------------------------------------------------------

    def test_claude_md_mentioning_sweetclaude_produces_no_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        missing_ids = [
            f.id for f in findings
            if f.id.startswith("env-wiring:claude-md-missing-section")
        ]
        assert missing_ids == [], (
            f"CLAUDE.md with sweetclaude mention should produce no missing-section finding, "
            f"got: {missing_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Case-insensitive match for sweetclaude in CLAUDE.md
    # ------------------------------------------------------------------

    def test_case_insensitive_match_for_sweetclaude_in_claude_md(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "claude_md": "# Project\n## SweetClaude Rules\nHere.",
        })
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        missing_ids = [
            f.id for f in findings
            if f.id.startswith("env-wiring:claude-md-missing-section")
        ]
        assert missing_ids == [], (
            f"'SweetClaude' in mixed case should match case-insensitively; "
            f"no missing-section finding expected, got: {missing_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: CLAUDE.md absent produces no missing-section finding
    # ------------------------------------------------------------------

    def test_claude_md_absent_produces_no_missing_section_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={"claude_md": None})
        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        missing_ids = [
            f.id for f in findings
            if f.id.startswith("env-wiring:claude-md-missing-section")
        ]
        assert missing_ids == [], (
            f"Absent CLAUDE.md should produce no missing-section finding, "
            f"got: {missing_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Plans directory missing and settings unset accumulate
    # ------------------------------------------------------------------

    def test_plans_directory_missing_and_settings_unset_accumulate(
        self, tmp_path, fake_home
    ):
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.write_text(json.dumps({}))

        project_dir = build_fixture(tmp_path)
        plans_dir = project_dir / ".sweetclaude" / "plans"
        shutil.rmtree(plans_dir)

        state = build_project_state(project_dir)
        findings = check_env_wiring(state)

        assert len(findings) >= 2, (
            f"Expected at least 2 findings for combined conditions, "
            f"got: {[f.id for f in findings]}"
        )

        ids = [f.id for f in findings]
        assert "env-wiring:missing:plans-directory" in ids, (
            f"Expected 'env-wiring:missing:plans-directory' in {ids}"
        )
        assert "env-wiring:plans-directory-unset:settings_global" in ids, (
            f"Expected 'env-wiring:plans-directory-unset:settings_global' in {ids}"
        )


# ---------------------------------------------------------------------------
# File diagnostics checks (doctor-file-diagnostics.feature)
# ---------------------------------------------------------------------------

class TestFileDiagnostics:
    """
    Tests for check_file_diagnostics(state) -> list[Finding].

    Each method corresponds to one Gherkin scenario in
    tests/features/doctor-file-diagnostics.feature.
    """

    # ------------------------------------------------------------------
    # Scenario: Healthy project produces no file_diagnostics findings
    # ------------------------------------------------------------------

    def test_healthy_project_produces_no_file_diagnostics_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path)
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)
        assert findings == [], (
            f"Healthy project should produce 0 file_diagnostics findings, "
            f"got: {[f.id for f in findings]}"
        )

    # ------------------------------------------------------------------
    # Scenario: File without frontmatter delimiter produces error
    # ------------------------------------------------------------------

    def test_file_without_frontmatter_delimiter_produces_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "content": "No frontmatter here"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:no-frontmatter:ISSUE-001-test.md" in ids, (
            f"Expected no-frontmatter finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:no-frontmatter:ISSUE-001-test.md")
        assert f.severity == "error", (
            f"Expected severity 'error', got: {f.severity}"
        )
        assert f.fix_type == "report-only", (
            f"Expected fix_type 'report-only', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with broken YAML in frontmatter produces error
    # ------------------------------------------------------------------

    def test_file_with_broken_yaml_produces_parse_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "content": "---\n{{bad: yaml\n---\n# Body"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:parse-error:ISSUE-001-test.md" in ids, (
            f"Expected parse-error finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:parse-error:ISSUE-001-test.md")
        assert f.severity == "error", (
            f"Expected severity 'error', got: {f.severity}"
        )
        assert f.fix_type == "report-only", (
            f"Expected fix_type 'report-only', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: Two files with the same ID produce duplicate-id error
    # ------------------------------------------------------------------

    def test_two_files_with_same_id_produce_duplicate_id_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-first.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "First", "status": "active",
                }},
                {"name": "ISSUE-001-second.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Second", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:duplicate-id:ISSUE-001" in ids, (
            f"Expected duplicate-id finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:duplicate-id:ISSUE-001")
        assert f.severity == "error", (
            f"Expected severity 'error', got: {f.severity}"
        )
        assert f.fix_type == "prompted", (
            f"Expected fix_type 'prompted', got: {f.fix_type}"
        )
        assert len(f.file_paths) == 2, (
            f"Expected 2 file_paths, got: {f.file_paths}"
        )

    # ------------------------------------------------------------------
    # Scenario: Duplicate IDs across backlog and roadmap produce error
    # ------------------------------------------------------------------

    def test_duplicate_ids_across_backlog_and_roadmap_produce_error(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
            "roadmap_files": [
                {"name": "ISSUE-001-dup.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "milestone", "title": "Dup", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:duplicate-id:ISSUE-001" in ids, (
            f"Expected duplicate-id finding across backlog and roadmap, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Different IDs do not produce duplicate finding
    # ------------------------------------------------------------------

    def test_different_ids_do_not_produce_duplicate_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "First", "status": "active",
                }},
                {"name": "ISSUE-002-test.md", "frontmatter": {
                    "id": "ISSUE-002", "type": "story", "title": "Second", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        dup_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:duplicate-id")]
        assert dup_ids == [], (
            f"Different IDs should not produce duplicate-id finding, got: {dup_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with no id in frontmatter produces warning
    # ------------------------------------------------------------------

    def test_file_with_no_id_in_frontmatter_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-id:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-id finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:missing-field-id:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with no title in frontmatter produces warning
    # ------------------------------------------------------------------

    def test_file_with_no_title_in_frontmatter_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-title:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-title finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:missing-field-title:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with no type in frontmatter produces warning
    # ------------------------------------------------------------------

    def test_file_with_no_type_in_frontmatter_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-type:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-type finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:missing-field-type:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )
        assert f.fix_type == "prompted", (
            f"Expected fix_type 'prompted', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with no status in frontmatter produces warning
    # ------------------------------------------------------------------

    def test_file_with_no_status_in_frontmatter_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-status:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-status finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:missing-field-status:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )
        assert f.fix_type == "prompted", (
            f"Expected fix_type 'prompted', got: {f.fix_type}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with unrecognized status produces warning
    # ------------------------------------------------------------------

    def test_file_with_unrecognized_status_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "invented",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:unknown-status:ISSUE-001-test.md" in ids, (
            f"Expected unknown-status finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:unknown-status:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with valid status "active" produces no unknown-status finding
    # ------------------------------------------------------------------

    def test_valid_status_active_produces_no_unknown_status_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-status")]
        assert unknown_ids == [], (
            f"Valid status 'active' should produce no unknown-status finding, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with valid status "done" produces no unknown-status finding
    # ------------------------------------------------------------------

    def test_valid_status_done_produces_no_unknown_status_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "done",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-status")]
        assert unknown_ids == [], (
            f"Valid status 'done' should produce no unknown-status finding, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Status with parenthetical suffix is parsed correctly
    # ------------------------------------------------------------------

    def test_status_with_parenthetical_suffix_is_parsed_correctly(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test",
                    "status": "active(in review)",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-status")]
        assert unknown_ids == [], (
            f"Status 'active(in review)' should be parsed as 'active'; "
            f"no unknown-status finding expected, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Status with em-dash suffix is parsed correctly
    # ------------------------------------------------------------------

    def test_status_with_em_dash_suffix_is_parsed_correctly(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test",
                    "status": "done—shipped",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-status")]
        assert unknown_ids == [], (
            f"Status 'done—shipped' should be parsed as 'done'; "
            f"no unknown-status finding expected, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Uppercase status is normalized and accepted
    # ------------------------------------------------------------------

    def test_uppercase_status_is_normalized_and_accepted(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "Active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-status")]
        assert unknown_ids == [], (
            f"Status 'Active' should normalize to 'active'; "
            f"no unknown-status finding expected, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with unrecognized type produces warning
    # ------------------------------------------------------------------

    def test_file_with_unrecognized_type_produces_warning(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "invented-type", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:unknown-type:ISSUE-001-test.md" in ids, (
            f"Expected unknown-type finding, got: {ids}"
        )

        f = next(x for x in findings if x.id == "file-diagnostics:unknown-type:ISSUE-001-test.md")
        assert f.severity == "warning", (
            f"Expected severity 'warning', got: {f.severity}"
        )

    # ------------------------------------------------------------------
    # Scenario: File with valid type "story" produces no unknown-type finding
    # ------------------------------------------------------------------

    def test_valid_type_story_produces_no_unknown_type_finding(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-type")]
        assert unknown_ids == [], (
            f"Valid type 'story' should produce no unknown-type finding, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Mixed-case type is normalized and accepted
    # ------------------------------------------------------------------

    def test_mixed_case_type_is_normalized_and_accepted(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "Story", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        unknown_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:unknown-type")]
        assert unknown_ids == [], (
            f"Type 'Story' should normalize to 'story'; "
            f"no unknown-type finding expected, got: {unknown_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Type with parenthetical suffix is flagged as unknown
    # ------------------------------------------------------------------

    def test_type_with_parenthetical_suffix_is_flagged_as_unknown(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "id": "ISSUE-001", "type": "story(core)", "title": "Test", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:unknown-type:ISSUE-001-test.md" in ids, (
            f"Type 'story(core)' should not strip parenthetical; "
            f"expected unknown-type finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: INDEX.md is excluded from file diagnostics
    # ------------------------------------------------------------------

    def test_index_md_is_excluded_from_file_diagnostics(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "INDEX.md", "content": "No frontmatter"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        diag_ids = [f.id for f in findings if f.id.startswith("file-diagnostics")]
        assert diag_ids == [], (
            f"INDEX.md should be excluded from file diagnostics, got: {diag_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: MIGRATION-MAP.md is excluded from file diagnostics
    # ------------------------------------------------------------------

    def test_migration_map_md_is_excluded_from_file_diagnostics(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "MIGRATION-MAP.md", "content": "No frontmatter"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        diag_ids = [f.id for f in findings if f.id.startswith("file-diagnostics")]
        assert diag_ids == [], (
            f"MIGRATION-MAP.md should be excluded from file diagnostics, got: {diag_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Files ending in -INDEX.md are excluded
    # ------------------------------------------------------------------

    def test_files_ending_in_index_md_are_excluded(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "STORY-INDEX.md", "content": "No frontmatter"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        diag_ids = [f.id for f in findings if f.id.startswith("file-diagnostics")]
        assert diag_ids == [], (
            f"STORY-INDEX.md should be excluded from file diagnostics, got: {diag_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Files in archived/ directory are excluded
    # ------------------------------------------------------------------

    def test_files_in_archived_directory_are_excluded(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "archived/ISSUE-001-test.md", "content": "No frontmatter"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        diag_ids = [f.id for f in findings if f.id.startswith("file-diagnostics")]
        assert diag_ids == [], (
            f"Files in archived/ should be excluded from file diagnostics, got: {diag_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Empty frontmatter block produces missing-field warnings
    # ------------------------------------------------------------------

    def test_empty_frontmatter_block_produces_missing_field_warnings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "content": "---\n---\n# Body"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-id:ISSUE-001-test.md" in ids, (
            f"Empty frontmatter should produce missing-field-id finding, got: {ids}"
        )

        no_fm_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:no-frontmatter")]
        assert no_fm_ids == [], (
            f"Empty frontmatter should not produce no-frontmatter finding, got: {no_fm_ids}"
        )

        parse_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:parse-error")]
        assert parse_ids == [], (
            f"Empty frontmatter should not produce parse-error finding, got: {parse_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Roadmap file with missing fields produces warnings
    # ------------------------------------------------------------------

    def test_roadmap_file_with_missing_fields_produces_warnings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "roadmap_files": [
                {"name": "MS-001-launch.md", "frontmatter": {
                    "type": "milestone", "title": "Launch", "status": "active",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-id:MS-001-launch.md" in ids, (
            f"Roadmap file with missing id should produce missing-field-id finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Multiple field issues on same file produce multiple findings
    # ------------------------------------------------------------------

    def test_multiple_field_issues_on_same_file_produce_multiple_findings(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "frontmatter": {
                    "description": "just a description",
                }},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        assert len(findings) >= 4, (
            f"Expected at least 4 findings for file missing id, title, type, and status, "
            f"got: {[f.id for f in findings]}"
        )

        ids = [f.id for f in findings]
        assert "file-diagnostics:missing-field-id:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-id finding, got: {ids}"
        )
        assert "file-diagnostics:missing-field-title:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-title finding, got: {ids}"
        )
        assert "file-diagnostics:missing-field-type:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-type finding, got: {ids}"
        )
        assert "file-diagnostics:missing-field-status:ISSUE-001-test.md" in ids, (
            f"Expected missing-field-status finding, got: {ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: Parse error stops further field checks for that file
    # ------------------------------------------------------------------

    def test_parse_error_stops_further_field_checks_for_that_file(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "content": "---\n{{bad: yaml\n---\n# Body"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:parse-error:ISSUE-001-test.md" in ids, (
            f"Expected parse-error finding, got: {ids}"
        )

        missing_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:missing-field")]
        assert missing_ids == [], (
            f"Parse error should stop further field checks; "
            f"no missing-field findings expected, got: {missing_ids}"
        )

    # ------------------------------------------------------------------
    # Scenario: No-frontmatter error stops further field checks for that file
    # ------------------------------------------------------------------

    def test_no_frontmatter_error_stops_further_field_checks_for_that_file(
        self, tmp_path, fake_home
    ):
        project_dir = build_fixture(tmp_path, overrides={
            "backlog_files": [
                {"name": "ISSUE-001-test.md", "content": "No frontmatter here"},
            ],
        })
        state = build_project_state(project_dir)
        findings = check_file_diagnostics(state)

        ids = [f.id for f in findings]
        assert "file-diagnostics:no-frontmatter:ISSUE-001-test.md" in ids, (
            f"Expected no-frontmatter finding, got: {ids}"
        )

        missing_ids = [f.id for f in findings if f.id.startswith("file-diagnostics:missing-field")]
        assert missing_ids == [], (
            f"No-frontmatter error should stop further field checks; "
            f"no missing-field findings expected, got: {missing_ids}"
        )
