"""Coverage for the legacy MS/BL artifact migration (ISSUE-255).

scripts/migrate-project-artifacts.py rewrites a project's milestone and
backlog trees into the v1.2 data model. 250 statements, no tests. It has a
--dry-run flag, and whether that flag is honoured is the difference between a
preview and an irreversible rewrite of someone's backlog.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate-project-artifacts.py"


def _load():
    spec = importlib.util.spec_from_file_location("migrate_project_artifacts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


# --- parsing helpers -----------------------------------------------------

def test_extract_meta_reads_a_bold_metadata_line() -> None:
    content = "# Title\n\n**Priority:** P1 - High\n**Status:** DONE\n"
    assert mod.extract_meta(content, "Priority") == "P1 - High"
    assert mod.extract_meta(content, "Status") == "DONE"


def test_extract_meta_returns_empty_for_a_missing_key() -> None:
    assert mod.extract_meta("# Title\n", "Nothing") == ""


def test_extract_section_reads_up_to_the_next_heading() -> None:
    content = "## First\nbody one\n\n## Second\nbody two\n"
    assert mod.extract_section(content, "First") == "body one"
    assert mod.extract_section(content, "Second") == "body two"


def test_extract_section_reads_the_last_section_to_end_of_file() -> None:
    assert mod.extract_section("## Only\nthe body\n", "Only") == "the body"


def test_extract_section_returns_empty_when_absent() -> None:
    assert mod.extract_section("## Other\nx\n", "Missing") == ""


@pytest.mark.parametrize("text,expected", [
    ("Simple Title", "simple-title"),
    ("Title With  Multiple   Spaces", "title-with-multiple-spaces"),
    ("Punctuation!@#$ Here", "punctuation-here"),
    ("---leading and trailing---", "leading-and-trailing"),
])
def test_slugify(text: str, expected: str) -> None:
    assert mod.slugify(text) == expected


def test_slugify_truncates_long_titles() -> None:
    assert len(mod.slugify("word " * 100)) <= 60


def test_slugify_can_leave_a_trailing_separator_when_truncating() -> None:
    """Behavior recorded, not endorsed.

    slugify() strips separators and only then truncates
    (`s.strip("-")[:60]`), so a 60-character cut can land immediately after a
    dash and yield a slug ending in one — producing filenames like
    `I-001-some-long-title-.md`. Only titles longer than 60 characters are
    affected. Locked here so a fix updates this assertion deliberately.
    """
    assert mod.slugify("word " * 100).endswith("-")


@pytest.mark.parametrize("raw,expected", [
    ("DONE", "done"), ("DONE - shipped", "done"),
    ("TODO", "backlog"), ("", "backlog"), ("in progress", "backlog"),
])
def test_map_status_bl(raw: str, expected: str) -> None:
    assert mod.map_status_bl(raw) == expected


def test_map_priority_falls_back_to_soon_for_unknown_input() -> None:
    assert mod.map_priority("something unrecognised") == "soon"


@pytest.mark.parametrize("title,summary,expected", [
    ("Fix the crash on login", "", "bug"),
    ("Refactor the parser", "", "chore"),
    ("Add a new dashboard", "", "story"),
    ("Remove dead code", "", "chore"),
    ("Regression in export", "", "bug"),
])
def test_infer_issue_type_from_title(title: str, summary: str, expected: str) -> None:
    assert mod.infer_issue_type("BL-001.md", title, "P2", summary) == expected


def test_infer_issue_type_detects_a_spike_from_priority() -> None:
    assert mod.infer_issue_type("BL-001.md", "Investigate options", "SPIKE", "") == "spike"


def test_infer_issue_type_detects_a_spike_from_title() -> None:
    assert mod.infer_issue_type("BL-001.md", "Spike on caching", "P2", "") == "spike"


def test_infer_issue_type_reads_the_summary_too() -> None:
    assert mod.infer_issue_type("BL-001.md", "Investigate", "P2",
                                "the export is broken") == "bug"


def test_parse_bl_frontmatter_reads_key_values() -> None:
    parsed = mod.parse_bl_frontmatter("---\nid: BL-001\nstatus: TODO\n---\nbody\n")
    assert isinstance(parsed, dict)


def test_extract_bl_title_and_body_reads_the_heading_format() -> None:
    """The legacy shape is `# BL-NNN: Title`, not a bare heading."""
    title, body = mod.extract_bl_title_and_body(
        "# BL-001: Fix the crash\n\nThe body text\n")
    assert title == "Fix the crash"
    assert "body text" in body


def test_extract_bl_title_and_body_prefers_yaml_frontmatter() -> None:
    title, body = mod.extract_bl_title_and_body(
        '---\nid: BL-001\ntitle: From Frontmatter\n---\n\nThe body text\n')
    assert title == "From Frontmatter"
    assert "body text" in body


def test_extract_bl_title_and_body_returns_empty_title_when_unrecognised() -> None:
    title, body = mod.extract_bl_title_and_body("# Just A Heading\n\nbody\n")
    assert title == ""
    assert body.startswith("# Just A Heading")


# --- write_file honours dry-run -----------------------------------------

def test_write_file_writes_when_not_dry_run(tmp_path: Path, capsys) -> None:
    target = tmp_path / "nested" / "out.md"
    mod.write_file(target, "content\n", dry_run=False)

    assert target.read_text(encoding="utf-8") == "content\n"
    assert "Written" in capsys.readouterr().out


def test_write_file_writes_nothing_in_dry_run(tmp_path: Path, capsys) -> None:
    """The whole safety story of this script rests on this branch."""
    target = tmp_path / "nested" / "out.md"
    mod.write_file(target, "content\n", dry_run=True)

    assert not target.exists(), "--dry-run wrote a file"
    assert not target.parent.exists(), "--dry-run created a directory"
    assert "DRY-RUN" in capsys.readouterr().out


# --- CLI preconditions ---------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


def test_cli_refuses_when_milestones_directory_is_missing(tmp_path: Path) -> None:
    (tmp_path / ".sweetclaude" / "product" / "backlog").mkdir(parents=True)

    r = _run("--repo-root", str(tmp_path), "--dry-run")

    assert r.returncode == 1
    assert "milestones directory not found" in r.stderr


def test_cli_refuses_when_backlog_directory_is_missing(tmp_path: Path) -> None:
    (tmp_path / ".sweetclaude" / "product" / "milestones").mkdir(parents=True)

    r = _run("--repo-root", str(tmp_path), "--dry-run")

    assert r.returncode == 1
    assert "backlog directory not found" in r.stderr


@pytest.fixture
def legacy_project(tmp_path: Path) -> Path:
    product = tmp_path / ".sweetclaude" / "product"
    milestones = product / "milestones"
    backlog = product / "backlog"
    milestones.mkdir(parents=True)
    backlog.mkdir(parents=True)

    (milestones / "MS-001-public-launch.md").write_text(
        "# MS-001: Public Launch\n\n"
        "**Status:** DONE\n**Target:** 2026-01-01\n\n"
        "## Summary\nShip it.\n\n## Success Criteria\n- criterion one\n",
        encoding="utf-8")
    (backlog / "BL-001-fix-the-crash.md").write_text(
        "# BL-001: Fix the crash on export\n\n"
        "**Priority:** P1 - High\n**Status:** TODO\n\n"
        "## Summary\nExport crashes on empty input.\n",
        encoding="utf-8")
    (backlog / "BL-002-refactor-parser.md").write_text(
        "# BL-002: Refactor the parser\n\n"
        "**Priority:** P3 - Low\n**Status:** DONE\n\n"
        "## Summary\nCleanup only.\n",
        encoding="utf-8")
    return tmp_path


def test_dry_run_leaves_the_project_untouched(legacy_project: Path) -> None:
    before = {p.relative_to(legacy_project).as_posix(): p.read_bytes()
              for p in legacy_project.rglob("*") if p.is_file()}

    r = _run("--repo-root", str(legacy_project), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout

    after = {p.relative_to(legacy_project).as_posix(): p.read_bytes()
             for p in legacy_project.rglob("*") if p.is_file()}
    assert after == before, "--dry-run modified the project"


def test_live_run_produces_the_v12_tree(legacy_project: Path) -> None:
    """The migration itself works; the run then dies writing its report.

    ISSUE-270: write_report() targets repo_root/scripts/migration-report.md
    with a bare write_text() and no mkdir, so any project lacking a top-level
    scripts/ directory ends in FileNotFoundError — after every phase has
    already rewritten the backlog. Asserted as-is so the fix flips it.
    """
    r = _run("--repo-root", str(legacy_project))

    product = legacy_project / ".sweetclaude" / "product"
    assert (product / "issues").is_dir(), "phase 3 did not run"
    assert list((product / "issues").glob("I-*.md")), "no issues were written"
    assert "LIVE" in r.stdout

    assert r.returncode == 1, "ISSUE-270 appears fixed — update this test"
    assert "migration-report.md" in r.stderr


def test_live_run_succeeds_when_a_scripts_directory_exists(legacy_project: Path) -> None:
    """Confirms ISSUE-270 is purely the missing directory: give the project a
    scripts/ dir and the same run completes cleanly."""
    (legacy_project / "scripts").mkdir()

    r = _run("--repo-root", str(legacy_project))

    assert r.returncode == 0, r.stderr + r.stdout
    assert (legacy_project / "scripts" / "migration-report.md").is_file()


def test_live_run_is_idempotent(legacy_project: Path) -> None:
    (legacy_project / "scripts").mkdir()  # avoid the ISSUE-270 crash
    _run("--repo-root", str(legacy_project))
    first = sorted(p.relative_to(legacy_project).as_posix()
                   for p in legacy_project.rglob("*") if p.is_file())

    _run("--repo-root", str(legacy_project))
    second = sorted(p.relative_to(legacy_project).as_posix()
                    for p in legacy_project.rglob("*") if p.is_file())

    assert second == first, "a second run produced a different tree"
