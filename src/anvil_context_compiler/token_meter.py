from __future__ import annotations

import math
import re

_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Fast offline token estimator.

    Uses a conservative hybrid estimate. It intentionally avoids model-specific
    tokenizers so the core remains zero-dependency and usable inside restricted
    government/enterprise environments.
    """
    if not text:
        return 0
    chars_based = math.ceil(len(text) / 4)
    lexical_based = math.ceil(len(_WORD_RE.findall(text)) * 1.25)
    return max(1, int(max(chars_based, lexical_based)))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    current = estimate_tokens(text)
    if current <= max_tokens:
        return text
    # Approximate char budget with a safety margin, then walk back to sentence or line boundary.
    char_budget = max(1, int(max_tokens * 3.5))
    clipped = text[:char_budget]
    boundary = max(clipped.rfind("\n"), clipped.rfind(". "), clipped.rfind("; "))
    if boundary > char_budget * 0.55:
        clipped = clipped[: boundary + 1]
    return clipped.rstrip() + "\n[ANVIL_TRUNCATED_TO_BUDGET]"


def token_report(items: dict[str, str]) -> dict[str, int]:
    return {name: estimate_tokens(value) for name, value in items.items()}
