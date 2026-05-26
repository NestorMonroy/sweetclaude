# Privacy Policy

**SweetClaude**
Last updated: 2026-05-25

## Summary

SweetClaude does not collect, transmit, or store any personal data. It runs entirely on your local machine.

## What SweetClaude does

SweetClaude is a Claude Code plugin. It installs skills, hooks, and configuration files onto your local filesystem and operates through Claude Code's standard AI session model.

SweetClaude writes state files to a `.sweetclaude/` directory inside your project. These files contain project metadata you provide (work items, decisions, personas, backlog entries) and are stored only on your machine. Doctor and recovery flows may also create local snapshots and manifests under paths such as `.sweetclaude/state/doctor-runs/` and `.sweetclaude/state/recovery-runs/`; those snapshots can include SweetClaude state and product artifacts so rollback is possible. They are never transmitted anywhere by SweetClaude.

## What SweetClaude does not do

- Does not collect telemetry or usage data
- Does not transmit any data to SweetClaude servers (there are none)
- Does not store any information outside your local filesystem
- Does not access your files beyond what you explicitly direct it to during a Claude Code session

## Anthropic and Claude Code

SweetClaude operates inside Claude Code, which sends your conversation and context to Anthropic's API for AI processing. That data is governed by [Anthropic's Privacy Policy](https://www.anthropic.com/privacy) and [Claude Code's Terms of Service](https://www.anthropic.com/legal/claude-code-terms). SweetClaude has no visibility into or control over that processing.

## Contact

Questions: open an issue at https://github.com/carson-sweet/sweetclaude/issues
