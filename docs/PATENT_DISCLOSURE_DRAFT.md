# ANVIL Patent Disclosure Draft

This is not legal advice. This is an engineering disclosure starter for patent counsel.

## Working title

Cache-Aware Reversible Context Compiler for Autonomous AI Agents

## Problem

Existing systems reduce token usage through isolated mechanisms such as prompt caching, summarization, output brevity, tool retrieval, or document compression. They do not provide a unified compiler that converts user intent into a cache-aware, tool-minimized, evidence-bound execution graph with reversible compression and auditability.

## Inventive concepts

### 1. Cache-zone context compiler

A compiler partitions agent context into immutable, mutable, volatile, and rehydratable zones, orders those zones to maximize cache reuse, and emits a cache key derived from stable zone hashes.

### 2. Reversible context compression ledger

A system compresses source context into budgeted evidence spans while storing exact source chunks in a local ledger keyed by source hash and span ID. The agent can restore only needed spans when uncertainty, validation failure, or user challenge occurs.

### 3. Tool-surface compiler

A system compiles a large tool registry into a limited loaded set plus compact deferred index, exposing full schemas only after intent-tool matching proves need.

### 4. Token budget governor

A runtime allocates token budgets across stable prefix, task state, tools, evidence, output, and reserve, then rejects or trims context zones that exceed allocation.

### 5. YAGNI execution gate

For code-generation tasks, the execution graph forces native platform, standard library, installed dependency, existing repo code, and config-only checks before allowing custom code creation.

### 6. Proof ledger hash chain

A hash-chain ledger records compile decisions, context-zone hashes, tool-selection decisions, compression ratios, and execution DAG creation events.

## Example independent claim seed

A computer-implemented method comprising: receiving a natural-language task request for an AI agent; normalizing the task request into an intent representation; partitioning agent context into a plurality of context zones having cache policies comprising immutable, mutable, volatile, and rehydratable policies; selecting a subset of tool definitions from a tool registry based on the intent representation and a tool token budget; compressing source evidence into evidence spans stored in a ledger and referenced by span identifiers; generating an execution graph comprising nodes associated with token budgets and acceptance checks; generating a prompt package ordered according to the cache policies; and storing a proof record comprising hashes of the selected context zones, selected tool definitions, evidence spans, and execution graph.

## Differentiation notes

- Different from output-compression tools: ANVIL governs input, tools, evidence, memory, and execution.
- Different from ordinary prompt caching: ANVIL compiles cacheable zones and volatile zones separately.
- Different from ordinary summarization: ANVIL keeps exact source spans rehydratable.
- Different from tool search alone: ANVIL combines tool selection with token budget, context zones, and proof ledger.

