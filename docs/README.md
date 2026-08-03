# SweetClaude Documentation

**Version:** 2.0
**Date:** 2026-08-03

Start with the guide that matches the SweetClaude plugin channel installed in
Claude Code.

## Stable: 4.x on `main`

Stable 4.x is the recommended channel for normal active project work.

| Item | Link |
|---|---|
| User guide index | [4.x User Guide](user-guide/index.md) |
| Install and update | [4.x Install](user-guide/install.md) |
| How it works | [4.x How It Works](user-guide/how-it-works.md) |
| Migration and recovery | [4.x Migration and Recovery](user-guide/migration-and-recovery.md) |
| Rescue guide | [4.x Beta Rescue](user-guide/beta-rescue.md) (for installs from the retired beta channel) |
| Changelog | [Full changelog](../CHANGELOG.md) |

Stable 4.x uses:

```text
/plugin marketplace add carson-sweet/sweetclaude@main
/plugin install sweetclaude@sweetclaude-stable
```

Stable 4.x separates framework update from project maintenance. Update the
plugin package and restart Claude Code before running `/sweetclaude:update`.
Project repair, recovery, and supported migration route through
`/sweetclaude:doctor`, `/sweetclaude:recover`, and guarded
`/sweetclaude:migrate`.

## Legacy: 3.x on `stable-3.x`

Legacy 3.x receives maintenance only. New installs should use stable 4.x.

| Item | Link |
|---|---|
| User guide index | [3.x User Guide (stable-3.x branch)](https://github.com/carson-sweet/sweetclaude/blob/stable-3.x/docs/user-guide/index.md) |
| Install and update | [3.x Install (stable-3.x branch)](https://github.com/carson-sweet/sweetclaude/blob/stable-3.x/docs/user-guide/install.md) |

Legacy 3.x uses:

```text
/plugin marketplace add carson-sweet/sweetclaude@stable-3.x
/plugin install sweetclaude@sweetclaude-legacy
```

To move a 3.x project to 4.x, install stable 4.x and run `/sweetclaude:update`
inside the project; migration is guarded and reversible.

## Retired: 4.x Beta

The 4.x beta channel is retired. It no longer receives updates and cannot be
installed. If `/plugin list` shows `sweetclaude@sweetclaude-beta`, make the
one-time switch to stable — run these in order so you are never
double-installed:

```text
/plugin marketplace add carson-sweet/sweetclaude@main
/plugin install sweetclaude@sweetclaude-stable
/plugin marketplace remove sweetclaude-beta
```

Then restart Claude Code and run `/sweetclaude:update`. If a former beta
install is stuck, see [4.x Beta Rescue](user-guide/beta-rescue.md).

## Design & Analysis

| Item | Link |
|---|---|
| Native Claude Code capabilities vs. SweetClaude | [Native capabilities analysis](design/native-capabilities-analysis.md) |

## Other Entry Points

- [Back to main README](../README.md)
- [User guide](user-guide/index.md)
- [Full changelog](../CHANGELOG.md)
