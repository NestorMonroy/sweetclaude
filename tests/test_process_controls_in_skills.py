from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_shared_process_controls_contract_exists():
    text = _read("skills/process-controls.md")

    for phrase in (
        "Required Ledger",
        "Default Limits",
        "Hard Stops",
        "Resume Requirements",
        "one three-reviewer caucus per budget window",
        "second blocking caucus failure",
        "no background implementer or reviewer dispatch while a process stop is active",
    ):
        assert phrase in text


def test_code_tdd_and_feature_require_process_control_ledger():
    for path in ("skills/code-tdd/SKILL.md", "skills/code-feature/SKILL.md", "skills/code-issue/SKILL.md"):
        text = _read(path)
        assert "skills/process-controls.md" in text
        assert ".sweetclaude/state/process-control-ledger.yaml" in text
        assert "stop disposition" in text


def test_john_wick_autonomous_caucus_steps_require_process_controls():
    for path in (
        "skills/john-wick/SKILL.md",
        "skills/john-wick/phase-1-define.md",
        "skills/john-wick/phase-2-plan.md",
        "skills/john-wick/phase-3-design.md",
        "skills/john-wick/phase-4-implement-prep.md",
        "skills/john-wick/phase-5-implement.md",
        "skills/john-wick/phase-6-verify.md",
    ):
        text = _read(path)
        assert "process-controls.md" in text
        assert "process_control" in text


def test_john_wick_state_schema_contains_process_control_state():
    text = _read("skills/john-wick/state-schema.md")

    for phrase in (
        "process_control:",
        "budget_approved",
        "max_caucus_rounds_per_step",
        "max_reviewer_agents_per_budget",
        "max_blocking_caucus_failures_per_step",
        "active_stop_disposition",
        "human_resume_approved",
    ):
        assert phrase in text
