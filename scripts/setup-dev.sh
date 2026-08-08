#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Install everything needed to run the SweetClaude test suite locally.
#
# Playwright pins an exact browser revision per package release, so the package
# and the browser must be installed together. Running pip alone leaves
# tests/test_dashboard_ui.py failing with "Executable doesn't exist".
#
# Usage: bash scripts/setup-dev.sh

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

PYTHON=${PYTHON:-python3}

echo "Installing Python test dependencies..."
"$PYTHON" -m pip install --quiet -r requirements-dev.txt

echo "Installing the matching Playwright browser build..."
"$PYTHON" -m playwright install chromium

EXPECTED=$("$PYTHON" - <<'PY'
import json, os, playwright
path = os.path.join(os.path.dirname(playwright.__file__), 'driver', 'package', 'browsers.json')
for browser in json.load(open(path))['browsers']:
    if browser['name'] == 'chromium':
        print(browser['revision'])
        break
PY
)

echo
echo "Ready. Playwright expects chromium build ${EXPECTED}."
echo "Run the suite with: ${PYTHON} -m pytest tests/ -q"
