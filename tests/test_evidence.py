import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from evidence import validate_receipt, write_receipt


EVIDENCE = _SCRIPTS_DIR / "evidence.py"


def test_write_receipt_creates_valid_completion_receipt(tmp_path):
    receipt = write_receipt(
        tmp_path,
        subject_id="ISSUE-123",
        receipt_type="completion",
        check_name="tests",
        status="pass",
        command="pytest -q",
        summary="all focused tests passed",
    )

    parsed = validate_receipt(
        receipt,
        subject_id="ISSUE-123",
        receipt_type="completion",
    )

    assert parsed["subject_id"] == "ISSUE-123"
    assert parsed["checks"][0]["status"] == "pass"


def test_validate_receipt_rejects_failed_check(tmp_path):
    receipt = tmp_path / "failed.json"
    receipt.write_text(json.dumps({
        "schema_version": 1,
        "receipt_type": "completion",
        "subject_id": "ISSUE-123",
        "status": "pass",
        "checks": [{
            "name": "tests",
            "status": "fail",
            "command": "pytest -q",
        }],
    }))

    with pytest.raises(ValueError, match="must pass"):
        validate_receipt(receipt, subject_id="ISSUE-123")


def test_validate_receipt_rejects_subject_mismatch(tmp_path):
    receipt = write_receipt(
        tmp_path,
        subject_id="ISSUE-999",
        receipt_type="completion",
        check_name="tests",
        status="pass",
        command="pytest -q",
    )

    with pytest.raises(ValueError, match="subject mismatch"):
        validate_receipt(receipt, subject_id="ISSUE-123")


def test_evidence_cli_write_and_validate(tmp_path):
    write_result = subprocess.run(
        [
            sys.executable,
            str(EVIDENCE),
            "write",
            "--project-dir",
            str(tmp_path),
            "--subject-id",
            "ISSUE-123",
            "--receipt-type",
            "completion",
            "--check",
            "tests",
            "--command",
            "pytest -q",
            "--summary",
            "passed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert write_result.returncode == 0, write_result.stdout + write_result.stderr
    receipt = json.loads(write_result.stdout)["receipt"]

    validate_result = subprocess.run(
        [
            sys.executable,
            str(EVIDENCE),
            "validate",
            "--receipt",
            receipt,
            "--subject-id",
            "ISSUE-123",
            "--receipt-type",
            "completion",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert validate_result.returncode == 0
    assert json.loads(validate_result.stdout)["ok"] is True
