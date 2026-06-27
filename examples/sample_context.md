# Sample Context

ANVIL should keep the immutable system policy stable at the start of the prompt package so provider prompt caching can reuse it.

A large tool registry should not be loaded into the model by default. The agent should first search a compact tool index, then inspect exactly one tool schema only when needed.

Summaries lose details. ANVIL stores exact source spans in a local ledger and references the span IDs in compressed context. The agent can rehydrate the span when risk is high.

Before writing custom code, the agent should check whether the task is needed, whether the platform/stdlib already solves it, whether an installed dependency already exists, whether existing repo code already covers it, and whether config alone can solve it.
