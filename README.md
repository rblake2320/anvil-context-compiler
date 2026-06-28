# ANVIL Context Compiler

ANVIL is a production-grade zero-dependency core for reducing AI-agent token and context waste before the model acts.

It compiles a user request into:

```text
cache-aware stable prefix
+ bounded task state
+ lazy tool surface
+ reversible evidence spans
+ execution DAG
+ proof ledger
+ token budget telemetry
```

This is not a caveman-output compressor. It is a context operating layer for agents.

## What it does

- Maximizes prompt-cache reuse with deterministic stable-prefix zones.
- Keeps volatile request data away from immutable cached regions.
- Loads only necessary tool schemas and defers the rest behind a compact index.
- Compresses evidence into exact source spans saved in a local SQLite ledger.
- Rehydrates exact spans by ID when accuracy risk demands more context.
- Builds a YAGNI-gated execution DAG before code generation.
- Produces a proof hash chain for compile decisions and persists a sidecar head anchor for compile-event tail checks.
- Runs as a CLI or local HTTP API with no required third-party packages.

## Install

```powershell
cd .\anvil_context_compiler
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests
```

Python 3.11+ works. Python 3.12 is recommended for Windows shops.

## Compile a request

```powershell
anvil-compile compile `
  --request "Build a minimal repo scanner without unnecessary dependencies" `
  --context-file .\examples\sample_context.md `
  --scope-path src `
  --scope-out prod `
  --budget 12000 `
  --out .\.anvil\plan.json `
  --prompt-out .\.anvil\compiled_prompt.txt
```

`--scope-path` and `--scope-out` are preserved in plan metadata so `anvil-core` can emit harness-ready `scope_in`, `scope_out`, and per-task `paths`.

## Run the local API

```powershell
$env:ANVIL_API_KEY = "change-me-local-dev-key"
anvil-compile serve --host 127.0.0.1 --port 8787
```

Compile through HTTP:

```powershell
$body = @{
  request = "Create the smallest correct implementation plan for an agent tool registry"
  evidence = @(@{ title = "notes"; source_uri = "inline"; text = "Load tool schemas lazily and cache stable prompt prefixes." })
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/v1/compile" `
  -Headers @{ Authorization = "Bearer $env:ANVIL_API_KEY" } `
  -ContentType "application/json" `
  -Body $body
```

## API

### `GET /health`

Returns service health.

### `POST /v1/compile`

Input:

```json
{
  "request": "Build a minimal API",
  "project_name": "demo",
  "system_rules": ["Use PowerShell for Windows multi-step tasks"],
  "evidence": [
    {"title": "note", "source_uri": "inline", "text": "Relevant source text"}
  ],
  "tools": [
    {"name": "repo.search", "description": "Search repo files", "tags": ["repo", "code"]}
  ],
  "config": {
    "total_token_budget": 12000,
    "max_loaded_tools": 8,
    "ledger_path": ".anvil/anvil_ledger.sqlite3"
  }
}
```

Output includes `prompt_package`, `execution_plan`, `zones`, `cache_key`, `proof_ledger`, and metrics.

### `POST /v1/ledger/rehydrate`

```json
{"span_ids": ["span_..."], "max_tokens": 1000}
```

### `GET /v1/ledger/spans?limit=50`

Lists recent reversible context spans.

## Verify the compile ledger

```powershell
anvil-compile verify-ledger --ledger .\.anvil\anvil_ledger.sqlite3 --require-anchor
```

Compile events are stored as a SQLite hash chain and each compile writes a sidecar head anchor containing the expected event count and final head hash. This detects edits and SQLite tail truncation when the anchor file is retained. For stronger attacker models, write the same head to an external store or sign it with a key not stored beside the ledger.

## Production deployment notes

- Default bind address is `127.0.0.1`. Do not expose directly to the public internet.
- Set `ANVIL_API_KEY` for bearer-token auth. If no key is set, requests fail closed unless the server is explicitly started with `--allow-unauthenticated-localhost`.
- Keep ledgers per project or per tenant.
- Treat ledger files as sensitive because they may contain source context.
- Put this behind your existing gateway if used in enterprise environments.
- Use a model/provider adapter above ANVIL. ANVIL produces the compiled prompt package; it does not force a specific LLM.

## Core patentable mechanisms represented in code

1. Cache-zone prompt compiler.
2. Tool-surface compiler with lazy schema expansion.
3. Reversible context compression ledger.
4. Token budget governor with acceptance checks.
5. YAGNI execution gate for code-generation tasks.
6. Proof ledger hash chain and sidecar head anchor for compile decisions.
