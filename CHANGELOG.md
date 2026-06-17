# Changelog

All notable changes to SweetClaude are documented here. SweetClaude has separate stable 3.x and 4.x beta channels, so this changelog calls out channel-specific changes explicitly.

---

## [4.2.11-beta] — 2026-06-17 (4.x beta channel)

### Fixed — a missing derived state snapshot bricked nearly every skill on load

`session-state.yaml` is a per-session *derived* snapshot, not a tracked file.
Since ec771ea (ISSUE-193), 85 skills loaded it with a bare
`!`cat .sweetclaude/state/session-state.yaml`` bang preamble, assuming the
SessionStart preflight always regenerated it first. Whenever the snapshot was
absent — preflight hadn't run this session, an update/doctor run regenerated
state mid-session, a worktree with a different working directory, a fresh
checkout — the bare `cat` exited non-zero and the skill aborted on load with
`cat: .sweetclaude/state/session-state.yaml: No such file or directory`.
`/sweetclaude:go` and the rest of the skill surface became unusable.

All 86 bang-preamble state loaders (85 × session-state, plus orchestrator's
sweetclaude.yaml) now route through `hooks/read-state.sh`, invoked via
`${CLAUDE_SKILL_DIR}/../../hooks/` so it resolves on fresh installs regardless
of working directory. The wrapper emits file contents when present and a
`STATE_NOT_FOUND` sentinel (which skills already handle) when absent, always
exiting 0 — a missing snapshot can no longer abort skill load.

---

## [4.2.10-beta] — 2026-06-16 (4.x beta channel)

### Fixed — typed-legacy backlog projects could never leave compatibility mode

A project whose product tree used typed backlog folders (`backlog/stories/`,
`backlog/debt/`, …) with legacy work-item prefixes (`STORY-`, `DEBT-`, `BL-`, …)
was classified `typed_legacy_backlog` and parked in compatibility mode
permanently. The migrator for that layout was `supported: false`, graduation
required zero legacy prefixes (impossible for the shape), and recovery only
re-stabilized — so `update`, `doctor`, `migrate`, and `recover` could never get
the project out. Running them again did nothing, because the framework was built
to park it. This release builds and wires the missing migrator end to end.

- **A real typed-legacy → unified `ISSUE-NNN` migrator.** `migrate_taxonomy`
  recognizes typed backlog dirs (including nested `done/` subdirs), top-level
  legacy-prefix files, spike reports, and the bespoke `stories/EPIC-NNN/` and
  `stories/BL-NNN/` user-story trees. It produces a reviewable dry-run plan
  (global ISSUE renumbering, `EP-NNN` epics, `migrated_from`, a `MIGRATION-MAP`,
  and reference rewrites), then executes behind a snapshot with byte-for-byte
  rollback and auto-rollback on failure.
- **The guard now offers the migrator.** `migrate.typed_legacy_backlog` is
  supported; the recovery guard, doctor maintenance route, and bootstrap route a
  typed-legacy project to `supported-migration-available` instead of a no-action
  compatibility mode. Projects with real (non-backup) duplicate IDs are routed
  to a resolvable step, not a wall.
- **No project shape is a dead end** — a test now asserts every guard status
  routes to an offered action.

Bugs found and fixed while validating against a real corpus:

- The migrator crashed when run as a CLI (`No module named 'recovery'`) — i.e.
  exactly how `sweetclaude:migrate` invokes it; the test suite had masked it.
- Migration left items behind: nested `backlog/stories/done/` and
  `stories/BL-NNN/` story dirs weren't scanned, so the project stayed
  typed-legacy after "migrating."
- Versioned draft documents (`BL-005-product-brief-draft-v1.0-….md`) were
  miscounted as work items, leaving the project reading as `flat_bl_backlog` and
  faking duplicate-ID blockers.
- Tool backups (`*.bold-backup-*`) were counted as duplicate IDs and used to
  justify refusing migration.
- Recovery forbade the now-safe migration: the stabilize postcondition required
  doctor to recommend no migration; it now fails only on unsupported migration.
- Interrupted (`incomplete`) migrations got stuck in recovery; stabilize now
  normalizes `incomplete → deferred` so recover-then-migrate completes.

### Fixed — dashboard detail-panel dates now show their timezone

Detail-panel date fields rendered as `2026-05-21 00:00:00.000Z` because an
over-escaped regex in `fmtDate` was emitted literally into the page JS and never
matched. They now read `2026-05-21 00:00:00 UTC`.

---

## [4.2.9-beta] — 2026-06-10 (4.x beta channel)

### Fixed — missing skills.yaml was still a dead end (and said something scary)

The 4.2.8 totality audit misclassified one finding as cosmetic, and a user
hit it within hours: after updating, doctor reported **"Skills configuration
hasn't been set up yet"** — wording that reads as if plugin skills are
broken, with guidance pointing at a bootstrap path that never creates the
file. Plugin skills were always fine: `.sweetclaude/state/skills.yaml` is
the optional-feature onboarding ledger (parking lot, milestones, usage
tracking activation state), not the skill registry, and every feature skill
tolerates its absence.

- **New generator:** `scripts/maintenance/generate-skills-state.py` creates
  the v2 stub that init normally writes. Idempotent — an existing file is
  never touched; uninitialized projects (no state directory) are refused
  with a pointer to `/sweetclaude:init`.
- **The finding now auto-fixes.** `onboarding-state:missing:skills.yaml`
  runs the generator through doctor's executor — archived, backed up,
  reversible via `doctor restore` — instead of being report-only with
  guidance that led nowhere.
- **Honest wording.** Summary is now "Optional-feature state file is missing
  (skills all work; this ledger only tracks feature onboarding)."
- **End-to-end test** locks the contract: scan → auto-fix → file created
  with `schema_version: 2` → rescan clears the finding.

Process note, recorded in the totality matrix: a finding every user sees
with no working resolution path is never "cosmetic" — this one is now in the
test corpus so the class stays closed.

---

## [4.2.8-beta] — 2026-06-10 (4.x beta channel)

### Fixed — maintenance dead ends closed end-to-end

This release closes the class of bug where Doctor, Update, Recover, and
Bootstrap detected maintenance issues but never connected the user to a
resolution — the "Doctor says run Recover, Recover says nothing to do" loop.
Every fix was driven by failing end-to-end tests derived from three real
projects, and acceptance was verified by those projects' session starts
coming up clean, not by the unit suite alone.

- **Guard names graduation blockers.** New `graduation-blocked` guard status:
  when a compatibility-mode project fails graduation validation on fixable
  blockers only (duplicate IDs, legacy type aliases, missing fields,
  frontmatter parse errors), the guard lists each blocker with its resolution
  instead of collapsing everything into the generic compatibility-mode
  message. Structural blockers (old taxonomy prefixes, non-standard layout)
  keep the project honestly in compatibility mode — those genuinely require a
  layout-specific migration plan.
- **`resolve-graduation-blocker` CLI** (recover_project.py): resolves
  duplicate-ID blockers through Doctor's executor — archived, backed up,
  reversible via `doctor restore`. It distinguishes *misnamed files* (the
  filename id and frontmatter id disagree → rename the file to match its
  frontmatter) from *true duplicates* (two files share a frontmatter id →
  renumber the non-canonical copy). Renumbering a misnamed file would have
  clobbered a valid id other artifacts reference.
- **The no-op compatibility exit is gone.** Doctor's
  `exit_compatibility_mode` prompt wrote a flag the guard never read for
  status, so "exiting" changed nothing and the prompt re-offered itself every
  scan, forever. Graduation is now the single exit from compatibility mode.
- **Cross-location duplicate findings carry their fix.**
  `storage-lint:cross-location-duplicate-id` supersedes the file-diagnostics
  duplicate finding in scan dedup but was report-only with an empty recipe —
  the dedup kept the dead end and dropped the resolution. It now carries the
  full renumber recipe.
- **Bootstrap routes every guard status.** Step 5b is now a two-mode
  maintenance guard. The v3 hard-stop is unchanged; a new *advisory* mode
  runs the guard at session start for v4 projects in compatibility/recovery
  states — previously the guard never ran for them, so graduation
  opportunities were invisible. Advisory mode also triggers when legacy
  taxonomy files (`STORY-`/`BUG-`/`DEBT-`/`CHORE-`) exist despite state
  claiming migration complete. Every status maps to an action or an honest
  explanation; migrate is never recommended except for
  `migration-may-be-needed`.
- **Recover acknowledges schema drift.** `diagnose` now reports a
  `state-schema-drift` failure class (informational — it never flips the
  recovery route) instead of answering "no recovery needed" while state files
  sit behind the registry schema. The next-step text names the drifted files
  and points at the migration runner path that actually fixes them.
- **Update's referral circle closed.** The PARTIAL-update halt told users to
  run Doctor "or Recover" for drift; Recover correctly reports drift as
  informational-only, so that referral looped. The halt now routes to Doctor
  alone, which auto-fixes drift through the migration runner.

### Added — dead-end totality test corpus

- `tests/test_dead_end_totality.py`: 14 end-to-end tests locking the
  detection-to-resolution contracts, built from the observed states of three
  real projects (graduation-blocked with a hidden blocker, recovery-required
  with legacy artifacts, healthy control). Includes a totality lint: every
  guard status the capability manifest can emit must be handled in the
  bootstrap skill.
- Totality matrix audit: all 59 Doctor finding constructors classified
  (auto/prompted findings all carry executable archived recipes; every
  report-only finding verified as policy block, broken-chain fallback,
  human-content, or owned by a reachable route).

---

## [4.2.7-beta] — 2026-06-10 (4.x beta channel)

### Fixed — doctor dead-end resolution paths

- **Schema drift auto-fix.** Doctor now auto-fixes v1→v2 schema drift via the
  migration runner instead of marking it report-only and sending the user in
  circles between `/sweetclaude:doctor`, `/sweetclaude:update`, and
  `/sweetclaude:recover` (none of which could actually fix it).
- **skills.yaml v1 schema auto-fix.** Skills file schema upgrades now route
  through the migration runner instead of referencing a non-existent bootstrap
  script that silently failed.
- **skills.yaml missing finding corrected.** Missing skills.yaml is now
  report-only with actionable guidance instead of offering a prompted fix that
  called the wrong script and silently did nothing.
- **Broken migration chains stay report-only.** Schema drift with broken
  migration chains (out-of-support-window) correctly falls back to report-only
  instead of offering an auto-fix that would fail.
- **`runner.py` added to executor allowlist.** The migration runner can now
  execute through Doctor's backup pipeline (before-image + diff, reversible
  via restore).

---

## [4.2.6-beta] — 2026-06-10 (4.x beta channel)

### Added — compatibility mode graduation

- **Compatibility mode graduation capability.** Projects stuck in compatibility
  mode (`stabilized-without-migration`) can now graduate when they are already
  v4-compliant. Doctor detects graduation candidates at the maintenance route
  prompt and offers a one-click exit — a state-only write to `sweetclaude.yaml`
  with one-file blast radius, fully reversible via Doctor's restore flow.
- **v4 compliance detection** in `characterize_project.py`: new `v4_compliance`
  output block reports old-prefix count, v4-prefix count, required-field coverage,
  canonical-type compliance, duplicate-ID status, and standard structure.
- **`graduation-check` and `graduate` CLI subcommands** on `recover_project.py`
  for read-only validation and state-only graduation execution.
- **`graduation_candidate` project shape** and `recover.graduate_from_compatibility`
  capability in the manifest, with full safety contract (diagnose → validate →
  snapshot → approve → execute → verify → rollback).
- **Doctor routes `graduation-available`** before falling through to
  `compatibility-mode`, so compliant projects see the exit rather than the dead end.
- **17 new tests** covering graduation-check happy path, blocker detection
  (old prefixes, duplicates, legacy types, parse errors), guard routing,
  doctor maintenance route, graduate execution, idempotency, and read-only
  guarantees.

---

## [4.2.5-beta] — 2026-06-10 (4.x beta channel)

### Fixed — doctor conformance, safety hardening

- **Doctor conformance remediation (P0–P5).** The `sweetclaude:doctor` subsystem
  now fully satisfies its PRD (verified 127/0/0 by an independent caucus): every
  Tier-2 prompted fix is wired end-to-end through the executor backup pipeline;
  the Tier-4 purge/re-onboard fallback is surfaced; detection gaps (missing hooks,
  legacy type aliases, schema drift) are closed; taxonomy drift routes to migrate;
  and a real `restore`/rollback path exists.
- **Scan is strictly read-only (P2/P4).** The suppression-ledger prune was moved
  out of the read-only scan into the execute phase and routed through the backup
  pipeline (before-image + diff, `restore`-reversible).
- **Path-containment guards.** `restore`, `file_move`, `renumber_duplicate`, and
  `run_script` now reject paths that escape the project tree or `~/.claude`,
  closing arbitrary-write/exec vectors via crafted recipes or archives.

### Added — release & test infrastructure

- **Tag-push release automation** (`.github/workflows/release.yml`): pushing a
  `v*` tag now publishes a GitHub release with CHANGELOG-sourced notes.
- **Test collection fix:** hyphenated `test-*.py` suites (~440 tests) are now
  collected and run; 7 pre-existing, unrelated failures are tracked via `xfail`.

---

## [4.2.4-beta] — 2026-06-08 (4.x beta channel)

### Added — small-story workflow

- **Small-story controller, hooks, skill, and routing** for lightweight,
  single-session work items (the small-story counterpart to the large-story flow).

---

## [4.2.3-beta] — 2026-06-08 (4.x beta channel)

### Added — unified artifact integrity system

- **Phases 1–2:** unified artifact integrity foundation.
- **Phase 3:** data-store consolidation — SQLite established as the single query store.
- **Phase 4:** skill-layer cleanup.
- **Phase 5:** project remediation and behavioral regression tests.

---

## [4.2.2-beta] — 2026-06-08 (4.x beta channel)

### Added — dashboard enhancements

- **Show/hide done issues:** "(+N done, not shown)" and "(+N more open)"
  text in roadmap epic nodes and the detail panel are now clickable links
  that reveal the full issue list inline. A "Hide done issues" / "Hide
  extra issues" link collapses them back.
- **Collapsible milestones:** Milestone rows in the Roadmap tab have a
  chevron toggle and are clickable to collapse/expand their epic tree.
  Expanded by default.

---

## [4.2.1-beta] — 2026-06-08 (4.x beta channel)

### Fixed — epic completion criteria format

- **cache.py:** Fixed int-vs-string comparison bug in the string-format
  completion criteria path. `completion_criteria_done` entries were compared
  as integer indexes instead of matching criterion text strings.
- **Doctor check:** Added `check_epic_completion_criteria` that detects
  old-format completion criteria (string list + `completion_criteria_done`
  parallel array) and auto-migrates to the canonical dict format
  (`{id, description, done}`). Extended `write_frontmatter_field` action to
  support `remove_keys` for atomic field removal during migration.
- **Epic skill template:** Updated to emit dict-format completion criteria
  and removed all references to `completion_criteria_done`.

### Fixed — installed_version not synced after update

- **Update skill:** Added Step 5b — writes `framework.installed_version`
  to `sweetclaude.yaml` immediately after successful sync. Previously,
  this was only handled by the health check hook, which could miss updates
  when multiple plugin keys existed.
- **Plugin key resolution:** Fixed `_resolve_installed_version` in doctor.py
  and the health check hook to pick the most recently updated plugin entry
  instead of the first dict-iteration match. With both
  `sweetclaude@sweetclaude` and `sweetclaude@sweetclaude-beta` present,
  the stale entry was being selected.

---

## [4.2.0-beta] — 2026-06-08 (4.x beta channel)

> **Tag note:** `4.2.0-beta` and `4.2.1-beta` were tracked here but never cut as
> standalone git tags — their changes shipped under tag `v4.2.2-beta`. The tag
> sequence is `…v4.1.17-beta → v4.2.2-beta → v4.2.3-beta → v4.2.4-beta`.

### Added — per-work-item artifact directories

New opt-in feature (`work_item_artifacts`) that co-locates all artifacts
produced during story, epic, and milestone work into a single directory
at `.sweetclaude/work/<ITEM-ID>/`. Design docs, plans, contracts, reports,
and decision excerpts all live together — finding everything about a work
item means looking in one place.

- **Feature flag:** registered as `work_item_artifacts` in the feature system;
  enable via `/_features`. Fully opt-in — disabled by default.
- **Backfill scanner:** `scripts/backfill_work_item_artifacts.py` scans
  existing artifacts across `.sweetclaude/technical/`, `.sweetclaude/plans/`,
  `.sweetclaude/contracts/`, `.sweetclaude/reports/`, and `docs/` for files
  matching work item IDs. Creates symlinked per-item directories with
  `manifest.yaml` metadata. Supports `--dry-run`, `--item`, and `--json`.
- **Session-state integration:** `generate-session-state.sh` exposes
  `paths.work_base` and `active_work_item.work_dir` when the feature is
  active and a work item is in progress.
- **Artifact path resolution:** 8 design/technical skills redirect artifact
  writes to `{work_dir}/design/` when active, with backward-compatible
  symlinks at the legacy locations.
- **Hardcoded-path skills:** large-story, john-wick, process-controls, and
  design-manage-decisions resolve contract/report/decision paths through
  `work_dir` when active.
- **Onboarding skill:** `sweetclaude:work-item-artifacts` with onboard,
  backfill, single-item, and status flows.
- **Doctor integration:** `check_work_item_artifacts` validates directory
  structure, manifest integrity, and symlink health.
- **STORY→ISSUE alias resolution:** backfill handles the v3→v4 ID migration,
  matching `story-015-*` files to their `ISSUE-170` canonical IDs.
- **Effort linking:** manifests include `effort_link` pointers to related
  `.sweetclaude/efforts/` directories.
- **Cross-cutting artifacts:** decision log stays global (authoritative);
  per-item directories get excerpts. Multi-item artifacts use symlinks with
  manifest cross-references.

### Notes

- Beta channel only. Not part of the stable 3.x release.
- Minor version bump (4.1 → 4.2) — this is a structural change to how
  artifacts are organized.

## [4.1.17-beta] — 2026-06-07 (4.x beta channel)

### Fixed

- Eliminated hardcoded hook paths from bang-command preambles.
- Compound bang commands now hard-error on standard-permission installs instead
  of failing silently.

---

## [4.1.16-beta] — 2026-06-07 (4.x beta channel)

### Fixed / Added — doctor totality invariant

Doctor can no longer leave a project in an indeterminate state without
no-data-loss guidance. Hardening, prompted by a real incident where a
load-bearing `.sweetclaude/product` bridge symlink was mistaken for duplicate
dead weight and deleted, blinding a project's dashboard:

- **Symlink awareness:** doctor stops and explains when a symlink sits where a
  real directory is expected; it never treats the contents as duplicates/
  orphans and never offers to delete it.
- **Cache base_path:** `cache.py` now honors `artifact-privacy.yaml` base_path
  (like doctor), so relocated-base projects need no bridge symlink and the
  dashboard cache finds artifacts directly. Eliminates the symlink-bridge class.
- **Executable contract:** doctor never presents a fix it cannot run; any
  auto/prompted finding with an unsupported action downgrades to report-only
  with manual guidance.
- **Totality classifier:** every finding routes to one of auto-fixable /
  guided-manual / accepted-no-action / terminal-fallback — nothing dangles.
- **Re-adopt backstop:** an executable, snapshot-first, reversible,
  no-data-loss terminal fallback (`scripts/recovery/re_adopt.py`), the
  universal recovery when no validated migrator exists.
- **Version currency:** when the framework is behind latest, doctor advises
  updating first — some findings may already be resolved in a newer release.

### Notes

- Beta channel only. Not part of the stable 3.x release.

## [4.1.15-beta] — 2026-06-07 (4.x beta channel)

### Added

- **Large-story harness-level enforcement.** The large-story workflow now
  enforces its discipline through Claude Code hooks rather than skill
  instructions, so an agent cannot produce a plausible result while skipping
  the evidence trail:
  - PreToolUse gate denies project-file writes outside a controller-entered
    IMPLEMENT phase, and denies all direct writes to controller-owned state,
    reports, and the frozen success-criteria contract.
  - PostToolUse evidence recorder captures implementation evidence by
    observation (not model self-report); VERIFY fails closed without it.
  - Stop guard blocks session end while a workflow is non-terminal.
  - Hook-load self-check: the workflow verifies the gate is actually loaded
    before IMPLEMENT and refuses to proceed unprotected (fails loud).
  - Contract authoring commands (`init-contract`, `freeze-contract`) remove
    the schema trial-and-error and hand-computed hashes.
  - Frozen-contract amendment is blocked; legitimate amendment is a human
    action. Completed-story history is immutable.

### Fixed

- `init` closing message and the SessionStart not-configured message now point
  to valid onboarding commands.
- Compound success-criteria are reported in a single validation error instead
  of one refreeze cycle per criterion; `verify` accepts a list payload.

### Notes

- Beta channel only. Not part of the stable 3.x release.

---

## Stable 3.x Channel — current: 3.68.6

The stable branch did not previously carry its own `CHANGELOG.md`, so this
section summarizes the current stable-channel state from the `stable-3.x` branch.
Stable 3.x is the recommended channel for normal active project work.

### Changed

- Added explicit stable-channel install and update guidance: install from
  `carson-sweet/sweetclaude@stable-3.x`, update the Claude Code plugin package
  with `/plugin update sweetclaude@sweetclaude-stable`, restart Claude Code, then
  run `/sweetclaude:update` inside each project when framework files need
  syncing.
- Added a stable 3.x user-guide entry point and clarified that
  `/sweetclaude:update` does not move stable installs onto 4.x beta.
- Standardized docs and cheatsheets on `/sweetclaude:go` as the normal project
  entry point after stable install.

### Fixed

- Hardened stable install/update discovery so stable installs preserve the
  stable/beta channel boundary and do not prompt users into prerelease beta
  updates by default.
- Added deterministic plugin-state inspection for stable installs, including
  update-source detection, recorded plugin metadata, and preflight reporting.
- Aligned stable hook-maintenance and upgrade-path checks around
  `/sweetclaude:fix-sweetclaude`, Bash-blocking behavior, and plugin-native hook
  handling.

### Stable vs Beta

- Stable 3.x uses `/sweetclaude:fix-sweetclaude` for project repair.
- 4.x beta uses the newer `/sweetclaude:doctor`, `/sweetclaude:recover`, and
  guarded `/sweetclaude:migrate` maintenance front doors.
- Channel switching is explicit: install `sweetclaude@sweetclaude-beta` from
  `beta-4.x` if you intentionally want beta behavior.

## [4.1.14-beta] — 2026-05-26

### Fixed

- Fixed installed-consumer preflight behavior when `CLAUDE_PLUGIN_ROOT` is not
  set, avoiding an empty optional argument expansion under `set -u`.
- Added update-discovery regression coverage that fails if preflight emits
  stderr in the no-`CLAUDE_PLUGIN_ROOT` consumer path.

## [4.1.13-beta] — 2026-05-26

### Fixed

- Added a capability manifest as the central source for beta/stable channel
  facts, release evidence requirements, supported project shapes, and guarded
  maintenance capabilities.
- Made update/preflight sync the manifest into the installed versionless
  framework config and fail closed for beta installs when the manifest is
  missing.
- Routed Doctor, Recover, Migrate, and Release Gate through manifest-backed
  capability checks so unsupported migrations remain report-only and mutation
  commands require matching project shape, approval, and integrity evidence.
- Hardened v3-to-v4 migration finalization and cleanup against forged completion
  state by requiring execution manifests with file and migration-map hashes.

## [4.1.12-beta] — 2026-05-25

### Fixed

- Added a stale beta plugin guard to bootstrap, update, and doctor so users on beta installs older than `4.1.9-beta` see the exact `/plugin update ...` command before any project maintenance runs.
- Extended plugin-state/preflight metadata with stale-beta detection, minimum safe beta version, exact plugin update command, and restart-required fields.
- Added regression coverage for stale legacy beta installs, preflight command emission, and front-door stale-beta stops in update/bootstrap/doctor.

---

## [4.1.11-beta] — 2026-05-25

### Changed

- Made `/sweetclaude:recover` the documented recovery entrypoint. Recovery now diagnoses first by default, then plans, snapshots, asks for approval, executes, verifies, and reports rollback instructions.
- Kept explicit recovery script subcommands for automation, but removed `recover diagnose` from user-facing beta rescue instructions.
- Made `scripts/recovery/recover_project.py` default to read-only diagnosis when run without a subcommand.

---

## [4.1.10-beta] — 2026-05-25

### Documentation

- Added a public 4.x beta rescue guide for users with stale beta installs or projects stuck after update, doctor, migrate, or repair failures.
- Clarified that existing beta users should run Claude Code's plugin update first, restart Claude Code, then run `/sweetclaude:update` from the repaired beta install.
- Updated install and skills-reference docs to distinguish stable updates, beta updates, legacy beta plugin keys, and project-state recovery.

---

## [4.1.9-beta] — 2026-05-25

### Fixed

- Hardened `/sweetclaude:update` for existing beta users with stale or legacy plugin metadata. Update now detects the installed SweetClaude channel, preserves the stable/beta branch boundary, ignores wrong-branch local repo sources, and repairs the recorded plugin version, commit SHA, and install path after sync.
- Added deterministic plugin install-state inspection and repair coverage for legacy `sweetclaude` beta installs.

---

## [4.1.8-beta] — 2026-05-25

### Fixed

- Hardened the release readiness gate so beta/stable release checks inspect the
  actual git checkout branch, upstream, tracked cleanliness, and tag-at-HEAD
  instead of trusting a supplied `--branch` argument alone.

---

## [4.1.7-beta] — 2026-05-25

### Fixed

- Added evidence receipts for high-stakes completion, ship, release, and
  external-close claims.
- Made manual `status.py set-terminal --status done` fail closed unless a
  matching completion evidence receipt is provided.
- Hardened dashboard and orchestrator done transitions so active work is not
  silently cleared without completion evidence.
- Updated public closeout skills to validate and pass evidence receipts before
  marking work done.
- Added a release readiness gate that enforces beta/stable channel separation,
  matching package/plugin/changelog metadata, and release evidence receipts
  before tag preparation.

---

## [4.1.6-beta] — 2026-05-25

### Fixed

- Reduced `/sweetclaude:doctor` noise for accepted compatibility-mode legacy
  taxonomy projects. Doctor now collapses accepted legacy taxonomy findings
  into one info item while preserving real residual findings such as duplicate
  IDs, missing frontmatter, unknown statuses, missing milestone fields, stale
  derived statuses, and auto-fixable date fields.
- Made Doctor's stored run state compact and count-based. `last-doctor-run.json`
  now records severity counts, total finding count, and a bounded finding
  summary instead of unbounded full scan output.
- Hardened Doctor's pre-fix menu preference lookup so it reads only compact
  preference fields, does not print stale large Doctor run files, and does not
  skip the menu from a one-time prior `menu_preference`.

---

## [4.1.5-beta] — 2026-05-25

### Fixed

- Added a compact Doctor maintenance-route preflight so `/sweetclaude:doctor`
  presents recovery, supported migration, compatibility, or manual-review
  guidance before large full-scan reports can bury the maintenance decision.
- Improved Doctor's user-facing maintenance router so recoverable projects
  present `Run safe recovery`, supported flat migration candidates present
  `Start supported migration`, and accepted legacy taxonomy layouts clearly
  continue in compatibility mode with no migration recommendation.
- Added regression coverage for the route-only Doctor command and installed
  plugin smoke coverage on disposable llm-session-harness and SynCog copies.

---

## [4.1.4-beta] — 2026-05-25

### Fixed

- Made `/sweetclaude:migrate` fail closed on unsupported typed backlog layouts
  before creating locks, backups, converted files, or `MIGRATION-MAP.md`.
- Added a deterministic migration preflight command that blocks accepted
  compatibility-mode projects, typed legacy backlog folders, duplicate old
  work-item IDs, malformed SweetClaude state, and layouts with no flat
  `BL-NNN` files for the v3-to-v4 backlog migrator.
- Hardened `/sweetclaude:doctor` so taxonomy migration remains blocked in beta
  unless a future capability check proves the detected project layout is
  supported. Doctor no longer directly invokes `migrate_taxonomy.py` from the
  migration menu or prompted-fix delegation path.
- Decoupled `/sweetclaude:update` framework sync from project mutation. Update
  now treats project drift and taxonomy/orphan checks as read-only diagnostics
  and does not invoke `_migrate`, purge/adopt, feature setup, capability
  bootstrap, plan-directory writes, or doctor prompt marker writes inline.
- Added installed-plugin smoke coverage on disposable llm-session-harness and
  SynCog copies, proving recovery/compatibility routing, zero product artifact
  mutation during recovery, read-only update drift checks, and stable/beta
  prerelease isolation.

---

## [4.1.3-beta] — 2026-05-25

### New features

- Added `/sweetclaude:recover`, a manifest-backed recovery path for projects
  left in bad update, migration, doctor, or repair states. It diagnoses and
  plans read-only, snapshots before mutation, requires approval to execute,
  verifies doctor/update/migrate/fix safety, supports resume and rollback, and
  writes a recovery report.

### Fixed

- Recovered SynCog-class beta failure states by stabilizing unsupported typed
  backlog layouts without running taxonomy migration. The recovery route marks
  migration as deferred, records the accepted legacy layout, leaves product
  artifacts unchanged, and is idempotent after recovery.
- Hardened user-facing migration guards so status, go, bootstrap, doctor,
  backlog, issue, triage, and GitHub issue flows route unsafe legacy layouts to
  `/sweetclaude:recover` instead of telling users to run blind migration.
- Recovery guards now ignore normal time-based doctor checkup markers and only
  treat migration-related doctor prompts as recovery failures, preventing
  recovered projects from being routed back into recovery by routine checkups.
- New setup runs add `.sweetclaude/state/recovery-runs/` to `.gitignore` so
  recovery snapshots, manifests, and reports are not committed accidentally.

---

## [4.1.2-beta] — 2026-05-24

### Fixed

- Disabled unsafe update-time taxonomy/orphan migration prompts. `sweetclaude:update` now reports legacy taxonomy and orphan findings without moving, copying, deleting, or normalizing project files.
- `sweetclaude:doctor` no longer recommends taxonomy migration unless `migrate_taxonomy.py` is actually executable as a CLI entry point.
- Corrected doctor routing guidance so taxonomy migration no longer delegates to the v3-to-v4 backlog migration skill.
- Stable 3.x installs no longer get automatic prerelease prompts for 4.x beta tags; beta users still get prompted for newer beta/RC tags.

---

## [4.1.1-beta] — 2026-05-24

### New features

**Doctor diagnostic skill (EP-001, ISSUE-177–181)**
- `sweetclaude:doctor` — unified diagnostic scan and repair skill across 8 categories: state integrity, hooks, storage, migration, config, files, onboarding, environment. 257 tests.
- `validate_frontmatter()` used for all schema checks — consistent validation across all doctor categories.
- Category filter support — run specific diagnostic categories instead of full scan.
- Health delegation — `_health` delegates to doctor for consistency checks.
- `fix-sweetclaude`, `migrate-diagnose`, and `claude-config-audit` replaced with thin wrappers that redirect to `doctor`.

**Dashboard (ISSUE-188–190)**
- `sweetclaude:dashboard` — local web dashboard showing roadmap, releases, epics, backlog, dependencies, git history, and skill activity.
- Detail panel UX with sidebar navigation.
- Drag-and-drop reorder and cross-priority moves for backlog issues.
- Write-back API — changes in the dashboard persist to issue files.
- Source flag, datetime fields, and story drag-and-drop support.

**Status system overhaul (EP-002a/b, ISSUE-182–186)**
- EP-002a: status integrity — canonical validation, derived status computation, consistency checks.
- EP-002b: status visibility — derived status, view scopes, dashboard integration.
- Milestone auto-close and auto-reopen with `source:auto` tracking.
- Consolidated status views — single `/sweetclaude:status` command with dynamic view selection.

**DateTime normalization (ISSUE-192)**
- All timestamps normalized to full ISO 8601 with timezone across all state files and skill output.

### Fixed

- All script paths resolved to `~/.claude/scripts/sweetclaude/` for consistent cross-platform operation.
- Auto-close bug fixes — false closure of items prevented.
- Migration output now uses `ISSUE-NNN` format with flat backlog structure; orphan scan added.

---

## [4.1.0-beta] — 2026-05-22

### New features

**Bash-based hook repair recovery (EP-010, STORY-304)**
- `scripts/emergency-hook-restore.sh` — zero-dependency emergency hook restore script. Resolves install path via `installed_plugins.json` (with `find` fallback), restores from `hooks.bak/` (with `repo/hooks/` fallback), validates each backup with `bash -n` before accepting. Supports `--dry-run` and an optional `[hook-name.sh]` argument to restore a single hook. Uses Bash only — works when Write/Edit hooks are blocked.
- `tests/test-emergency-restore.sh` — behavioral test suite for the recovery script (eight tests passing, one documented SKIP).
- `sweetclaude:hook-repair` skill — invocable as `/sweetclaude:hook-repair`. Diagnoses broken installed hooks via `bash -n`, proposes restoration via AskUserQuestion, verifies after restore. Falls through to `bash scripts/emergency-hook-restore.sh` if the backup is missing or itself broken.
- `docs/user-guide/hook-development.md` — new user-guide page with Recovery, Emergency Recovery (Break Glass), and What to Read Next sections.

### Changed

**Artifact taxonomy rationalization (EP-001)**
- All work item prefixes unified to `ISSUE-NNN`. The per-type prefixes (`STORY-NNN`, `BUG-NNN`, `DEBT-NNN`, `CHORE-NNN`) and the legacy `BL-NNN` scheme are retired. Item type is now a frontmatter field, not an ID prefix.
- Flat `backlog/` directory replaces typed subdirectories (`stories/`, `bugs/`, `debt/`, `chores/`).
- Two-directory lifecycle: `backlog/` (untriaged) and `roadmap/issues/` (committed to an epic). Three moves: triage, complete, discard.
- 11 statuses: new, ready, active, in-review, blocked, on-hold, deferred, done, declined, abandoned, superseded.
- `sweetclaude:update` detects old-format files and offers migration. `/sweetclaude:migrate` handles the conversion with backup, preview, and verify steps.
- If you are already on v4 with `ISSUE-NNN` files, this change is transparent — no action needed.

**Version bumping is now explicit (ISSUE-069)**
- Removed `auto-version-bump` hook. Version bumps are now manual via `scripts/bump-version.sh`.
- Updated CONTRIBUTING.md and GOVERNANCE.md to reflect the explicit bump workflow.

- `README.md` — "Housekeeping" table heading renamed to "Maintenance & Troubleshooting"; new `hook-repair` row added.
- `docs/user-guide/skills-reference.md` — System table grew from 14 to 15 skills; total count bumped from 103 to 104.

---

## [4.0.9-beta] — 2026-05-19

### New features

**Roadmap cache (SQLite)**
- `scripts/cache.py` — SQLite-backed cache built from roadmap markdown frontmatter. Supports `--rebuild`, `--query releases`, `--query summary`, `--query backlog`.
- `sweetclaude:epics` skill — browse, filter, and link epics interactively.
- `sweetclaude:big-picture` now renders the full release → epic → story pipeline from the cache instead of milestones.
- `sweetclaude:go` routes P3 (find next story from active epic) via cache.
- 16 skills decoupled from `INDEX.md`; cache is the source of truth for aggregate queries.

**Self-hosting infrastructure (EP-010, STORY-300–303)**
- `scripts/sync-to-installed.sh` — canonical sync wrapper with phase gate (blocks on `implement`), backup (`hooks.bak/` before overwrite), test gate (`tests/test-hooks.sh` must pass), and atomic rollback on failure. Flags: `--dry-run`, `--force`.
- `sweetclaude:feature-setup` — replaces `sweetclaude:experimental-feature-setup`. Thin wrapper around `sync-to-installed.sh` + cache rebuild. Enforces same phase and test gates.
- `tests/test-hooks.sh` extended from 10 to 22 tests. New coverage: `test-guardian.sh` code paths (phase inactive, blocked, non-test file, non-implement tdd_phase, uppercase IMPLEMENT), `auto-test-runner.sh` code paths (phase inactive, source → triggers, test file → skip, non-Write/Edit → skip), and syntax validation (fail-closed check).

### Changed

- `sweetclaude:experimental-feature-setup` removed; use `sweetclaude:feature-setup` instead.
- `auto-test-runner.sh` TEST_PATTERNS array now matches `test-guardian.sh` exactly, including a separate `*.feature` suffix check (was using substring match, which incorrectly matched `.feature-flags/` directories).

### Deferred to 4.1.0

STORY-305 (session-start symlink detection), STORY-306 (hook development workflow documentation). STORY-304 (Bash-based hook repair recovery) was completed post-release — see [Unreleased] above.

---

## [4.0.0] — 2026-05-10

### Breaking

Story storage moved from `.sweetclaude/product/backlog/BL-NNN.md` to `docs/product/backlog/<type>s/<TYPE>-NNN-<slug>.md`. ID scheme is now per-type (`STORY-NNN`, `BUG-NNN`, `DEBT-NNN`, `CHORE-NNN`). The legacy `BL-NNN` scheme is retired. v4 cannot run against v3 storage — the bootstrap hard stop blocks every v4 skill in a v3 project until migration completes.

### Migration

`/sweetclaude:migrate` runs once per project; a safety backup is created automatically. See [docs/user-guide/v4-migration.md](docs/user-guide/v4-migration.md) for the full migration walkthrough.

### New features

- Per-type subdirectories (`stories/`, `bugs/`, `debt/`, `chores/`) with `done/` archive subdirectory.
- `MIGRATION-MAP.md` for v3↔v4 ID lookups at `docs/product/backlog/MIGRATION-MAP.md`.
- `_health` lint rules for v4 storage invariants: counter drift detection, done/status placement invariant, v3 file detection.
- `fix-sweetclaude` auto-repair recipes for lint findings.

### Removed

The EP-999 backlog-holding-epic concept is replaced by the `docs/product/backlog/INDEX.md` source of truth for counters and the visible table of unscheduled work.
