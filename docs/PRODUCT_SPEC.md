# ANVIL Context Compiler Product Spec

## Product thesis

AI agents waste tokens because they treat every prompt as a bag of text. ANVIL treats context as compiled execution memory.

## Buyer pain

- Tool registries and MCP servers flood context with schemas.
- Long chat transcripts rot accuracy.
- RAG retrieves too much and compresses unreliably.
- Agent coding produces unnecessary files, abstractions, and dependencies.
- Prompt caching is underused because prompt structure is unstable.

## Product surface

1. CLI for local/CI workflows.
2. HTTP API for agent harnesses.
3. SQLite ledger for reversible context.
4. Tool-surface compiler for lazy tool loading.
5. Prompt-package renderer for downstream LLM calls.
6. Proof ledger for auditability.

## Core objects

- `CompileRequest`
- `CompileResult`
- `ContextZone`
- `ExecutionNode`
- `EvidenceSpan`
- `ToolSpec`
- `ProofStep`

## Golden path

```text
request + rules + evidence + tool specs
→ normalize intent
→ allocate token budget
→ compile stable prefix
→ select needed tool schemas
→ compress evidence into span ledger
→ render prompt package
→ emit execution DAG
→ write proof hash chain
```

## Non-goals for v1

- ANVIL does not call a specific LLM provider.
- ANVIL does not execute high-risk external tools.
- ANVIL does not claim compression is lossless; it makes compression reversible by span rehydration.

