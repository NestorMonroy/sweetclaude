# SweetClaude 4.x Beta Rescue

Use this page if a 4.x beta install is stuck, noisy, or giving confusing update,
doctor, migrate, or repair advice.

The safe path is:

1. Update the Claude Code plugin package.
2. Restart Claude Code.
3. Run `/sweetclaude:update` after the new plugin has loaded.
4. Use doctor or recovery for project state problems.

Do not try to fix a beta install by running project migration commands first.

## Step 1: Check The Installed Plugin Key

Inside Claude Code:

```text
/plugin list
```

If you see:

```text
sweetclaude@sweetclaude-beta
```

update with:

```text
/plugin update sweetclaude@sweetclaude-beta
```

If you see the legacy beta key:

```text
sweetclaude@sweetclaude
```

update that exact key:

```text
/plugin update sweetclaude@sweetclaude
```

## Step 2: Restart Claude Code

Claude Code loads plugin skills at session start. After the plugin update,
restart Claude Code before running SweetClaude commands.

## Step 3: Sync SweetClaude Framework Files

After restart, run:

```text
/sweetclaude:update
```

The hardened beta update path preserves the stable/beta channel boundary,
ignores wrong-branch local developer repos, repairs stale plugin metadata, and
does not migrate project files inline.

If update reports project drift, stop there and use doctor or recover. Do not run
migration commands directly.

## Step 4: Recover A Stuck Project

For a bad migration, doctor, update, or repair state, run:

```text
/sweetclaude:recover
```

Recovery diagnoses first, shows a plan, snapshots before mutation, asks before
execution, verifies the result, and reports rollback instructions.

## Stable Users

Stable users should stay on the 3.x stable channel:

```text
/plugin marketplace add carson-sweet/sweetclaude@stable-3.x
/plugin install sweetclaude@sweetclaude-stable
```

Stable updates use:

```text
/plugin update sweetclaude@sweetclaude-stable
```

Stable installs should not update to the 4.x beta unless you intentionally add
and install the beta marketplace.

## What Not To Do

- Do not install old 4.x beta tags on active projects.
- Do not run `/sweetclaude:migrate` as the first response to a broken beta install.
- Do not use `/sweetclaude:fix-sweetclaude` for active repair; it redirects to `/sweetclaude:doctor`.
- Do not mix stable and beta marketplaces for the same install. Use the exact plugin key shown by `/plugin list`.
