# CodeMind OKF CLI

> **Generate AI-ready knowledge bundles from any codebase. Works with Cursor, Antigravity, GitHub Copilot, and any MCP-compatible AI IDE.**

## Install

```bash
pip install codemind-okf
```

## Quick Start

```bash
# 1. Navigate to your project
cd my-project

# 2. Generate the OKF knowledge bundle (zero LLM cost — pure AST)
codemind index .

# 3. Drop AI IDE config files so Cursor/Antigravity/Copilot use the bundle
codemind init

# 4. Open your IDE — AI now reads .okf/index.md as its primary context!
```

## Commands

### `codemind index <path>`
Crawls and indexes a project into an `.okf/` knowledge bundle.

```bash
codemind index .                         # Index current directory
codemind index /path/to/project          # Index a specific directory
codemind index . --lang python           # Only index Python files
codemind index . --overwrite             # Re-index from scratch
```

### `codemind init`
Drops AI IDE instruction files that tell Cursor, Antigravity, and Copilot to use `.okf/` as context.

```bash
codemind init                            # Create all AI IDE config files
codemind init --no-copilot              # Skip GitHub Copilot instructions
```

**Files created:**
| File | AI Tool |
|---|---|
| `.cursorrules` | Cursor AI |
| `.agents/AGENTS.md` | Antigravity IDE & compatible agents |
| `.github/copilot-instructions.md` | GitHub Copilot |

### `codemind status`
Show the current bundle statistics.

```bash
codemind status
codemind status /path/to/project
```

## How It Works

```
Your Codebase  →  AST Parser  →  ModuleSummary  →  .okf/modules/*.md
                                                    .okf/index.md
                                                    .okf/log.md
                                                           ↓
                              AI IDE reads .cursorrules → reads .okf/index.md
                              → understands full architecture instantly
```

All parsing is **deterministic and free** — no LLM calls, no API keys required.

## Output Structure

```
.okf/
├── index.md              ← Master architecture map (AI IDE reads this first)
├── log.md                ← Generation audit trail
└── modules/
    ├── src-auth-router.md
    ├── src-database-models.md
    └── src-api-endpoints.md
```

Each module file contains structured YAML frontmatter:
```yaml
---
type: api
title: Auth Router
description: Handles user authentication endpoints including login, logout, and token refresh.
resource: src/auth/auth_router.py
tags:
  - api
  - auth
  - fastapi
key_functions:
  - login
  - logout
  - refresh_token
timestamp: 2025-07-23
---
```

## Supported Languages

- Python (`.py`) — Full AST analysis
- JavaScript (`.js`, `.jsx`) — AST + regex parsing
- TypeScript (`.ts`, `.tsx`) — AST + regex parsing

## License

MIT © CodeMind
