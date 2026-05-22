# SweetClaude Migration Guide

**Version:** 4.1.0-beta
**Date:** 2026-05-21

---

## Overview

SweetClaude uses a unified taxonomy for all work items: `ISSUE-NNN` files stored in `.sweetclaude/product/backlog/`. If your project has files in an older format (`BL-NNN`, `STORY-NNN`, `BUG-NNN`, `DEBT-NNN`, `CHORE-NNN`) or in older directory structures (`docs/product/backlog/`, typed subdirectories like `stories/`, `bugs/`), you need to migrate.

### What the current format looks like

- All work items are `ISSUE-NNN-<slug>.md` in `.sweetclaude/product/backlog/`
- Item type (story, bug, debt, chore, spike) is a frontmatter field, not an ID prefix
- Done items move to `.sweetclaude/product/backlog/done/`
- Triaged items move to `.sweetclaude/product/roadmap/issues/`
- The SQLite cache (`scripts/cache.py`) is the source of truth for aggregate queries

### Migration is safe and reversible

Before touching a single file, `/sweetclaude:migrate` creates a full timestamped backup. If anything goes wrong, one command restores you to exactly where you started. Original files are never deleted during migration — they stay in place until you explicitly choose to remove them.

---

## When migration is needed

`/sweetclaude:update` automatically detects old-format files and offers migration. You can also run `/sweetclaude:migrate` directly. Skills that read backlog files will detect unmigrated data and prompt you.

If you skip migration, skills that use the cache (like `/sweetclaude:go`) will not see your old items. Skills with migration guards (like `/sweetclaude:project-issues`) will detect old files and ask you to migrate first.

---

## What migration does

- Creates a timestamped safety backup at `.sweetclaude/state/backups/`
- Scans all old-format files, validates them, and aborts before any write if validation fails
- Shows a preview of every planned rename/move before any file is created
- Converts each item to `ISSUE-NNN-<slug>.md` with updated frontmatter
- Moves files to `.sweetclaude/product/backlog/` (flat structure)
- Verifies every written file before declaring success
- On any failure, restores from backup
- On success, offers to delete original files (the backup remains)

---

## If something goes wrong

- During migration, on any failure: the skill offers diagnosis via `/sweetclaude:migrate-diagnose`, a state reset, or wait
- Manual rollback at any time via the backup archive in `.sweetclaude/state/backups/`

---

## FAQ

**Do I have to migrate?**
Not immediately. You can skip migration when prompted. But most skills will either not see your old items or will refuse to run until migration is complete. Migration is the recommended path.

**What happens to my git history?**
Migration does not rewrite history. New files are created; originals remain until you accept the delete offer.

**Can I migrate one project and defer others?**
Yes. The framework update is global, but migration is per-project. Each project can migrate on its own schedule.

**Can I roll back?**
Yes, via the backup archive created before migration.
