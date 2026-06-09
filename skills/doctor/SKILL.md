---
spdx-license: AGPL-3.0-or-later
user-invocable: true
description: "Diagnostic scan, repair, and rollback. Checks 8 categories (state integrity, hooks, storage, migration, config, files, onboarding, environment), fixes what it safely can, and can restore (roll back / undo / revert) the files a previous doctor run changed."
---


!`cat .sweetclaude/state/session-state.yaml`

<preflight-guard>
STOP. Before executing this skill, check: if pre-loaded state above shows STATE_NOT_FOUND, or neither .sweetclaude/state/sweetclaude.yaml nor .sweetclaude/state/phase.yaml exists, do not proceed. Instead say: "This project is not configured for SweetClaude. Running pre-flight check." Then invoke the sweetclaude master skill (Skill tool, skill: "sweetclaude:master") and run its pre-flight. Return here only after the pre-flight passes.
</preflight-guard>

# SweetClaude Doctor

Diagnostic scan and repair for your SweetClaude project. Checks 8 categories, offers fixes, and keeps a backup of everything it touches.

Thin orchestrator — all scanning and file mutation happens in `scripts/doctor.py`. This skill owns rendering, menus, prompted fixes, and user interaction. All file writes go through the script's `execute_recipe` pipeline to guarantee backup and diff recording.

---

## Step 0: Plugin Update Guard

Before any Doctor scan or maintenance routing, run the SweetClaude preflight
helper to detect stale beta plugin installs:

```bash
if [ -f ~/.claude/scripts/sweetclaude/preflight.sh ]; then
  eval "$(bash ~/.claude/scripts/sweetclaude/preflight.sh . 2>/dev/null)"
fi
```

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

## Step 0b: Roll back a prior run when requested

If the user is explicitly asking to undo, roll back, or revert a previous doctor run
(e.g. "roll back the doctor changes", "undo that doctor run"), handle it HERE and skip
the diagnostic scan. This restores files from a run's archived `before/` images through
the executor — the rollback counterpart to the safety branch, and the path for changes
outside the project git tree (e.g. `~/.claude` files) that a safety branch can't cover.

1. Pick the run archive. Default to the most recent; if the user names a specific run, use
   that instead:

   ```bash
   ls -1d .sweetclaude/state/doctor-runs/*/ 2>/dev/null | sort | tail -1
   ```

   If none exist, tell the user there is no doctor run to roll back, and stop.

2. Show what that run changed — list the affected files from its manifest:

   ```bash
   python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print('\n'.join(sorted({a.get('file_path','') for a in m.get('actions',[]) if a.get('file_path')})) or '(no file mutations recorded)')" {run_dir}/manifest.json
   ```

3. Restore writes files back over the live ones, so require explicit approval. Present via
   AskUserQuestion:
   - **Roll back the whole run (Recommended)** — restore every file this run changed
   - **Roll back specific files** — choose which files to restore
   - **Cancel** — leave everything as-is

4. Invoke restore (whole run, or once per chosen file with `--file {path}` instead of `--all`):

   ```bash
   python3 ~/.claude/scripts/sweetclaude/doctor.py restore --project-dir . --archive-dir {run_dir} --all
   ```

5. Report the result. `restored` lists the files reverted byte-for-byte; `skipped` lists any
   with no archived before-image (`reversible:false` — e.g. cache/derived rebuilds). Tell the
   user any skipped files were not archive-reversible, and if that run created a git safety
   branch, point to it as the fallback. Stop after rollback unless the user asks for more.

## Step 1a: Maintenance route preflight

Run the compact maintenance route before the full scan. This is intentionally
separate from the full scan because large projects can produce huge finding
lists, and the user-facing maintenance decision must not get buried.

```bash
python3 ~/.claude/scripts/sweetclaude/doctor.py maintenance-route --project-dir . 2>/dev/null
```

Parse the JSON output. Handle these cases:

**Not configured:** If the output contains `"error": "not-configured"`, print:
> SweetClaude is not configured for this project.

Stop. Do not continue to Step 2.

**Parse failure:** If the output is not valid JSON or the command exits
non-zero, print:
> Doctor route check failed. Run `python3 ~/.claude/scripts/sweetclaude/doctor.py maintenance-route --project-dir .` manually to see the error.

Stop.

**Success:** Store `maintenance_route`. Doctor is the maintenance front door;
do not make the user choose among internal commands such as `recover`,
`_migrate`, or taxonomy migration scripts.

If `maintenance_route.status` is `recovery-available`, present
**AskUserQuestion** before running the full scan:

> Doctor found a recoverable SweetClaude maintenance state. Recovery will
> diagnose, plan, snapshot, request approval, verify, and keep rollback data.

Options:
- **Run safe recovery** — "Use the snapshot-backed recovery flow"
- **Continue without maintenance** — "Skip recovery for now and continue to non-migration fixes"

On **Run safe recovery**: invoke `sweetclaude:recover`. Recovery owns the
diagnose, plan, approval, execute, resume, verification, and rollback flow. When
it completes, run the full scan and continue with the fresh findings.

If `maintenance_route.status` is `supported-migration-available`, present
**AskUserQuestion** before running the full scan:

> Doctor found a supported flat BL-NNN migration candidate. Migration will run
> its own preflight and safety steps before conversion.

Options:
- **Start supported migration** — "Open the migration flow for this supported layout"
- **Continue without migration** — "Skip migration for now and continue to other fixes"

On **Start supported migration**: invoke `sweetclaude:migrate`. Do not invoke
`migrate_taxonomy.py` or any migration script directly from Doctor. After the
migration flow completes, run the full scan and continue with fresh findings.

If `maintenance_route.status` is `compatibility-mode`, print a visible
maintenance route block before the full scan:

> Maintenance route: {message}
> No migration is recommended for this project.

Then continue to Step 1b.

If `maintenance_route.status` is `migration-blocked`, `manual-review`, or
`no-maintenance-action`, print the route `message` when it is non-empty, then
continue to Step 1b. Do not invoke any migration script.

---

## Step 1b: Scan

```bash
python3 ~/.claude/scripts/sweetclaude/doctor.py scan --project-dir . 2>/dev/null
```

Parse the JSON output. Handle these cases:

**Not configured:** If the output contains `"error": "not-configured"`, print:
> SweetClaude is not configured for this project.

Stop. Do not continue to Step 2.

**Parse failure:** If the output is not valid JSON or the command exits non-zero, print:
> Doctor scan failed. Run `python3 ~/.claude/scripts/sweetclaude/doctor.py scan --project-dir .` manually to see the error.

Stop.

**Success:** Store the parsed result. Extract `findings`,
`skipped_categories`, `suppressions_resolved`, `compatibility_adjustments`, and
`project_state_summary`.
Keep using the `maintenance_route` from Step 1a. Use the full scan's
`maintenance_route` only as a fallback if Step 1a did not return one. Count
findings by severity (error/warning/info) for the summary line in Step 9.

---

## Step 2: Render report

**Zero findings:** If `findings` is empty:

Check if `.sweetclaude/state/last-doctor-run.json` exists.
- First run (file missing): print "This is your first checkup — doctor scans your project for common issues and offers to fix them." then "All clear."
- Subsequent run: print "All clear."

Skip to Step 9 (persist the clean run).

**Findings present:** Render the report.

If `compatibility_adjustments.applied` is true and
`compatibility_adjustments.collapsed_count` is greater than 0, print this before
the severity groups:

> Compatibility mode collapsed {collapsed_count} accepted legacy taxonomy
> findings. These are not recommended fixes while compatibility mode is active.

### Summary tier (default)

Group findings by severity. For each group, print a header with icon and the findings:

```
### ❌ Errors (N)
- {summary}
- {summary}

### ⚠️ Warnings (N)
- {summary}

### ℹ️ Info (N)
- {summary}
```

Use the `summary` field from each finding (plain English, no paths or codes).

### Detail tier (--verbose)

If the user invoked doctor with `--verbose` or asked for details, render the detail tier instead:

```
### ❌ Errors (N)
- {detail}
  Files: {file_paths joined by ", "}
  Fix: {fix_type}

### ⚠️ Warnings (N)
- {detail}
  Files: {file_paths joined by ", "}
  Fix: {fix_type}
```

### Skipped categories

If `skipped_categories` is non-empty:
> Skipped {N} check categories due to missing dependencies:
> - {category}: {reason}

### Resolved suppressions

If `suppressions_resolved` is non-empty, list each one:
> Previously suppressed findings resolved:
> - {finding_id_1}
> - {finding_id_2}

---

## Step 2b: Maintenance router guard

Step 1 must already have handled and visibly rendered the maintenance route
before the full findings report. Do not present a second maintenance prompt
here. If Step 1 did not return a route but the full scan did, handle that route
now using the same rules from Step 1a before continuing to Step 3.

`migration_recommendations` is legacy diagnostic context. Do not use it to
present a migration prompt unless `maintenance_route.status` is
`supported-migration-available`.

---

## Step 3: Pre-fix menu

If no findings have `fix_type` of `auto` or `prompted`, skip to Step 8.

Check for a stored menu default. Do not `cat` or print
`.sweetclaude/state/last-doctor-run.json`; older runs can contain large stale
finding lists. Read only the compact preference fields:

```bash
python3 -c "import json, os; p='.sweetclaude/state/last-doctor-run.json'; d=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps({'exists': bool(d), 'menu_default': d.get('menu_default'), 'menu_preference': d.get('menu_preference')}))" 2>/dev/null || echo '{"exists": false}'
```

Use `menu_default` for skip-menu behavior. `menu_preference` is only the last
one-time choice and must not skip the menu by itself. If the user passed
`--interactive`, ignore stored preferences.

If a stored default of `proceed` exists and `--interactive` was not passed, skip the menu — print "Using stored preference: proceed" and go to Step 4.

Otherwise, present the menu via AskUserQuestion:

Options:
1. **Explain what I'll do** — "Show a numbered list describing each planned change"
2. **Show me a dry run** — "Simulate the fixes and show before/after diffs without changing anything"
3. **Proceed** — "Apply fixes (you'll be asked about each prompted fix)"
4. **No fixes needed** — "Skip all fixes and just record the scan results"

### Explain

If the user picks Explain:

Number each finding that has a fix (auto or prompted). For each:
> {N}. {summary} → {fix_type} fix

After the list, the user can ask about a specific number for detail (show `detail` field and `file_paths`). Then re-present the Step 3 menu.

### Dry run

If the user picks dry run:

```bash
echo '{scan_findings_json}' | python3 ~/.claude/scripts/sweetclaude/doctor.py dry-run --project-dir .
```

Parse the `simulations` array. For each:
- If it has `before` and `after`: show a before/after comparison
- If it has `note`: show the note
- If it has `description`: show the description

After rendering, re-present the Step 3 menu.

### Proceed

Continue to Step 4.

### No fixes needed

Skip to Step 8 (suppression offer). No safety branch, no archive, no fixes.

### Remember-last-choice

Track consecutive identical menu choices. After this run completes, the choice is saved via the `--menu-preference` arg to `persist`.

If the user has now picked the same option 3 consecutive runs (check previous `last-doctor-run.json` files), offer via AskUserQuestion:
> "You've chosen {choice} the last 3 times — want me to skip this menu from now on? (You can always override with `--interactive`.)"

Options: Yes, skip the menu / No, keep asking

If yes, the persist step will store `menu_default` in addition to `menu_preference`.

---

## Step 4: Safety branch offer

**Always present this step.** Never skip it due to stored preferences.

First check prerequisites:

```bash
git rev-parse --is-inside-work-tree 2>/dev/null
```

If not a git repo: print "Not a git repository — skipping safety branch." Continue to Step 5.

```bash
git status --porcelain 2>/dev/null
```

If dirty working tree: warn "You have uncommitted changes — the safety branch will include them."

Present via AskUserQuestion:
- **Yes, create a safety branch (Recommended)** — "Create doctor/run-{timestamp} from current HEAD as a restore point"
- **No, proceed on current branch** — "Make changes directly on the current branch"

If yes:

```bash
git branch doctor/run-{timestamp}
```

This creates the branch as a restore point WITHOUT switching to it. If the branch name already exists, append `-2`, `-3`, etc. Record the branch name — pass it to `persist` via `--safety-branch`.

If no: record that the user declined (pass `--safety-branch ""` to persist, or omit the arg).

---

## Step 5: Create archive and run auto-fixes

```bash
python3 ~/.claude/scripts/sweetclaude/doctor.py create-archive --project-dir .
```

Store the `archive_dir` from the response.

Then pipe the scan findings to auto-fix:

```bash
echo '{scan_findings_json}' | python3 ~/.claude/scripts/sweetclaude/doctor.py auto-fix --project-dir . --archive-dir {archive_dir}
```

Parse the result. Report:

**Successes:**
> Fixed {N} items automatically:
> - {description}

**Failures:**
> Failed to fix {N} items:
> - {description}: {error}

If no auto-fixable findings existed, skip this output.

### Post-fix rescan

If `post_fix_categories` is non-empty:

```bash
echo '{scan_findings_json}' | python3 ~/.claude/scripts/sweetclaude/doctor.py post-fix-rescan --project-dir . --categories {comma_separated_categories}
```

If the rescan returns new findings:
> ### Post-fix findings
> A fix revealed a previously hidden issue:
> - {summary}

### Refresh prompted findings

After auto-fix and post-fix rescan, filter the prompted-fix findings list: drop any finding whose ID no longer appears in a fresh scan of its category (it was resolved by an auto-fix). Use the post-fix rescan results for this — if a prompted finding's ID is absent from the rescan of its category, remove it from the prompted list.

---

## Step 6: Prompted fixes

Group prompted-fix findings by category. Process each category:

### Batch presentation

If a category has multiple findings of the same `fix_recipe.type`, batch them. Present via AskUserQuestion:

> {N} {description of batch} — for example: "3 files need moving to done/"

Options:
- **Fix all** — "Apply the fix to all {N} items"
- **Review each** — "Show me each item and let me decide individually"
- **Skip all** — "Skip all {N} items"

### Individual review

For each finding (or if user chose "Review each"):

Present the finding details and offer via AskUserQuestion:
- **Fix it** — description of what the fix does
- **Skip** — "Leave it as-is for now"
- **Suppress** — "Don't report this finding again"

**On Fix:**

Execute the fix through the script's backup pipeline. For fix types that have a concrete recipe action (not just `"prompt"`):

```bash
echo '[{single_finding_json}]' | python3 ~/.claude/scripts/sweetclaude/doctor.py auto-fix --project-dir . --archive-dir {archive_dir} --include-prompted
```

For fix types that require further user input or skill delegation:

- `choose_value`: Present `fix_recipe.options` for `fix_recipe.field` via AskUserQuestion. With the chosen value, apply through the executor by **reusing the `write_frontmatter_field` action** (do not write the file directly) — build a finding whose recipe is the executable write and pipe it to auto-fix:
  ```bash
  echo '[{"id": "{finding_id}", "category": "{category}", "summary": "{summary}", "fix_type": "prompted", "fix_recipe": {"action": "write_frontmatter_field", "file": "{fix_recipe.file}", "key": "{fix_recipe.field}", "value": "{chosen_value}"}}]' | python3 ~/.claude/scripts/sweetclaude/doctor.py auto-fix --project-dir . --archive-dir {archive_dir} --include-prompted
  ```
  This routes through the executor's backup/diff pipeline (reversible via `restore`). Then record the prompted-fix action.

- `provide_value`: Ask the user to supply a value for `fix_recipe.field` (open prompt). Apply identically by reusing `write_frontmatter_field` — same auto-fix invocation as `choose_value`, with the supplied value. Then record.

- `config_conflict`: Present the options from `fix_recipe.options` (**adopt** = use SweetClaude's rule, **keep** = keep your rule, **both** = keep both) via AskUserQuestion. Apply through the executor by building a finding whose recipe is the executable `config_conflict` action — carry the chosen `choice` plus the target the check already threaded into the prompt recipe (`path`, `conflict`, and `tool`/`hook_command`/`matcher` for settings F1-F3, or `pattern` for text F4/W1-W4/I1-I2). Do not write the file directly. Only `adopt` mutates (a targeted line/key edit through the backup pipeline, reversible via `restore`); `keep`/`both` are no-ops the executor records as success with no backup.
  ```bash
  echo '[{"id": "{finding_id}", "category": "config_compat", "summary": "{summary}", "fix_type": "prompted", "fix_recipe": {"action": "config_conflict", "file": "{fix_recipe.file}", "path": "{fix_recipe.path}", "choice": "{chosen_choice}", "conflict": "{fix_recipe.conflict}", "tool": "{fix_recipe.tool}", "hook_command": "{fix_recipe.hook_command}", "matcher": "{fix_recipe.matcher}", "pattern": "{fix_recipe.pattern}"}}]' | python3 ~/.claude/scripts/sweetclaude/doctor.py auto-fix --project-dir . --archive-dir {archive_dir} --include-prompted
  ```
  Include only the target fields present on the prompt recipe (settings conflicts carry `tool` or `hook_command`/`matcher`; text conflicts carry `pattern`). Then record the prompted-fix action.

- `hook_restore`: Present source options (backup vs repo) via AskUserQuestion. Restore the file, record the action.

- `migration`: Delegate to the appropriate skill or script per Step 7. Record the result.

- `yaml_repair`: Present options (auto-fix syntax, show file for manual edit, restore from archive) via AskUserQuestion. Apply, record.

- `bootstrap`: Run the bootstrap script via the auto-fix pipeline with `--include-prompted`, record.

**On Skip:**
```bash
echo '{"finding_id": "...", "action": "skip", "timestamp": "..."}' | python3 ~/.claude/scripts/sweetclaude/doctor.py record-action --archive-dir {archive_dir}
```

**On Suppress:**

Ask for a reason string. Write the suppression:

```python
# Add to doctor-suppressions.json
{"finding_id": "...", "suppressed_at": "{ISO timestamp}", "reason": "{user's reason}"}
```

Record the action:
```bash
echo '{"finding_id": "...", "action": "suppress", "reason": "...", "timestamp": "..."}' | python3 ~/.claude/scripts/sweetclaude/doctor.py record-action --archive-dir {archive_dir}
```

---

## Step 7: Migration and restore delegation

When a prompted fix involves migration or restoration:

- **Schema migration** (`fix_recipe.script` = "runner.py"): Invoke `sweetclaude:_migrate` skill. Record result via `record-action`.

- **Taxonomy migration** (`fix_recipe.script` = "migrate_taxonomy.py"): Block in this beta unless a future taxonomy
  migration capability check proves the detected layout is supported. Do not
  run this script directly from doctor. Record the blocked action and route the
  user to `/sweetclaude:recover` or manual review based on the recovery guard.

- **v3-to-v4 migration** (`fix_recipe.script` = "migrate-v3-to-v4.py"): Invoke `sweetclaude:migrate`, which runs its
  read-only preflight before creating locks, backups, files, or migration maps.
  Record result.

- **Purge/re-onboard**: Invoke `sweetclaude:purge`. Record result.

---

## Step 8: Suppression offer

After all fixes are processed (or if there were no fixes, or the user chose "No fixes needed"), if there are remaining unfixed findings:

> Want to suppress any of the remaining findings so they don't show up next time?

Present via AskUserQuestion:
- **Yes, let me choose** — "Review remaining findings and choose which to suppress"
- **No** — "Keep reporting everything"

If yes: present each remaining finding with suppress/keep options (same as Step 6 suppress flow).

For findings where `previously_suppressed` is true, note: "This finding was previously suppressed, resolved, and has now re-emerged."

---

## Step 9: Persist and summary

If no archive was created (zero-findings or "No fixes needed" path), create one for the persist record:

```bash
python3 ~/.claude/scripts/sweetclaude/doctor.py create-archive --project-dir .
```

Pipe the original scan findings to persist:

```bash
echo '{scan_findings_json}' | python3 ~/.claude/scripts/sweetclaude/doctor.py persist --project-dir . --archive-dir {archive_dir} --menu-preference {choice_from_step_3} --safety-branch {branch_name_or_empty}
```

Count severities from the findings array: errors = findings where severity="error", warnings = severity="warning", info = severity="info". Get fix counts from the archive actions (auto_fixed, user_fixed, skipped).

Render the summary line:

> **{errors} errors, {warnings} warnings, {info} info. {auto_fixed} auto-fixed, {user_fixed} user-fixed, {skipped} skipped.**

Report the archive location (unconditional — always show if an archive exists):
> Run details saved to `.sweetclaude/state/doctor-runs/{timestamp}/`

If the run changed any files (`auto_fixed + user_fixed > 0`), tell the user it is reversible:
> These changes are backed up and reversible. To undo this run, say "roll back the doctor
> changes" (or run `/sweetclaude:doctor` and ask to roll back).

If a git safety branch was created this run, add: ` The git safety branch \`{branch_name}\` is also available.`

Prune old archives:

```bash
python3 ~/.claude/scripts/sweetclaude/doctor.py prune-archives --project-dir .
```

Silent — do not report pruning results to the user.

---

## Rules

- **Read-only scan.** The scan phase (Step 1) never writes. All writes happen in Steps 5-7.
- **All mutations go through the script.** Even prompted fixes use `auto-fix --include-prompted` or `record-action`. The skill never writes files directly via Bash — this guarantees backup and diff recording per FR-2.4.
- **Archive is unconditional.** Every run creates an archive, regardless of whether changes were made.
- **Safety branch is always offered.** Never skip it due to stored preferences or menu defaults. Never subject it to remember-last-choice. Uses `git branch` (not `checkout -b`) to avoid switching context.
- **Skip is always available.** Doctor never blocks on a single finding. The user can skip any prompted fix, skip all fixes, or exit the menu entirely.
- **No deletions without backup.** Enforced by `scripts/doctor.py`'s `execute_recipe`, not by this skill.
- **Prompted fixes are batched where possible.** Multiple findings of the same type in the same category are presented as a group.
- **Summary tier is default.** Use plain English summaries with severity icons unless the user asks for `--verbose` detail.
- **Use AskUserQuestion for all bounded decisions.** Pre-fix menu, safety branch, prompted fixes, suppression — all via AskUserQuestion, never text-imitation menus.
