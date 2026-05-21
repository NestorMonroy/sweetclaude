"""
Tests for status/priority remapping — Feature: Status and priority remapping
Translates: tests/features/issue-090-migrate-taxonomy-status-priority.feature
"""
import os
import sys
import warnings
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from migrate.migrate_taxonomy import remap_status, remap_priority, infer_workflow_type


# ---------------------------------------------------------------------------
# Scenario Outline: Status remapping (lowercase input)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("backlog",     "new"),
    ("open",        "active"),
    ("in_progress", "active"),
    ("in progress", "active"),
    ("cancelled",   "abandoned"),
    ("canceled",    "abandoned"),
    ("complete",    "done"),
    ("achieved",    "done"),
    ("closed",      "done"),
    ("promoted",    "superseded"),
    ("proposed",    "new"),
])
def test_status_remapping_lowercase(legacy, expected):
    assert remap_status(legacy) == expected


# ---------------------------------------------------------------------------
# Scenario Outline: Status remapping is case-insensitive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("BACKLOG",     "new"),
    ("Open",        "active"),
    ("DONE",        "done"),
    ("In_Progress", "active"),
    ("PROMOTED",    "superseded"),
])
def test_status_remapping_case_insensitive(legacy, expected):
    assert remap_status(legacy) == expected


# ---------------------------------------------------------------------------
# Scenario Outline: Already-correct statuses pass through
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [
    "new",
    "ready",
    "active",
    "in-review",
    "blocked",
    "on-hold",
    "deferred",
    "done",
    "declined",
    "abandoned",
    "superseded",
])
def test_already_correct_status_passes_through(status):
    assert remap_status(status) == status


# ---------------------------------------------------------------------------
# Scenario: Unknown status passes through with warning
# ---------------------------------------------------------------------------

class TestUnknownStatusPassesThroughWithWarning:
    def test_unknown_status_returns_value_and_emits_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = remap_status("custom-status")

        assert result == "custom-status"
        assert any("status" in str(w.message).lower() for w in caught)


# ---------------------------------------------------------------------------
# Scenario Outline: Priority remapping (lowercase input)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("spike",   "P3"),
    ("next",    "P0"),
    ("now",     "P0"),
    ("sooner",  "P1"),
    ("soon",    "P2"),
    ("later",   "P3"),
    ("someday", "P4"),
    ("high",    "P1"),
    ("medium",  "P2"),
    ("low",     "P3"),
    ("p0",      "P0"),
    ("p1",      "P1"),
    ("p2",      "P2"),
    ("p3",      "P3"),
    ("p4",      "P4"),
])
def test_priority_remapping_lowercase(legacy, expected):
    assert remap_priority(legacy) == expected


# ---------------------------------------------------------------------------
# Scenario Outline: Priority remapping is case-insensitive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("SPIKE",  "P3"),
    ("High",   "P1"),
    ("P0",     "P0"),
    ("SOONER", "P1"),
])
def test_priority_remapping_case_insensitive(legacy, expected):
    assert remap_priority(legacy) == expected


# ---------------------------------------------------------------------------
# Scenario: Unknown priority passes through with warning
# ---------------------------------------------------------------------------

class TestUnknownPriorityPassesThroughWithWarning:
    def test_unknown_priority_returns_value_and_emits_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = remap_priority("critical")

        assert result == "critical"
        assert any("priority" in str(w.message).lower() for w in caught)


# ---------------------------------------------------------------------------
# Scenario: Missing priority field produces None
# ---------------------------------------------------------------------------

class TestMissingPriorityProducesNone:
    def test_none_priority_produces_none(self):
        assert remap_priority(None) is None


# ---------------------------------------------------------------------------
# Scenario: Empty priority string produces None
# ---------------------------------------------------------------------------

class TestEmptyPriorityProducesNone:
    def test_empty_string_priority_produces_none(self):
        assert remap_priority("") is None


# ---------------------------------------------------------------------------
# Scenario Outline: Workflow type inference from type field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("type_field,expected_workflow", [
    ("story",    "enhancement"),
    ("bug",      "bug-fix"),
    ("debt",     "tech-debt"),
    ("chore",    "tech-debt"),
    ("spike",    "spike"),
    ("refactor", "tech-debt"),
])
def test_workflow_type_from_type_field(type_field, expected_workflow):
    result = infer_workflow_type(type_field=type_field)
    assert result == expected_workflow


# ---------------------------------------------------------------------------
# Scenario: Explicit workflow_type takes precedence over type field
# ---------------------------------------------------------------------------

class TestExplicitWorkflowTypeTakesPrecedence:
    def test_explicit_workflow_type_overrides_type_field(self):
        result = infer_workflow_type(
            workflow_type="net-new-feature",
            type_field="story",
        )
        assert result == "net-new-feature"


# ---------------------------------------------------------------------------
# Scenario: Type field takes precedence over title heuristic
# ---------------------------------------------------------------------------

class TestTypeFieldTakesPrecedenceOverTitleHeuristic:
    def test_type_story_with_fix_title_returns_enhancement(self):
        result = infer_workflow_type(
            type_field="story",
            title="Fix the bug in login",
        )
        assert result == "enhancement"


# ---------------------------------------------------------------------------
# Scenario Outline: Workflow type heuristic from title
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected_workflow", [
    ("Spike: evaluate voice SDK",   "spike"),
    ("Research caching strategies",  "spike"),
    ("Evaluate new auth provider",   "spike"),
    ("Fix broken login flow",        "bug-fix"),
    ("Bug in payment processing",    "bug-fix"),
    ("Add user invitation feature",  "enhancement"),
])
def test_workflow_type_heuristic_from_title(title, expected_workflow):
    result = infer_workflow_type(title=title)
    assert result == expected_workflow


# ---------------------------------------------------------------------------
# Scenario: Default workflow type when no signals
# ---------------------------------------------------------------------------

class TestDefaultWorkflowTypeWhenNoSignals:
    def test_no_type_no_workflow_type_no_title_signals_defaults_to_enhancement(self):
        result = infer_workflow_type(title="Some task")
        assert result == "enhancement"
