---
spdx-license: AGPL-3.0-or-later
user-invocable: true
description: "Update SweetClaude to the latest version from GitHub (or a local repo)."
---



# Update SweetClaude

Fetch the latest SweetClaude and sync it to all installed locations.

**This skill can be run from any project directory.**

---

## Step -1: Pre-flight

Clear any previous update decline (running `/sweetclaude:update` is explicit re-engagement), and emit the runner path for later steps.

```bash
eval "$(bash "${CLAUDE_PLUGIN_ROOT}/scripts/preflight.sh" --from-update 2>/dev/null)"
```

`DECLINE_CLEARED=true` if the project's `framework.update.declined` was cleared. `RUNNER` is set for use in Step 6b. `SC_PLUGIN_CHANNEL`, `SC_PLUGIN_EXPECTED_REF`, `SC_PLUGIN_KEY`, `SC_PLUGIN_INSTALL_PATH`, `SC_PLUGIN_VERSION`, and `SC_PLUGIN_GIT_SHA` are emitted by the deterministic plugin-state helper and are the source of truth for channel-safe update decisions. If the user picks "Not now" later, `declined` will be re-set to the specific version declined (per Gap #1's version-aware decline rule).

If `SC_PLUGIN_STALE_BETA=true`, print this message with the variables substituted, then stop before any project
maintenance, migration, doctor, setup, or recovery routing:

```
SweetClaude beta plugin update required.
──────────────────────────────────────
Installed plugin: {SC_PLUGIN_KEY}
Installed version: {SC_PLUGIN_VERSION}
Minimum safe beta: {SC_PLUGIN_MIN_SAFE_BETA_VERSION}

Run this Claude Code command:
{SC_PLUGIN_UPDATE_COMMAND}

Then restart Claude Code and run:
/sweetclaude:update

Stopping here because this installed beta is old enough to have unsafe
update/recovery behavior. No project files were changed.
```

Do not invoke `/sweetclaude:update`, `/sweetclaude:doctor`,
`/sweetclaude:recover`, `/sweetclaude:migrate`, `_migrate`, setup, purge, or
any project-mutating skill from this stale-beta stop path.

---

## Step 1: Read current install state

Use the plugin-state variables emitted by Step -1. Do not manually choose a
SweetClaude entry from `installed_plugins.json` when the helper has provided
one. The helper understands the current plugin root, local project-scoped
installs, legacy `sweetclaude@sweetclaude` beta installs, and the stable/beta
channel split.

Required variables:

- `SC_PLUGIN_KEY` — the exact installed plugin key to repair after sync
- `SC_PLUGIN_INSTALL_PATH` — the plugin cache directory to update
- `SC_PLUGIN_VERSION` — current installed version
- `SC_PLUGIN_GIT_SHA` — currently recorded installed commit
- `SC_PLUGIN_CHANNEL` — `stable` or `beta`
- `SC_PLUGIN_EXPECTED_REF` — `stable-3.x` or `beta-4.x`
- `SC_PLUGIN_LEGACY_MARKETPLACE` — true when a legacy marketplace key is in use

If `SC_PLUGIN_OK` is not `true`, stop and report that SweetClaude cannot find a
repairable installed plugin entry. Do not guess from arbitrary plugin cache
directories.

Set:

```bash
installPath="$SC_PLUGIN_INSTALL_PATH"
installed_version="$SC_PLUGIN_VERSION"
installed_sha="$SC_PLUGIN_GIT_SHA"
EXPECTED_REF="$SC_PLUGIN_EXPECTED_REF"
PLUGIN_KEY="$SC_PLUGIN_KEY"
```

Read `{installPath}/.claude-plugin/plugin.json` and extract:
- `repository` — the GitHub repo URL (fallback: `https://github.com/carson-sweet/sweetclaude`)

Present:
```
SweetClaude v{installed_version}
════════════════════════════════

Installed: {installPath}
Commit:    {installed_sha (short)}
Channel:   {SC_PLUGIN_CHANNEL} ({EXPECTED_REF})
Source:    {repository}
```

If `SC_PLUGIN_LEGACY_MARKETPLACE=true`, include one warning line:

```
Legacy install metadata detected; this update will repair the recorded version, commit, and install path for the existing plugin entry.
```

---

## Step 2: Get the latest source

### 2a: Local repo (developer workflow)

Read `~/.claude/sweetclaude-install.json` (written by `install.sh`) to find the local repo path:

```bash
REPO_PATH=$(python3 -c "
import json, os
try:
    d = json.load(open(os.path.expanduser('~/.claude/sweetclaude-install.json')))
    print(d.get('repo_path', ''))
except: print('')
" 2>/dev/null)
```

If `REPO_PATH` is non-empty AND `$REPO_PATH/package.json` exists AND the repo has a remote matching the repository URL, fetch from origin. Use the local repo only when its current branch exactly matches `$EXPECTED_REF`. If the local repo is on any other branch, print a warning and ignore it for this update so beta users cannot be updated from main or stable users from beta:

```bash
git -C "$REPO_PATH" fetch origin
LOCAL_BRANCH=$(git -C "$REPO_PATH" branch --show-current 2>/dev/null || true)
if [ "$LOCAL_BRANCH" != "$EXPECTED_REF" ]; then
  echo "Ignoring local SweetClaude repo for update: branch $LOCAL_BRANCH does not match channel ref $EXPECTED_REF"
  REPO_PATH=""
else
  git -C "$REPO_PATH" log --oneline -1
fi
```

- If fetch succeeds and the local branch matches `$EXPECTED_REF`: use `$REPO_PATH` as SOURCE_DIR. The local repo may be ahead of GitHub on that channel branch — that is intentional and correct. Skip to Step 3.
- If fetch fails (network error): warn ("Could not reach GitHub to check for remote updates — proceeding with local repo state.") and use `$REPO_PATH` as SOURCE_DIR. Skip to Step 3.

### 2b: GitHub (standard user workflow)

If no local repo found, clone a fresh shallow copy from GitHub. Use `gh` if available (handles private repos with existing auth), fall back to `git`.

```bash
TMPDIR=$(mktemp -d)

if command -v gh &>/dev/null; then
  gh repo clone {owner}/{repo} "$TMPDIR/sweetclaude" -- --depth 1 --branch "$EXPECTED_REF"
else
  git clone --depth 1 --branch "$EXPECTED_REF" {repository_url} "$TMPDIR/sweetclaude"
fi
```

If clone fails with an auth error, tell the user:
> "The SweetClaude repo requires authentication. Run `! gh auth login` to authenticate with GitHub, then try again."

Do not retry. Do not ask for tokens. On any failure, stop.

Use `$TMPDIR/sweetclaude` as SOURCE_DIR.

---

## Step 3: Compare versions

When SOURCE_DIR is the local repo (came from Step 2a), compare against `origin/$EXPECTED_REF` — not local `HEAD` and not `origin/HEAD` — so the current install channel is preserved and commits on the matching channel branch are detected. If origin is ahead of local HEAD, pull before syncing:

```bash
# Determine effective SHA to compare
CONFIGURED_REPO=$(python3 -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/sweetclaude-install.json'))); print(d.get('repo_path',''))" 2>/dev/null || echo "")
if [ "$SOURCE_DIR" = "$CONFIGURED_REPO" ]; then
  EFFECTIVE_SHA=$(git -C $SOURCE_DIR rev-parse "origin/$EXPECTED_REF")
  LOCAL_SHA=$(git -C $SOURCE_DIR rev-parse HEAD)
  if [ "$EFFECTIVE_SHA" != "$LOCAL_SHA" ]; then
    git -C $SOURCE_DIR pull --ff-only origin
  fi
else
  EFFECTIVE_SHA=$(git -C $SOURCE_DIR rev-parse HEAD)
fi
git -C $SOURCE_DIR log --oneline -5
cat $SOURCE_DIR/package.json
```

If EFFECTIVE_SHA matches the installed `gitCommitSha`: "Already up to date." Clean up temp dir if used. **Then jump to Step 6b** — even when the framework is up to date, the current project may still have pending schema migrations from a previous update that wasn't completed (e.g., user updated in another project, then opened this one without restarting bootstrap). Do not stop.

Otherwise, show what changed since the installed version:

```bash
git -C $SOURCE_DIR log --oneline {installed_sha}..{EFFECTIVE_SHA}
```

Then diff against installed:

```bash
diff -rq $SOURCE_DIR/skills/ {installPath}/skills/ 2>/dev/null
diff -rq $SOURCE_DIR/rules/ ${CLAUDE_PLUGIN_ROOT}/rules/ 2>/dev/null
diff -rq $SOURCE_DIR/hooks/ ${CLAUDE_PLUGIN_ROOT}/hooks/ 2>/dev/null
diff -rq $SOURCE_DIR/config/ ${CLAUDE_PLUGIN_ROOT}/config/ 2>/dev/null
diff -rq $SOURCE_DIR/scripts/ {installPath}/scripts/ 2>/dev/null
```

Present a summary:

```
Update available: {installed_sha_short} → {new_sha_short}
═══════════════════════════════════════════════════════════

Commits:
  {oneline log}

Changes:
  Skills:  {N} modified, {N} added, {N} removed
  Rules:   {N}
  Hooks:   {N}
  Config:  {N}
  Agents:  {N}
  Scripts: {N}
```

Wait for user confirmation before proceeding.

---

## Step 3b: Artifact safety check for removed skills

Before syncing, identify skills being removed — present in installed but absent in source:

```bash
diff -rq {installPath}/skills/ $SOURCE_DIR/skills/ 2>/dev/null \
  | grep "^Only in {installPath}/skills" \
  | sed 's|.*skills/||'
```

For each removed skill, check whether it owns live artifact content. Resolve `base_path`:

```bash
python3 -c "
import yaml, pathlib
p = pathlib.Path('.sweetclaude/state/session-state.yaml')
if p.exists():
    d = yaml.safe_load(p.read_text()) or {}
    print(d.get('paths', {}).get('product_base', '.sweetclaude/product'))
else:
    print('.sweetclaude/product')
" 2>/dev/null || echo ".sweetclaude/product"
```

| Skill | Artifact path |
|---|---|
| `product-milestones` | `{base_path}/milestones/MS-*.md` |
| `product-parking-lot` or `product-backlog` | `{base_path}/backlog/ISSUE-*.md` or `{base_path}/backlog/stories/*.md` |
| `product-sprint-plan` | `{base_path}/sprints/` (any files) |
| `user-personas` | `.sweetclaude/state/personas.yaml` |
| `product-user-stories` | `{base_path}/stories/US-*.md` (any files) |
| `document-corpus` | `.sweetclaude/state/corpus-pipeline.yaml` |

Only run this check if `.sweetclaude/` exists in the current project directory.

If any removed skill has matching live artifacts, pause and present:

```
⚠ Artifact safety check — removed skills with live content:
  {skill-name}: {artifact path} — {N} items found
  [repeat per affected skill]

  This content will become orphaned when these skills are removed.

  Options:
    1. Proceed anyway — I understand the content will be orphaned
    2. Cancel — I'll migrate the content before updating
    3. Skip removing these skills — sync everything else
```

Wait for user choice before continuing.

If no removed skills have live artifacts, continue silently to Step 4.

---

## Step 3c: Major version gate (v3 → v4)

After determining the installed version and the incoming version, check for a v3→v4 major upgrade:

```python
import re

def major_version(v):
    m = re.match(r'^(\d+)', str(v or ''))
    return int(m.group(1)) if m else 0

current_major = major_version(installed_version)   # from Step 1
incoming_major = major_version(new_version)         # from Step 3 source package.json
```

If `current_major == 3` and `incoming_major >= 4`:

Present AskUserQuestion with this body block before any sync:

> **SweetClaude v4 is available — this is a major release.**
>
> All work items use the ISSUE-NNN prefix and are stored in `.sweetclaude/product/backlog/`. Each project migrates independently the first time you open it after updating.
>
> Migration creates a safety backup and can be rolled back. Active and future stories must migrate. Done stories are optional.

- **Options:** `Yes, update`, `Not now`
- On `Not now`:
  - Write `framework.update.declined: true` to `.sweetclaude/state/sweetclaude.yaml` (if it exists in the current project).
  - **Do NOT re-offer** in subsequent bootstrap runs until the user explicitly runs `/sweetclaude:update` again.
  - Clean up temp dir if used. Stop.
- On `Yes, update`: proceed to Step 4.

If it is not a v3→v4 transition (e.g. minor/patch updates), skip this step and proceed directly to Step 4.

## Step 4: Sync

Before syncing, capture which skills are new (present in source, absent in the currently installed path). Claude Code loads skills at session start, so new skills added during this update will not be available until the user restarts.

```bash
NEW_SKILLS=""
if [ -d "{installPath}/skills" ]; then
  for skill_dir in "$SOURCE_DIR/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    if [ ! -d "{installPath}/skills/$skill_name" ]; then
      NEW_SKILLS="${NEW_SKILLS:+$NEW_SKILLS }$skill_name"
    fi
  done
fi
echo "NEW_SKILLS=${NEW_SKILLS}"
```

Save the value of `NEW_SKILLS` — it is used in the Step 6c success report.

Copy from SOURCE_DIR to installed locations. Use `rsync --delete` to remove files that no longer exist in the source.

```bash
# Skills → plugin cache
rsync -a --delete $SOURCE_DIR/skills/ {installPath}/skills/

# Hooks → plugin cache (hooks.json uses ${CLAUDE_PLUGIN_ROOT}/hooks/ — must stay current)
rsync -a --delete $SOURCE_DIR/hooks/ {installPath}/hooks/

# Top-level files → plugin cache
for f in CLAUDE.md package.json LICENSE CHANGELOG.md; do
  [ -f "$SOURCE_DIR/$f" ] && cp "$SOURCE_DIR/$f" {installPath}/
done

# Plugin manifest
rsync -a $SOURCE_DIR/.claude-plugin/ {installPath}/.claude-plugin/

# Scripts → plugin cache
if [ -d "$SOURCE_DIR/scripts" ]; then
  rsync -a --delete $SOURCE_DIR/scripts/ {installPath}/scripts/
fi

# Framework dirs → plugin cache
rsync -a --delete $SOURCE_DIR/rules/ ${CLAUDE_PLUGIN_ROOT}/rules/
rsync -a --delete $SOURCE_DIR/hooks/ ${CLAUDE_PLUGIN_ROOT}/hooks/
rsync -a --delete $SOURCE_DIR/config/ ${CLAUDE_PLUGIN_ROOT}/config/

# Ensure hooks are executable
chmod +x "${CLAUDE_PLUGIN_ROOT}/hooks/"*.sh 2>/dev/null || true

# Verify registry file synced correctly
ls ${CLAUDE_PLUGIN_ROOT}/config/skills-registry.yaml 2>/dev/null || echo "WARNING: skills-registry.yaml not found after sync"

# Claude Code may load skills from a version-named directory (e.g. 4.0.6-beta/)
# rather than installPath (e.g. 3.52.14/) when they differ. Sync to both.
# Derive the version-named dir from the new package.json version.
NEW_VER=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR/package.json'))['version'])" 2>/dev/null)
PLUGIN_CACHE_PARENT=$(dirname {installPath})
VERSION_DIR="$PLUGIN_CACHE_PARENT/$NEW_VER"
if [ -n "$NEW_VER" ] && [ "$VERSION_DIR" != "{installPath}" ]; then
  mkdir -p "$VERSION_DIR/skills" "$VERSION_DIR/hooks"
  rsync -a --delete $SOURCE_DIR/skills/ "$VERSION_DIR/skills/"
  rsync -a --delete $SOURCE_DIR/hooks/ "$VERSION_DIR/hooks/"
  if [ -d "$SOURCE_DIR/scripts" ]; then
    rsync -a --delete $SOURCE_DIR/scripts/ "$VERSION_DIR/scripts/"
  fi
  if [ -d "$SOURCE_DIR/rules" ]; then
    rsync -a --delete $SOURCE_DIR/rules/ "$VERSION_DIR/rules/"
  fi
  if [ -d "$SOURCE_DIR/config" ]; then
    rsync -a --delete $SOURCE_DIR/config/ "$VERSION_DIR/config/"
  fi
  rsync -a $SOURCE_DIR/.claude-plugin/ "$VERSION_DIR/.claude-plugin/"
  for f in CLAUDE.md package.json LICENSE CHANGELOG.md; do
    [ -f "$SOURCE_DIR/$f" ] && cp "$SOURCE_DIR/$f" "$VERSION_DIR/"
  done
  echo "Synced to version-named dir: $VERSION_DIR"
fi
```

---

## Step 4b: Reconcile SweetClaude hook entries in settings.json

Strip broken `${CLAUDE_PLUGIN_ROOT}` literals (from pre-3.68.2 installs) and stale plugin-version paths from `~/.claude/settings.json`. The three preflight hooks themselves are plugin-native (auto-loaded from `hooks/hooks.json`) and need no settings.json entry.

```bash
HOOK_RECONCILE_LOG=$(mktemp -t sc-hook-reconcile.XXXXXX) || HOOK_RECONCILE_LOG=/tmp/sc-hook-reconcile.log
if ! python3 ${CLAUDE_PLUGIN_ROOT}/scripts/maintenance/ensure-global-hooks.py >"$HOOK_RECONCILE_LOG" 2>&1; then
  echo "warning: hook reconciliation failed — see $HOOK_RECONCILE_LOG"
fi
cat "$HOOK_RECONCILE_LOG"
```

Read `$HOOK_RECONCILE_LOG`. If it contains any `cleaned:` line, sum the counts across buckets and include `✓ Hooks: reconciled N stale/broken entries in ~/.claude/settings.json` in the Step 6c success report (where N is the total). Also add this line to the report's tail:

> → Restart Claude Code to stop the in-session `${CLAUDE_PLUGIN_ROOT}` error from old settings.json entries. The hooks themselves load from the plugin's hooks.json and are unaffected.

If `$HOOK_RECONCILE_LOG` contains only `ok: hooks already up to date`, omit both lines entirely.

---

## Step 5: Update plugin metadata

Update `~/.claude/plugins/installed_plugins.json` through the deterministic
plugin-state helper. Do not hand-edit JSON and do not hard-code
`sweetclaude@sweetclaude`; update the exact `SC_PLUGIN_KEY` selected in Step 1.

```bash
NEW_SHA=$(git -C "$SOURCE_DIR" rev-parse HEAD)
NEW_VER=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SOURCE_DIR/package.json")
SYNC_TARGET="${VERSION_DIR:-$installPath}"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/maintenance/plugin-state.py \
  --project-dir . \
  repair \
  --plugin-key "$PLUGIN_KEY" \
  --install-path "$SYNC_TARGET" \
  --version "$NEW_VER" \
  --sha "$NEW_SHA"
```

This repairs stale existing-user metadata: `lastUpdated`, `gitCommitSha`,
`version`, and `installPath` all move to the just-synced channel version.

---

## Step 5b: Update project installed_version

If `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory, write `framework.installed_version` to match the just-synced version. This is framework identity metadata — the project records which version it was last synced against — not project-state mutation.

```bash
if [ -f .sweetclaude/state/sweetclaude.yaml ]; then
  python3 - .sweetclaude/state/sweetclaude.yaml "$NEW_VER" << 'PY'
import sys, yaml, os, tempfile
sc_path, new_ver = sys.argv[1], sys.argv[2]
try:
    with open(sc_path) as f:
        d = yaml.safe_load(f) or {}
except Exception:
    sys.exit(0)
recorded = (d.get('framework') or {}).get('installed_version')
if recorded == new_ver:
    sys.exit(0)
d.setdefault('framework', {})['installed_version'] = new_ver
with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(sc_path), suffix='.tmp', delete=False) as tmp:
    yaml.safe_dump(d, tmp, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp_name = tmp.name
os.replace(tmp_name, sc_path)
PY
fi
```

---

## Step 6: Clean up

If a temp directory was used, remove it:
```bash
rm -rf "$TMPDIR"
```

Run a final diff to confirm sync:
```bash
SYNC_TARGET="${VERSION_DIR:-{installPath}}"
diff -rq $SOURCE_DIR/skills/ "$SYNC_TARGET/skills/" 2>/dev/null
diff -rq $SOURCE_DIR/scripts/ "$SYNC_TARGET/scripts/" 2>/dev/null
```

Continue to Step 6b. The user-facing success report is deferred until Step 6b confirms project state is coherent — reporting "updated" before the drift verdict is what caused BUG-002.

---

## Step 6b: Project-state drift detection and safety routing

This beta update path syncs framework files only. It does not run
project-state migrations inline.

Steps 6b, 6b1, and 6b2 are read-only project checks. If any project drift or
legacy taxonomy state is detected, report it and route to `/sweetclaude:doctor`
or `/sweetclaude:recover`. Do not invoke `_migrate`, `purge`, `adopt`, or any
layout-specific migration from `/sweetclaude:update`.

Only run if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory — skip silently otherwise. (Update can be run from any directory; this step only applies when run from inside a SweetClaude project.)

After the framework sync, the registry on disk may declare schema versions newer
than this project's state files. Surface that immediately, without persisting
drift markers or mutating project state.

Parse the runner's stdout directly. Do NOT read `pending-drift-decision.yaml` —
that marker is written by `drift-gate.sh` at session start and represents
pre-update state. The fresh stdout from the just-synced runner is authoritative
for this step.

```bash
DRIFT_COUNT=0
if [ -f .sweetclaude/state/sweetclaude.yaml ] && [ -n "$RUNNER" ] && [ -f "$RUNNER" ]; then
  DRIFT_OUTPUT=$(python3 "$RUNNER" --project-dir . --scan-drift 2>/dev/null)
  DRIFT_COUNT=$(printf '%s\n' "$DRIFT_OUTPUT" | grep -c '\[DRIFT\]' | tr -d ' ')
fi
echo "DRIFT_COUNT=$DRIFT_COUNT"
```

If `DRIFT_COUNT` is 0: continue to Step 6b1. Do not remove or rewrite any
project state marker from update.

If `DRIFT_COUNT > 0`: do NOT print the success report. The framework files were
synced, but this project needs a separate migration/recovery decision. Print
the halt diagnostic:

```
SweetClaude update PARTIAL.
═══════════════════════════

✓ Version:    {old_version} → {new_version}  (framework synced)
✗ Project:    {DRIFT_COUNT} state file(s) need migration review

No project files were changed by update.
Run /sweetclaude:doctor — it auto-fixes state schema drift through the
migration runner (backed up, reversible). Bootstrap will also offer this
migration at the next session start.

Drift details:
  {Print the DRIFT lines from $DRIFT_OUTPUT}

→ The framework is at v{new_version}. Project state was not migrated inline.
```

Stop. Do NOT continue to Step 7.

---

## Step 6b1: Orphan file scan

Only run if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory — skip silently otherwise.

Scan for work item files that may have been lost, abandoned, or orphaned from previous SweetClaude versions — files in typed subdirectories (retired in 4.1.0), legacy prefixes, or other locations the primary migration wouldn't find.

```bash
ORPHAN_COUNT=0
MIGRATE_SCRIPT=${CLAUDE_PLUGIN_ROOT}/scripts/migrate/migrate-v3-to-v4.py
if [ ! -f "$MIGRATE_SCRIPT" ]; then
  MIGRATE_SCRIPT=$(find "$(dirname "${CLAUDE_PLUGIN_ROOT}")" -type f -name 'migrate-v3-to-v4.py' 2>/dev/null | sort -V | tail -1)
fi
if [ -f .sweetclaude/state/sweetclaude.yaml ] && [ -n "$MIGRATE_SCRIPT" ] && [ -f "$MIGRATE_SCRIPT" ]; then
  ORPHAN_OUT=$(python3 "$MIGRATE_SCRIPT" scan-orphans --project-dir . 2>/dev/null)
  ORPHAN_COUNT=$(echo "$ORPHAN_OUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('orphan_count', 0))" 2>/dev/null || echo 0)
fi
echo "ORPHAN_COUNT=$ORPHAN_COUNT"
```

If `ORPHAN_COUNT` is 0: continue silently to Step 6b2.

If `ORPHAN_COUNT > 0`: run `group-orphans` to get grouping data:

```bash
GROUP_OUT=$(python3 "$MIGRATE_SCRIPT" group-orphans --project-dir . 2>/dev/null)
```

Present a summary of findings:

```
Found {total_files} orphaned work item file(s) outside the primary backlog.
```

Then present via **AskUserQuestion** (single-select):

> "How would you like to handle these orphaned files?"
>
> Options:
> - **Re-onboard all as new ISSUE items** — creates a new ISSUE-NNN file in backlog/ for each orphan, preserving original content and linking back to the source via `reonboarded_from` metadata.
> - **Review by group** — groups orphans by category and location. You decide what to do with each group (re-onboard, archive, or leave in place).
> - **Review one by one** — step through each orphan individually and decide its fate (re-onboard, archive, leave in place, or skip).
> - **Archive all** — moves all orphans to `archive/orphans/` where they are preserved but no longer flagged.

(No "Leave all in place" option in the menu — the user can dismiss the menu with "Something else" and say they want to leave them.)

### Action path: Re-onboard all

Collect all file paths from `ORPHAN_OUT` findings:

```bash
PATHS=$(echo "$ORPHAN_OUT" | python3 -c "import sys, json; print(json.dumps([f['file'] for f in json.load(sys.stdin).get('findings', [])]))")
python3 "$MIGRATE_SCRIPT" reonboard-orphans --project-dir . --paths "$PATHS"
```

Report results: "{N} files re-onboarded as new ISSUE items." List each mapping: `{source} → {new_id}`.

### Action path: Review by group

If `has_grouping` from `GROUP_OUT` is false (only one file or one group with one file), fall through to "Review one by one" instead.

Otherwise, iterate through each group in `GROUP_OUT`. For each group, present:

```
Group: {label} ({count} files)
Directory: {directory}

Files:
  {id} — {title} [{status}]
  ...
```

Then present via **AskUserQuestion** (single-select) per group:

> "What would you like to do with this group?"
>
> Options:
> - **Re-onboard this group** — creates new ISSUE-NNN files for all items in this group.
> - **Archive this group** — moves all items to `archive/orphans/`.
> - **Leave in place** — acknowledges these files so they stop being flagged.
> - **Skip for now** — leaves files untouched without acknowledging (will be flagged again next scan).

Execute the chosen action for each group using the appropriate CLI subcommand:
- Re-onboard: `reonboard-orphans --paths {json list of group file paths}`
- Archive: `archive-orphans --paths {json list of group file paths}`
- Leave in place: `acknowledge-orphans --paths {json list of group file paths}`
- Skip: no action

### Action path: Review one by one

Iterate through all findings from `ORPHAN_OUT`. For each file, present:

```
{file}
  ID: {id}  Title: {title}  Status: {status}  Category: {category}
```

Then present via **AskUserQuestion** (single-select) per file:

> "What would you like to do with this file?"
>
> Options:
> - **Re-onboard** — creates a new ISSUE-NNN file from this orphan.
> - **Archive** — moves to `archive/orphans/`.
> - **Leave in place** — acknowledges so it stops being flagged.
> - **Skip** — leave untouched (will be flagged again next scan).

Execute each choice using the `resolve-orphan` CLI:

```bash
python3 "$MIGRATE_SCRIPT" resolve-orphan --project-dir . --path "{file}" --action "{action}"
```

### Action path: Archive all

```bash
PATHS=$(echo "$ORPHAN_OUT" | python3 -c "import sys, json; print(json.dumps([f['file'] for f in json.load(sys.stdin).get('findings', [])]))")
python3 "$MIGRATE_SCRIPT" archive-orphans --project-dir . --paths "$PATHS"
```

Report: "{N} orphaned files archived to `archive/orphans/`."

### Action path: Leave all in place (user typed "Something else")

If the user says they want to leave all orphans in place, acknowledge them all so they stop being flagged:

```bash
PATHS=$(echo "$ORPHAN_OUT" | python3 -c "import sys, json; print(json.dumps([f['file'] for f in json.load(sys.stdin).get('findings', [])]))")
python3 "$MIGRATE_SCRIPT" acknowledge-orphans --project-dir . --paths "$PATHS"
```

Report: "{N} orphaned files acknowledged — they will no longer be flagged."

Then continue to Step 6b2.

---

## Step 6b2: Taxonomy migration detection

Only run if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory — skip silently otherwise.

Check for old-taxonomy files that need migration to the ISSUE-NNN format:

```bash
OLD_TAXONOMY=0
if [ -d .sweetclaude/product/backlog ]; then
  BL_COUNT=$(find .sweetclaude/product/backlog -maxdepth 1 -name 'BL-*.md' 2>/dev/null | wc -l | tr -d ' ')
  STORY_COUNT=$(find .sweetclaude/product/backlog -maxdepth 2 -name 'STORY-*.md' 2>/dev/null | wc -l | tr -d ' ')
  BUG_COUNT=$(find .sweetclaude/product/backlog -maxdepth 2 -name 'BUG-*.md' 2>/dev/null | wc -l | tr -d ' ')
  DEBT_COUNT=$(find .sweetclaude/product/backlog -maxdepth 2 -name 'DEBT-*.md' 2>/dev/null | wc -l | tr -d ' ')
  CHORE_COUNT=$(find .sweetclaude/product/backlog -maxdepth 2 -name 'CHORE-*.md' 2>/dev/null | wc -l | tr -d ' ')
  OLD_TAXONOMY=$((BL_COUNT + STORY_COUNT + BUG_COUNT + DEBT_COUNT + CHORE_COUNT))
fi
echo "OLD_TAXONOMY=$OLD_TAXONOMY"
```

If `OLD_TAXONOMY` is 0: skip — project is already on the new taxonomy.

If `OLD_TAXONOMY > 0`: do not present a migration prompt and do not invoke
`migrate_taxonomy.py`. Report the condition as non-blocking:

```
Found {OLD_TAXONOMY} work item(s) using legacy taxonomy prefixes
(BL-/STORY-/BUG-/DEBT-/CHORE-).

No files were changed. The taxonomy migration prompt is disabled in this beta
hotfix because the current migrator is not safely executable for all supported
v4 project layouts. Continue using the project as-is; run `sweetclaude:doctor`
for read-only diagnostics.
```

Then continue to Step 6b3. Do not write `doctor-prompt-pending.json`.

---

## Step 6b3: Bold-format file detection

Only run if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory — skip silently otherwise.

Scan for Bold-format artifact files that should be converted to YAML frontmatter:

```bash
BOLD_COUNT=0
CONVERTER="$HOME/.claude/scripts/sweetclaude/format_converter.py"
if [ -f "$CONVERTER" ]; then
  BOLD_COUNT=$(python3 "$CONVERTER" --project-dir . --dry-run 2>/dev/null | grep -c '"action": "would_convert"' || true)
fi
echo "BOLD_COUNT=$BOLD_COUNT"
```

If `BOLD_COUNT` is 0: skip — all files use YAML frontmatter.

If `BOLD_COUNT > 0`: report the condition as non-blocking:

```
Found {BOLD_COUNT} artifact file(s) using Bold Key-Value format instead of
YAML frontmatter. These files are readable but won't participate in status
propagation. Run `sweetclaude:doctor --check format_consistency --auto-fix`
to convert them.
```

Then continue to Step 6c.

---

## Step 6c: Success report (only reached when read-only project checks are clean)

```
SweetClaude updated.
═══════════════════

✓ Version:    {old_version} → {new_version}  (or same if unchanged)
✓ Commit:     {old_sha_short} → {new_sha_short}
✓ Files:      {total count} synced across skills, rules, hooks, config, agents
✓ Hooks:      {only include this line if Step 4b reported cleaned: entries}
✓ Project:    clean

→ Restart Claude Code to use this update — skills are loaded at session start
  and are not updated in the current session.
```

Print exactly `✓ Project:    clean`. Do not print `clean (verified post-migrate)`
because update does not run project migrations inline.

If `NEW_SKILLS` (from Step 4) is non-empty, append this block after the success report — one line per new skill:

```
New skills added (not available until restart):
  {list each name from NEW_SKILLS, one per line, prefixed with /sweetclaude:}
```

Do not mention any `/sweetclaude:` command as something the user can run now. Do not ask "Want to run it?" or offer to invoke any skill. The current session does not have the updated skill set.

After printing the template (and the new-skills block if applicable), continue
to Step 7. Do not write `doctor-prompt-pending.json` from update.

---

## Step 7: Surface capabilities

Read [capability-surface.md](capability-surface.md) for the "What's new in this
update" section only. Do not execute its project skill-state migration,
bootstrap, or onboarding sections from update.


---

## Step 7b: Feature configuration check

Skip feature configuration from update. Feature setup is project mutation and
belongs in a separate doctor/setup flow with a plan and explicit approval.

---

## Step 7c: Configure plan directory

Skip plan-directory configuration from update. Do not write project settings
from update.

---

## Step 8: Project-state migration is not run inline

The current project is not migrated inline after framework sync. Other projects
the user opens must be classified by bootstrap/status/recover guards before any
mutation-capable migration path runs.

Rationale:

- Framework sync and project-state mutation must stay operationally independent.
- Update may report that project migration or recovery is needed, but must not
  perform it inline.
- Project mutation requires a dedicated safety path with diagnosis, plan,
  snapshot, approval, execution manifest, verification, and rollback or
  fail-closed behavior.

---

## Rules

- **Always show the diff preview and wait for confirmation before syncing.**
- **Use rsync --delete.** Removed files in the source should be removed from installed locations.
- **Prefer `gh` over `git` for cloning.** It handles private repo auth transparently.
- **Never ask for tokens or credentials.** If auth fails, tell the user to run `gh auth login`.
- **Always clean up temp directories**, even on failure.
- **Do not touch ~/.claude/settings.json.** Hook wiring is handled by install.sh.
- **Do not modify ~/CLAUDE.md.** Also handled by install.sh.
- **Do not mutate per-project `.sweetclaude/` directories from update except for
  `framework.installed_version` (Step 5b) and explicit user decline state in
  the major-version gate.** Framework sync is global; project
  migration/recovery is separate.
