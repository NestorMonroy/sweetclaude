#!/bin/bash
set -e
TEST_TMPDIR=$(mktemp -d)
trap "rm -rf $TEST_TMPDIR" EXIT
mkdir -p "$TEST_TMPDIR/.sweetclaude/state"

# Write sweetclaude.yaml with stale timestamps (25 hours ago)
STALE=$(python3 -c "
from datetime import datetime, timezone, timedelta
print((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec='seconds'))
")

python3 -c "
import yaml, sys
d = {
  'schema_version': 1,
  'framework': {
    'installed_version': '2.40.0',
    'setup_complete': True,
    'hook_last_ran': None,
    'consistency': {'last_checked': '$STALE', 'status': 'ok', 'drift': [], 'check_error': None},
    'update': {'available': None, 'last_checked': '$STALE', 'declined': False, 'check_error': None},
  }
}
open('$TEST_TMPDIR/.sweetclaude/state/sweetclaude.yaml','w').write(yaml.dump(d))
"

PROJECT_DIR="$TEST_TMPDIR" bash hooks/sweetclaude-health-check.sh

# Verify timestamps were updated
python3 -c "
import yaml
from datetime import datetime, timezone
d = yaml.safe_load(open('$TEST_TMPDIR/.sweetclaude/state/sweetclaude.yaml'))
stale = '$STALE'
cons_ts = str(d['framework']['consistency']['last_checked'] or '')
upd_ts  = str(d['framework']['update']['last_checked'] or '')
hook_ts = d['framework']['hook_last_ran']
assert cons_ts != stale, f'consistency.last_checked not updated: {cons_ts}'
assert upd_ts  != stale, f'update.last_checked not updated: {upd_ts}'
assert hook_ts is not None, 'hook_last_ran not written'
print('PASS')
"

# Test 2: drift cleared in ok-path
python3 -c "
import yaml
d = yaml.safe_load(open('$TEST_TMPDIR/.sweetclaude/state/sweetclaude.yaml'))
d['framework']['consistency']['status'] = 'drift_detected'
d['framework']['consistency']['drift'] = ['fake_drift']
d['framework']['consistency']['last_checked'] = '$STALE'
open('$TEST_TMPDIR/.sweetclaude/state/sweetclaude.yaml','w').write(yaml.dump(d))
"

PROJECT_DIR="$TEST_TMPDIR" bash hooks/sweetclaude-health-check.sh

python3 -c "
import yaml
d = yaml.safe_load(open('$TEST_TMPDIR/.sweetclaude/state/sweetclaude.yaml'))
assert d['framework']['consistency']['status'] == 'ok', f\"drift not cleared: {d['framework']['consistency']['status']}\"
assert d['framework']['consistency']['drift'] == [], f\"drift list not empty: {d['framework']['consistency']['drift']}\"
print('DRIFT_CLEAR_PASS')
"


# Test 3: stable update discovery ignores beta local clone
TEST_HOME=$(mktemp -d)
TEST_PROJECT=$(mktemp -d)
TEST_REPO=$(mktemp -d)
trap "rm -rf $TEST_TMPDIR $TEST_HOME $TEST_PROJECT $TEST_REPO" EXIT
mkdir -p "$TEST_HOME/.claude/plugins" "$TEST_HOME/.claude/plugins/cache/sweetclaude-stable/sweetclaude/3.68.6/.claude-plugin" "$TEST_PROJECT/.sweetclaude/state"
cat > "$TEST_HOME/.claude/plugins/installed_plugins.json" << JSON
{"plugins":{"sweetclaude@sweetclaude-stable":[{"scope":"user","installPath":"$TEST_HOME/.claude/plugins/cache/sweetclaude-stable/sweetclaude/3.68.6","version":"3.68.6","lastUpdated":"2026-05-25T00:00:00Z"}]}}
JSON
cat > "$TEST_HOME/.claude/plugins/cache/sweetclaude-stable/sweetclaude/3.68.6/.claude-plugin/plugin.json" << JSON
{"repository":"not-a-real-remote"}
JSON
cat > "$TEST_HOME/.claude/sweetclaude-install.json" << JSON
{"repo_path":"$TEST_REPO"}
JSON
(
  cd "$TEST_REPO"
  git init -q
  git checkout -q -b beta-4.x
  printf '{"name":"sweetclaude","version":"4.1.12-beta"}
' > package.json
)
python3 -c "
import yaml
from datetime import datetime, timezone, timedelta
stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec='seconds')
d = {
  'schema_version': 1,
  'framework': {
    'installed_version': '3.68.6',
    'setup_complete': True,
    'hook_last_ran': None,
    'consistency': {'last_checked': stale, 'status': 'ok', 'drift': [], 'check_error': None},
    'update': {'available': None, 'last_checked': stale, 'declined': False, 'check_error': None},
  }
}
open('$TEST_PROJECT/.sweetclaude/state/sweetclaude.yaml','w').write(yaml.dump(d))
"
HOME="$TEST_HOME" PROJECT_DIR="$TEST_PROJECT" bash hooks/sweetclaude-health-check.sh
python3 -c "
import yaml
d = yaml.safe_load(open('$TEST_PROJECT/.sweetclaude/state/sweetclaude.yaml'))
assert d['framework']['update']['available'] is None, d['framework']['update']['available']
print('STABLE_IGNORES_BETA_LOCAL_CLONE_PASS')
"


# Test 4: stable plugin root wins when stable and beta metadata coexist
TEST_HOME2=$(mktemp -d)
TEST_PROJECT2=$(mktemp -d)
TEST_REPO2=$(mktemp -d)
trap "rm -rf $TEST_TMPDIR $TEST_HOME $TEST_PROJECT $TEST_REPO $TEST_HOME2 $TEST_PROJECT2 $TEST_REPO2" EXIT
STABLE_PATH="$TEST_HOME2/.claude/plugins/cache/sweetclaude-stable/sweetclaude/3.68.6"
BETA_PATH="$TEST_HOME2/.claude/plugins/cache/sweetclaude-beta/sweetclaude/4.1.12-beta"
mkdir -p "$STABLE_PATH/.claude-plugin" "$BETA_PATH/.claude-plugin" "$TEST_HOME2/.claude/plugins" "$TEST_PROJECT2/.sweetclaude/state"
cat > "$TEST_HOME2/.claude/plugins/installed_plugins.json" << JSON
{"plugins":{"sweetclaude@sweetclaude-beta":[{"scope":"user","installPath":"$BETA_PATH","version":"4.1.12-beta","lastUpdated":"2026-05-25T01:00:00Z"}],"sweetclaude@sweetclaude-stable":[{"scope":"user","installPath":"$STABLE_PATH","version":"3.68.6","lastUpdated":"2026-05-25T00:00:00Z"}]}}
JSON
cat > "$STABLE_PATH/.claude-plugin/plugin.json" << JSON
{"repository":"not-a-real-remote"}
JSON
cat > "$BETA_PATH/.claude-plugin/plugin.json" << JSON
{"repository":"not-a-real-remote"}
JSON
cat > "$TEST_HOME2/.claude/sweetclaude-install.json" << JSON
{"repo_path":"$TEST_REPO2"}
JSON
(
  cd "$TEST_REPO2"
  git init -q
  git checkout -q -b beta-4.x
  printf '{"name":"sweetclaude","version":"4.1.12-beta"}\n' > package.json
)
python3 -c "
import yaml
from datetime import datetime, timezone, timedelta
stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec='seconds')
d = {
  'schema_version': 1,
  'framework': {
    'installed_version': '3.68.6',
    'setup_complete': True,
    'hook_last_ran': None,
    'consistency': {'last_checked': stale, 'status': 'ok', 'drift': [], 'check_error': None},
    'update': {'available': None, 'last_checked': stale, 'declined': False, 'check_error': None},
  }
}
open('$TEST_PROJECT2/.sweetclaude/state/sweetclaude.yaml','w').write(yaml.dump(d))
"
HOME="$TEST_HOME2" CLAUDE_PLUGIN_ROOT="$STABLE_PATH" PROJECT_DIR="$TEST_PROJECT2" bash hooks/sweetclaude-health-check.sh
python3 -c "
import yaml
d = yaml.safe_load(open('$TEST_PROJECT2/.sweetclaude/state/sweetclaude.yaml'))
assert d['framework']['installed_version'] == '3.68.6', d['framework']['installed_version']
assert d['framework']['update']['available'] is None, d['framework']['update']['available']
print('STABLE_PLUGIN_ROOT_IGNORES_COEXISTING_BETA_PASS')
"
