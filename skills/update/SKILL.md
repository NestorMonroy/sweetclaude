---
spdx-license: AGPL-3.0-or-later
user-invocable: true
description: "Update SweetClaude to the latest version from GitHub (or a local repo)."
---

!`bash ~/.claude/hooks/sweetclaude/record-event.sh skill_invoked "sweetclaude:update" 2>/dev/null || true`

!`cat .sweetclaude/state/session-state.yaml 2>/dev/null || echo "STATE_NOT_FOUND"`

# Update SweetClaude

Fetch the latest SweetClaude and sync it to all installed locations.

**This skill can be run from any project directory.**

---

## Step -1: Pre-flight

Ensure the versionless framework path is populated, clear any previous update decline (running `/sweetclaude:update` is explicit re-engagement), and emit the runner path for later steps.

```bash
PREFLIGHT="$HOME/.claude/scripts/sweetclaude/preflight.sh"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$CLAUDE_PLUGIN_ROOT/scripts/preflight.sh" ]; then
  mkdir -p ~/.claude/scripts/sweetclaude
  rsync -a "$CLAUDE_PLUGIN_ROOT/scripts/" ~/.claude/scripts/sweetclaude/ 2>/dev/null || true
  PREFLIGHT="$CLAUDE_PLUGIN_ROOT/scripts/preflight.sh"
elif [ ! -f "$PREFLIGHT" ]; then
  IP=$(python3 -c "
import json, os
try:
    d = json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')))
    entries = []
    for plugin_key, versions in d.get('plugins', {}).items():
        if 'sweetclaude' not in str(plugin_key).lower() or not isinstance(versions, list):
            continue
        for e in versions:
            if e.get('scope') != 'user':
                continue
            version = str(e.get('version') or '')
            market = str(plugin_key).lower()
            beta = 'beta' in market or '-' in version or version.lstrip('v').startswith('4.')
            if beta:
                entries.append(e)
    entries.sort(key=lambda e: e.get('lastUpdated', ''), reverse=True)
    for e in entries:
        ip = e.get('installPath', '')
        if ip and os.path.isdir(os.path.join(ip, 'scripts')):
            print(ip)
            break
except Exception:
    pass
" 2>/dev/null)
  if [ -n "$IP" ] && [ -d "$IP/scripts" ]; then
    mkdir -p ~/.claude/scripts/sweetclaude
    rsync -a "$IP/scripts/" ~/.claude/scripts/sweetclaude/ 2>/dev/null || true
  fi
fi
if [ -f "$PREFLIGHT" ]; then
  eval "$(bash "$PREFLIGHT" --from-update 2>/dev/null)"
fi
```

`DECLINE_CLEARED=true` if the project's `framework.update.declined` was cleared. `RUNNER` is set for use in Step 6b. `SC_PLUGIN_CHANNEL`, `SC_PLUGIN_EXPECTED_REF`, `SC_PLUGIN_KEY`, `SC_PLUGIN_INSTALL_PATH`, `SC_PLUGIN_VERSION`, and `SC_PLUGIN_GIT_SHA` are emitted by the deterministic plugin-state helper and are the source of truth for channel-safe update decisions. If the user picks "Not now" later, `declined` will be re-set to the specific version declined (per Gap #1's version-aware decline rule).

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

If `REPO_PATH` is non-empty AND `$REPO_PATH/package.json` exists AND the repo has a remote matching the repository URL, fetch from origin. Use the local repo only when its current branch exactly matches `$EXPECTED_REF`. If the local repo is on any other branch, print a warning and ignore it for this update so beta users cannot be updated from main and stable users cannot be updated from beta:

```bash
LOCAL_BRANCH=$(git -C "$REPO_PATH" branch --show-current 2>/dev/null || true)
if [ "$LOCAL_BRANCH" != "$EXPECTED_REF" ]; then
  echo "Ignoring local SweetClaude repo for update: branch $LOCAL_BRANCH does not match channel ref $EXPECTED_REF"
  REPO_PATH=""
elif git -C "$REPO_PATH" fetch origin; then
  git -C "$REPO_PATH" log --oneline -1
else
  echo "Could not reach GitHub to check for remote updates — proceeding with local repo state."
fi
```

- If the local branch matches `$EXPECTED_REF`: use `$REPO_PATH` as SOURCE_DIR. The local repo may be ahead of GitHub on that channel branch — that is intentional and correct. Skip to Step 3.
- If fetch fails (network error): proceed with the same branch-checked local repo state. Do not use a local repo from another branch.

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

## Step 2c: Prerelease check (STORY-050)

Before comparing versions for the channel update, check if any prerelease tags are newer than the installed version. Stable installs ignore prereleases; beta installs can opt into newer prerelease tags.

```bash
INSTALLED_VERSION="$installed_version"

# Read prerelease_declined from this project's sweetclaude.yaml (if present —
# project-level declines persist across update runs in that project only).
DECLINED_PRERELEASE=$(python3 -c "
import yaml
try:
    d = yaml.safe_load(open('.sweetclaude/state/sweetclaude.yaml')) or {}
    print((d.get('framework') or {}).get('update', {}).get('prerelease_declined', '') or '')
except Exception:
    pass
" 2>/dev/null)

PRERELEASE_OUT=$(python3 ~/.claude/scripts/sweetclaude/maintenance/check-prerelease.py \
    --installed-version "$INSTALLED_VERSION" \
    --declined "$DECLINED_PRERELEASE" \
    --repo-dir "$SOURCE_DIR" 2>/dev/null)

SHOULD_PROMPT=$(echo "$PRERELEASE_OUT" | python3 -c "import sys, json; print('true' if json.load(sys.stdin).get('should_prompt') else 'false')")
PRERELEASE_TAG=$(echo "$PRERELEASE_OUT" | python3 -c "import sys, json; v=json.load(sys.stdin).get('prerelease_available'); print(v if v else '')")
```

If `SHOULD_PROMPT` is `true`, present **AskUserQuestion**:

> ⚠ **SweetClaude {PRERELEASE_TAG} is available as a prerelease.**
>
> Prereleases are not final. They may contain bugs that have not yet been caught and may change in incompatible ways before the final release. Real-world usage helps surface issues — but if you need stability for production work, wait for the final release.
>
> - Currently installed: `{INSTALLED_VERSION}`
> - Available prerelease: `{PRERELEASE_TAG}`

Options:
- **Install the prerelease** — pull and install from the `{PRERELEASE_TAG}` tag instead of the channel branch
- **Wait for the final release** — record the decline and proceed with the normal channel update flow

On **Install the prerelease**:
```bash
# Ensure TMPDIR is set — Step 2a (local repo path) doesn't create one, so we
# need a fresh tempdir here regardless of which Step 2 path ran.
TMPDIR="${TMPDIR:-$(mktemp -d)}"
mkdir -p "$TMPDIR"
rm -rf "$TMPDIR/sweetclaude"

# Resolve the repo URL: prefer the source dir's remote, fall back to canonical GitHub URL.
REPO_URL=$(git -C "$SOURCE_DIR" config --get remote.origin.url 2>/dev/null || echo "https://github.com/carson-sweet/sweetclaude.git")

# Re-fetch source at the prerelease tag specifically (overrides Step 2a/2b result).
git clone --branch "$PRERELEASE_TAG" --depth 1 "$REPO_URL" "$TMPDIR/sweetclaude"
SOURCE_DIR="$TMPDIR/sweetclaude"
PRERELEASE_INSTALL=true
NEW_VERSION_LABEL="$PRERELEASE_TAG"
```

On **Wait for the final release**:
```bash
# Record the decline so this specific prerelease tag won't re-prompt every update.
# A newer prerelease tag (e.g. v4.0.0-beta2) will still prompt.
python3 -c "
import yaml, os, tempfile
p = '.sweetclaude/state/sweetclaude.yaml'
if os.path.exists(p):
    d = yaml.safe_load(open(p)) or {}
    d.setdefault('framework', {}).setdefault('update', {})['prerelease_declined'] = '$PRERELEASE_TAG'
    with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(p), suffix='.tmp', delete=False) as t:
        yaml.safe_dump(d, t, default_flow_style=False, sort_keys=False)
        tn = t.name
    os.replace(tn, p)
"
PRERELEASE_INSTALL=false
```

Set `PRERELEASE_INSTALL=false` if `SHOULD_PROMPT` was false (no prerelease available or already declined).

After Step 2c: continue to Step 3.

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
    git -C $SOURCE_DIR pull --ff-only origin "$EXPECTED_REF"
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
diff -rq $SOURCE_DIR/skills/ ~/.claude/skills/sweetclaude/ 2>/dev/null
diff -rq $SOURCE_DIR/rules/ ~/.claude/rules/sweetclaude/ 2>/dev/null
diff -rq $SOURCE_DIR/hooks/ "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/hooks/sweetclaude}/" 2>/dev/null
diff -rq $SOURCE_DIR/config/ ~/.claude/config/sweetclaude/ 2>/dev/null
diff -rq $SOURCE_DIR/agents/ ~/.claude/agents/sweetclaude/ 2>/dev/null
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

For each removed skill, check whether it owns live artifact content. Read `base_path` from session-state (`paths.product_base`) or fall back to `.sweetclaude/artifacts/product`.

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
for f in CLAUDE.md package.json LICENSE; do
  [ -f "$SOURCE_DIR/$f" ] && cp "$SOURCE_DIR/$f" {installPath}/
done

# Plugin manifest
rsync -a $SOURCE_DIR/.claude-plugin/ {installPath}/.claude-plugin/

# Skills → legacy install path (created by install.sh — must stay in sync)
if [ -d "$HOME/.claude/skills/sweetclaude" ]; then
  rsync -a --delete $SOURCE_DIR/skills/ ~/.claude/skills/sweetclaude/
fi

# Scripts → plugin cache AND versionless ~/.claude/scripts/sweetclaude/.
# The versionless path is what skills reference (no installPath lookup needed).
if [ -d "$SOURCE_DIR/scripts" ]; then
  rsync -a --delete $SOURCE_DIR/scripts/ {installPath}/scripts/
  mkdir -p ~/.claude/scripts/sweetclaude
  rsync -a --delete $SOURCE_DIR/scripts/ ~/.claude/scripts/sweetclaude/
fi

# Framework dirs → ~/.claude/
rsync -a --delete $SOURCE_DIR/rules/ ~/.claude/rules/sweetclaude/
rsync -a --delete $SOURCE_DIR/hooks/ "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/hooks/sweetclaude}/"
rsync -a --delete $SOURCE_DIR/config/ ~/.claude/config/sweetclaude/
rsync -a --delete $SOURCE_DIR/agents/ ~/.claude/agents/sweetclaude/

# Ensure hooks are executable
chmod +x "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/hooks/sweetclaude}/"*.sh 2>/dev/null || true

# Verify registry file synced correctly
ls ~/.claude/config/sweetclaude/skills-registry.yaml 2>/dev/null || echo "WARNING: skills-registry.yaml not found after sync"

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
  rsync -a $SOURCE_DIR/.claude-plugin/ "$VERSION_DIR/.claude-plugin/"
  for f in CLAUDE.md package.json LICENSE; do
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
if ! python3 ~/.claude/scripts/sweetclaude/maintenance/ensure-global-hooks.py >"$HOOK_RECONCILE_LOG" 2>&1; then
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
SYNC_TARGET="$installPath"
python3 ~/.claude/scripts/sweetclaude/maintenance/plugin-state.py   --project-dir .   repair   --plugin-key "$PLUGIN_KEY"   --install-path "$SYNC_TARGET"   --version "$NEW_VER"   --sha "$NEW_SHA"
```

This repairs stale existing-user metadata: `lastUpdated`, `gitCommitSha`,
`version`, and `installPath` all move to the just-synced channel version.


---

## Step 6: Clean up

If a temp directory was used, remove it:
```bash
rm -rf "$TMPDIR"
```

Run a final diff to confirm sync:
```bash
SYNC_TARGET="${SYNC_TARGET:-$installPath}"
diff -rq $SOURCE_DIR/skills/ "$SYNC_TARGET/skills/" 2>/dev/null
diff -rq $SOURCE_DIR/skills/ ~/.claude/skills/sweetclaude/ 2>/dev/null
diff -rq $SOURCE_DIR/scripts/ "$SYNC_TARGET/scripts/" 2>/dev/null
```

Continue to Step 6b. The user-facing success report is deferred until Step 6b confirms project state is coherent — reporting "updated" before the drift verdict is what caused BUG-002.

---

## Step 6b: Project-state drift detection

Update does not run
project-state migrations inline. Framework sync and project-state mutation are deliberately decoupled: update may report drift, but the owning doctor/recovery flow decides what to do next.

Only run this scan if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory. Update can be run from any directory.

```bash
DRIFT_COUNT=0
if [ -f .sweetclaude/state/sweetclaude.yaml ] && [ -n "$RUNNER" ] && [ -f "$RUNNER" ]; then
  DRIFT_JSON=$(python3 "$RUNNER" --project-dir . --scan-drift --persist 2>/dev/null || echo '[]')
  DRIFT_COUNT=$(printf '%s
' "$DRIFT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); xs=d if isinstance(d,list) else d.get('findings',[]); print(sum(1 for x in xs if x.get('needs_migration')))" 2>/dev/null || echo 0)
fi
echo "DRIFT_COUNT=$DRIFT_COUNT"
```

If `DRIFT_COUNT` is 0, print the success report with `✓ Project: clean`.

If `DRIFT_COUNT` is greater than 0, print:

```
SweetClaude framework files were updated.
Project-state migration is not run inline.
No project files were changed by update.
Run /sweetclaude:doctor for the maintenance route.
```

Do not write `doctor-prompt-pending.json` from update. Do not execute its project skill-state migration from update.

## Step 6b1: Orphan file scan

Only run if `.sweetclaude/state/sweetclaude.yaml` exists in the current project directory — skip silently otherwise.

Scan for work item files that may have been lost, abandoned, or orphaned from previous SweetClaude versions — files in typed subdirectories (retired in 4.1.0), scratch/, or other locations the primary migration wouldn't find. Recovering them here means Step 6b2's taxonomy scan picks them up automatically.

```bash
ORPHAN_COUNT=0
MIGRATE_SCRIPT=~/.claude/scripts/sweetclaude/migrate/migrate-v3-to-v4.py
if [ ! -f "$MIGRATE_SCRIPT" ]; then
  MIGRATE_SCRIPT=$(find ~/.claude/plugins/cache/sweetclaude -type f -name 'migrate-v3-to-v4.py' 2>/dev/null | head -1)
fi
if [ -f .sweetclaude/state/sweetclaude.yaml ] && [ -n "$MIGRATE_SCRIPT" ] && [ -f "$MIGRATE_SCRIPT" ]; then
  ORPHAN_OUT=$(python3 "$MIGRATE_SCRIPT" scan-orphans --project-dir . 2>/dev/null)
  ORPHAN_COUNT=$(echo "$ORPHAN_OUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('orphan_count', 0))" 2>/dev/null || echo 0)
fi
echo "ORPHAN_COUNT=$ORPHAN_COUNT"
```

If `ORPHAN_COUNT` is 0: continue silently to Step 6b2.

If `ORPHAN_COUNT > 0`: present findings grouped by category:

```
Found {N} orphaned work item files outside the primary backlog:

Typed subdirectories (retired in 4.1.0):
  {file} — {id} — {title} [{status}]

Scratch directory:
  {file} — {id} — {title} [{status}]

Stray files:
  {file} — {id} — {title} [{status}]
```

Do not move, copy, delete, or normalize these files from `sweetclaude:update`.
Report them as a follow-up diagnostic only:

```
Found {N} orphaned work item file(s) outside the primary backlog.

No files were changed. Taxonomy/orphan recovery is disabled in this beta
hotfix because the current migrator does not safely support every v4 project
layout. Continue using the project as-is; run `sweetclaude:doctor` for a
read-only diagnostic report.
```

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

Then continue to Step 6c. Do not write `doctor-prompt-pending.json`.

---

## Step 6c: Success report (only reached when project state is verified clean)

```
SweetClaude updated.
═══════════════════

✓ Version:    {old_version} → {new_version}  (or same if unchanged)
✓ Commit:     {old_sha_short} → {new_sha_short}
✓ Files:      {total count} synced across skills, rules, hooks, config, agents
✓ Hooks:      {only include this line if Step 4b reported cleaned: entries}
✓ Project:    {clean | clean (verified post-migrate)}

→ Restart Claude Code to use this update — skills are loaded at session start
  and are not updated in the current session.
```

The `✓ Project:` line wording depends on which Step 6b exit path was taken:
- DRIFT_COUNT=0 on first check → `clean`
- _migrate ran and POST_MIGRATE_COUNT=0 → `clean (verified post-migrate)`

Print exactly one of those two; do not print the literal text `clean OR clean (verified post-migrate)`.

If `NEW_SKILLS` (from Step 4) is non-empty, append this block after the success report — one line per new skill:

```
New skills added (not available until restart):
  {list each name from NEW_SKILLS, one per line, prefixed with /sweetclaude:}
```

Do not mention any `/sweetclaude:` command as something the user can run now. Do not ask "Want to run it?" or offer to invoke any skill. The current session does not have the updated skill set.

Do not write `doctor-prompt-pending.json` from update. No project files were changed by update. Continue to Step 7.

---

## Step 7: Surface capabilities

Read [capability-surface.md](capability-surface.md) and execute it in full.


---

## Step 7b: Feature configuration check

Skip feature configuration from update. Feature setup is project mutation and belongs to doctor/setup, not framework update.

## Step 7c: Configure plan directory

Skip plan-directory configuration from update. Plan directory repair is project mutation and belongs to doctor/setup, not framework update.

## Step 8: Project-state migration is not run inline

Project-state migration is not run inline by update. The framework may be synced while the current project still has drift; the success report must say so and point to `/sweetclaude:doctor`.

Disabled from update:
- project-state migration commands
- purge or re-onboarding commands
- plan-directory configuration
- feature configuration

---

## Rules

- **Always show the diff preview and wait for confirmation before syncing.**
- **Use rsync --delete.** Removed files in the source should be removed from installed locations.
- **Prefer `gh` over `git` for cloning.** It handles private repo auth transparently.
- **Never ask for tokens or credentials.** If auth fails, tell the user to run `gh auth login`.
- **Always clean up temp directories**, even on failure.
- **Do not touch ~/.claude/settings.json.** Hook wiring is handled by install.sh.
- **Do not modify ~/CLAUDE.md.** Also handled by install.sh.
- **This does not affect per-project .sweetclaude/ directories.** Only the global framework.
