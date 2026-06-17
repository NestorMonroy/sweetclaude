"""Regression lock for the 4.2.11-beta state-loader fix.

`session-state.yaml` (and `sweetclaude.yaml`) are per-session *derived*
snapshots, not tracked files. A skill bang preamble (`` !`...` ``) must never
bare-`cat` them: when the snapshot is absent the bare cat exits non-zero and
aborts skill load — the 4.2.10-beta brick (`cat: ...session-state.yaml: No such
file or directory`). All state loading in a bang preamble must route through
`hooks/read-state.sh`, which emits a `STATE_NOT_FOUND` sentinel and exits 0 when
the file is absent.

These tests fail if anyone reintroduces the bare-cat pattern.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
READ_STATE = REPO / "hooks" / "read-state.sh"


def _offending_bang_state_lines(text):
    """Bang-preamble lines that read a state file without read-state.sh."""
    offenders = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("!`") and ".sweetclaude/state/" in s and "read-state.sh" not in s:
            offenders.append(s)
    return offenders


def test_detector_flags_bare_cat_and_passes_wrapper():
    """The detector itself: RED on a bare-cat, GREEN on wrapper and body forms."""
    bare_cat = "!`cat .sweetclaude/state/session-state.yaml`"
    wrapper = "!`bash ${CLAUDE_SKILL_DIR}/../../hooks/read-state.sh session-state`"
    body_block = "cat .sweetclaude/state/session-state.yaml 2>/dev/null || echo X"

    assert _offending_bang_state_lines(bare_cat) == [bare_cat]
    assert _offending_bang_state_lines(wrapper) == []
    assert _offending_bang_state_lines(body_block) == []


def test_no_skill_bang_preamble_reads_state_without_read_state():
    offenders = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        for line in _offending_bang_state_lines(skill_md.read_text()):
            offenders.append(f"{skill_md.relative_to(REPO)}: {line}")
    assert not offenders, (
        "Bang preambles must load state via hooks/read-state.sh, not a bare "
        "cat (a missing derived snapshot would abort skill load):\n"
        + "\n".join(offenders)
    )


def test_read_state_wrapper_exists_and_is_executable():
    assert READ_STATE.is_file(), "hooks/read-state.sh must exist"
    assert READ_STATE.stat().st_mode & 0o111, "hooks/read-state.sh must be executable"


def test_read_state_missing_file_emits_sentinel_and_exits_zero(tmp_path):
    result = subprocess.run(
        ["bash", str(READ_STATE), "session-state"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, "wrapper must exit 0 even when the file is absent"
    assert result.stdout.strip() == "STATE_NOT_FOUND"


def test_read_state_present_file_emits_contents_and_exits_zero(tmp_path):
    state_dir = tmp_path / ".sweetclaude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "session-state.yaml").write_text("schema_version: 2\nactive: foo\n")
    result = subprocess.run(
        ["bash", str(READ_STATE), "session-state"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "schema_version: 2" in result.stdout
    assert "active: foo" in result.stdout
