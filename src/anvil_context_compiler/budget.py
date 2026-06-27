from __future__ import annotations

from .models import BudgetAllocation, CompilerConfig


def allocate_budget(config: CompilerConfig, system_tokens: int, tool_tokens: int, evidence_tokens: int) -> BudgetAllocation:
    config = config.clamp()
    total = config.total_token_budget
    output = min(config.max_output_tokens, max(128, total // 5))
    reserve = min(config.reserve_tokens, max(0, total - output - 256))

    stable_prefix = min(config.max_system_tokens, system_tokens, max(0, total - output - reserve))
    tools = min(config.max_loaded_tool_tokens, tool_tokens, max(0, total - stable_prefix - output - reserve))
    task_state = min(config.max_task_state_tokens, max(128, total // 12), max(0, total - stable_prefix - tools - output - reserve))
    evidence = min(config.max_evidence_tokens, evidence_tokens, max(0, total - stable_prefix - tools - task_state - output - reserve))
    remaining = total - stable_prefix - task_state - tools - evidence - output - reserve

    if remaining < 0:
        # Shrink evidence first, then tools, while preserving output/reserve.
        over = abs(remaining)
        shrink_evidence = min(evidence, over)
        evidence -= shrink_evidence
        over -= shrink_evidence
        shrink_tools = min(tools, over)
        tools -= shrink_tools
        over -= shrink_tools
        task_state = max(128, task_state - over)
        remaining = total - stable_prefix - task_state - tools - evidence - output - reserve

    return BudgetAllocation(
        total=total,
        stable_prefix=stable_prefix,
        task_state=task_state,
        tools=tools,
        evidence=evidence,
        output=output,
        reserve=reserve,
        remaining=max(0, remaining),
    )
