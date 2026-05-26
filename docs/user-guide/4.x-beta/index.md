# SweetClaude 4.x Beta User Guide

Use this track only if you intentionally installed the 4.x beta marketplace or
`/plugin list` shows `sweetclaude@sweetclaude-beta`.

4.x beta changes project maintenance behavior. Plugin update, framework sync,
project recovery, and taxonomy migration are separate safety-gated flows.

## Install

```text
/plugin marketplace add carson-sweet/sweetclaude@beta-4.x
/plugin install sweetclaude@sweetclaude-beta
```

Then restart Claude Code and run:

```text
/sweetclaude:help
```

## Update

Update the Claude Code plugin package first:

```text
/plugin update sweetclaude@sweetclaude-beta
```

If `/plugin list` shows the legacy beta key `sweetclaude@sweetclaude`, update
that exact key instead:

```text
/plugin update sweetclaude@sweetclaude
```

Restart Claude Code after plugin update. Then run:

```text
/sweetclaude:update
```

In the hardened 4.x beta path, update syncs framework files and reports drift.
It does not run project-state migrations or taxonomy migrations inline.

## Maintenance Front Door

For project problems after update, start with:

```text
/sweetclaude:doctor
```

Doctor routes to one of these outcomes:

- `recovery-available`: run `/sweetclaude:recover`.
- `supported-migration-available`: run `/sweetclaude:migrate`.
- `compatibility-mode`: continue without migration; accepted legacy taxonomy noise is collapsed.
- `no-migration-recommended`: no migration prompt is shown.

## Start Here

- [4.x Migration and Recovery](migration-and-recovery.md)
- [Beta Rescue](beta-rescue.md)
- [Install and Update](../install.md)
- [State and Memory](../state-and-memory.md)
- [Skills Reference](../skills-reference.md)
