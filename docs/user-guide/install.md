# Installing SweetClaude

SweetClaude has two supported install tracks:

- **Stable 3.x**: recommended for normal active project work.
- **4.x beta**: explicit opt-in for testing the newer project maintenance and taxonomy model.

Do not use `/sweetclaude:update` to move between stable and beta. Choose the
Claude Code plugin marketplace channel intentionally.

## Stable 3.x Install

Inside Claude Code:

```text
/plugin marketplace add carson-sweet/sweetclaude@stable-3.x
/plugin install sweetclaude@sweetclaude-stable
```

Then run:

```text
/sweetclaude:help
```

## 4.x Beta Install

Inside Claude Code:

```text
/plugin marketplace add carson-sweet/sweetclaude@beta-4.x
/plugin install sweetclaude@sweetclaude-beta
```

Restart Claude Code after install. Then run:

```text
/sweetclaude:help
```

Use the current `beta-4.x` channel for beta testing. Do not install old 4.x beta
tags on active projects.

## Updating

Update the Claude Code plugin package first, restart Claude Code, then run the
SweetClaude framework sync command.

Stable:

```text
/plugin update sweetclaude@sweetclaude-stable
```

Beta:

```text
/plugin update sweetclaude@sweetclaude-beta
```

If `/plugin list` shows the legacy beta key `sweetclaude@sweetclaude`, update
that exact key instead:

```text
/plugin update sweetclaude@sweetclaude
```

After plugin update, restart Claude Code. Then run:

```text
/sweetclaude:update
```

`/sweetclaude:update` syncs SweetClaude framework files inside the installed
channel. In the hardened 4.x beta path, it reports project drift but does not run
project-state migrations or taxonomy migrations inline. For project repair or
migration prompts, run `/sweetclaude:doctor`.

If a 4.x beta project is already stuck from a prior update, doctor, migrate, or
repair flow, follow [SweetClaude 4.x Beta Rescue](4.x-beta/beta-rescue.md).

---

## Optional Integrations

### Firecrawl (web research enhancement)

[Firecrawl](https://firecrawl.dev) adds JavaScript-rendered page extraction, structured schema output, and autonomous multi-page research to `sweetclaude:product-research` and `sweetclaude:product-competition`. Both skills degrade gracefully if Firecrawl is absent.

1. Create an account at [firecrawl.dev](https://firecrawl.dev) — Hobby tier ($16/mo) or free trial.
2. Add the MCP server to Claude Code settings:
   ```json
   {
     "mcpServers": {
       "firecrawl": {
         "command": "npx",
         "args": ["-y", "@firecrawl/mcp-server"],
         "env": { "FIRECRAWL_API_KEY": "YOUR_API_KEY" }
       }
     }
   }
   ```
3. Restart Claude Code. The research and competition skills will automatically detect Firecrawl and use it when present.

### Local RAG (semantic search over your documents)

SweetClaude's corpus management pipeline (`/sweetclaude:document-corpus`) can build a local semantic search index over your canonical documents. You can then ask questions like "what did we decide about authentication?" and get the relevant passages back — no external services, all on your machine.

This uses [mcp-local-rag](https://www.npmjs.com/package/mcp-local-rag), which runs a per-project [LanceDB](https://lancedb.com/) vector database.

**Prerequisites:** Node.js (any recent version).

1. Install the MCP server globally:
   ```bash
   npm install -g mcp-local-rag
   ```

2. Add it to Claude Code's MCP settings (`~/.claude/settings.json` or via `/config`):
   ```json
   {
     "mcpServers": {
       "local-rag": {
         "command": "mcp-local-rag",
         "args": []
       }
     }
   }
   ```

3. Restart Claude Code. The corpus pipeline's **Promote** and **Reindex RAG** steps will automatically use it when present.

Without RAG installed, the corpus pipeline still works through the Promote step — your canonical documents are organized and versioned. You just won't have the semantic search index. RAG can be added later without redoing any prior corpus work; just install and run `/sweetclaude:document-corpus reindex`.

---

## Uninstalling

To suspend SweetClaude for one project without uninstalling globally:

```bash
touch .sweetclaude/disabled
```

Run `/sweetclaude:go` to reactivate.
