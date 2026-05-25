# Installing SweetClaude

## Marketplace Install (Recommended)

Inside Claude Code, no terminal required:

```
/plugin marketplace add carson-sweet/sweetclaude@stable-3.x
/plugin install sweetclaude@sweetclaude-stable
```

For the 4.x beta channel, use this instead:

```
/plugin marketplace add carson-sweet/sweetclaude@beta-4.x
/plugin install sweetclaude@sweetclaude-beta
```

All skills are immediately available. Then go to your project and run `/sweetclaude:go` to begin.

**Beta safety note:** 4.x beta releases before `v4.1.9-beta` had known
update/recovery risks. Do not install older beta tags on active projects. Use
the current `beta-4.x` channel for beta testing.

---

## Updating

For stable installs:

```
/plugin update sweetclaude@sweetclaude-stable
```

For beta installs:

```
/plugin update sweetclaude@sweetclaude-beta
```

If `/plugin list` shows the legacy beta key `sweetclaude@sweetclaude`, update
that exact key:

```
/plugin update sweetclaude@sweetclaude
```

Restart Claude Code after any plugin update. Then run:

```
/sweetclaude:update
```

`/sweetclaude:update` syncs SweetClaude framework files to installed locations.
In the 4.x beta, project migration and setup are separate safety-gated flows;
update reports project drift without migrating project files inline.

If a beta project is already stuck from a prior update, doctor, migrate, or
repair flow, follow [SweetClaude 4.x Beta Rescue](beta-rescue.md).

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
