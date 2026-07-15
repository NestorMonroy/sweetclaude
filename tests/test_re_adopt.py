"""re_adopt: the universal no-data-loss terminal fallback doctor's totality
classifier promises. Archives SweetClaude state aside (reversible) so a project
can be re-onboarded, without touching source or relocated artifacts.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from recovery import re_adopt


def _project(tmp_path):
    p = tmp_path / "proj"
    (p / ".sweetclaude" / "state").mkdir(parents=True)
    (p / ".sweetclaude" / "state" / "phase.yaml").write_text("schema_version: 2\n")
    (p / ".sweetclaude" / "artifact-privacy.yaml").write_text(
        "categories:\n  product:\n    base_path: docs/product\n")
    (p / "docs" / "product" / "backlog").mkdir(parents=True)
    (p / "docs" / "product" / "backlog" / "ISSUE-001.md").write_text("---\nid: ISSUE-001\n---\n")
    (p / "src").mkdir()
    (p / "src" / "app.py").write_text("print('hi')\n")
    return p


def test_plan_is_read_only_and_reports_what_will_move(tmp_path):
    p = _project(tmp_path)
    plan = re_adopt.plan_re_adopt(p)
    assert plan["ok"]
    assert plan["archives"] == [".sweetclaude"]
    assert plan["no_data_loss"] is True
    assert plan["reversible"] is True
    # planning touches nothing
    assert (p / ".sweetclaude").is_dir()
    assert not list(p.glob(".sweetclaude.legacy*"))


def test_execute_archives_state_preserving_every_file(tmp_path):
    p = _project(tmp_path)
    before = {str(f.relative_to(p / ".sweetclaude"))
              for f in (p / ".sweetclaude").rglob("*") if f.is_file()}
    result = re_adopt.execute_re_adopt(p)
    assert result["ok"]
    legacy = Path(result["legacy_path"])
    assert legacy.exists()
    # .sweetclaude cleared from root (fresh slate for re-onboarding)
    assert not (p / ".sweetclaude").exists()
    # every original file preserved in the archive — no data loss
    after = {str(f.relative_to(legacy / ".sweetclaude"))
             for f in (legacy / ".sweetclaude").rglob("*") if f.is_file()}
    assert after == before


def test_execute_leaves_source_and_relocated_artifacts_untouched(tmp_path):
    p = _project(tmp_path)
    re_adopt.execute_re_adopt(p)
    assert (p / "src" / "app.py").read_text() == "print('hi')\n"
    assert (p / "docs" / "product" / "backlog" / "ISSUE-001.md").exists()


def test_reverse_restores_state(tmp_path):
    p = _project(tmp_path)
    result = re_adopt.execute_re_adopt(p)
    re_adopt.reverse_re_adopt(p, result["legacy_path"])
    assert (p / ".sweetclaude" / "state" / "phase.yaml").exists()
    assert not (p / ".sweetclaude").is_symlink()


def test_execute_refuses_if_no_sweetclaude(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    result = re_adopt.execute_re_adopt(p)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# CLI entrypoint — the audit gap. Doctor (and the SKILL) must be able to drive
# the re-onboard archive through a script invocation, never a skill-side mv. The
# CLI reuses the existing functions; it does NOT reimplement the archiving.
# NO MOCKS — real filesystem, real subprocess.
# ---------------------------------------------------------------------------


class TestReAdoptCLI:

    def test_cli_plan_is_read_only_and_reports_init_next_step(self, tmp_path):
        p = _project(tmp_path)
        rc = re_adopt.main(["plan", "--project-dir", str(p)])
        assert rc == 0
        # dry-run touches nothing
        assert (p / ".sweetclaude").is_dir()
        assert not list(p.glob(".sweetclaude.legacy*"))

    def test_cli_execute_archives_state_to_legacy_and_reports_init_next_step(
        self, tmp_path, capsys
    ):
        p = _project(tmp_path)
        before = {str(f.relative_to(p / ".sweetclaude"))
                  for f in (p / ".sweetclaude").rglob("*") if f.is_file()}

        rc = re_adopt.main(["execute", "--project-dir", str(p)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)

        assert out["ok"] is True
        # archived to .sweetclaude.legacy/<ts>/
        legacy = Path(out["legacy_path"])
        assert legacy.exists()
        assert legacy.parent.name == ".sweetclaude.legacy"
        # root cleared for a fresh re-onboard
        assert not (p / ".sweetclaude").exists()
        # no data loss — every file preserved
        after = {str(f.relative_to(legacy / ".sweetclaude"))
                 for f in (legacy / ".sweetclaude").rglob("*") if f.is_file()}
        assert after == before
        # the JSON reports the init re-onboard as the next step (NOT a ghost
        # 'adopt' skill)
        assert "next_step" in out
        assert "init" in out["next_step"].lower()
        assert "adopt" not in out["next_step"].lower()

    def test_cli_execute_leaves_project_code_untouched(self, tmp_path, capsys):
        p = _project(tmp_path)
        re_adopt.main(["execute", "--project-dir", str(p)])
        capsys.readouterr()
        assert (p / "src" / "app.py").read_text() == "print('hi')\n"
        assert (p / "docs" / "product" / "backlog" / "ISSUE-001.md").exists()

    def test_cli_execute_is_reversible(self, tmp_path, capsys):
        p = _project(tmp_path)
        re_adopt.main(["execute", "--project-dir", str(p)])
        out = json.loads(capsys.readouterr().out)
        # the archive can be undone — state restored to the project root
        rev = re_adopt.reverse_re_adopt(p, out["legacy_path"])
        assert rev["ok"] is True
        assert (p / ".sweetclaude" / "state" / "phase.yaml").exists()

    def test_cli_execute_refuses_if_no_sweetclaude(self, tmp_path, capsys):
        p = tmp_path / "empty"
        p.mkdir()
        rc = re_adopt.main(["execute", "--project-dir", str(p)])
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        # a failed re-adopt is a non-zero exit so callers can detect it
        assert rc != 0

    def test_cli_runs_as_real_subprocess_entrypoint(self, tmp_path):
        # End-to-end: doctor invokes this exactly as a process, not an import.
        p = _project(tmp_path)
        script = SCRIPTS_DIR / "recovery" / "re_adopt.py"
        proc = subprocess.run(
            [sys.executable, str(script), "execute", "--project-dir", str(p)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert Path(out["legacy_path"]).exists()
        assert not (p / ".sweetclaude").exists()
        assert "init" in out["next_step"].lower()
