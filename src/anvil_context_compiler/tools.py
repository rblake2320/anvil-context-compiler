from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import ToolSpec
from .text import lexical_score
from .token_meter import estimate_tokens, trim_to_tokens


@dataclass(slots=True)
class ToolSelection:
    loaded: list[ToolSpec]
    deferred: list[ToolSpec]
    manifest_text: str
    token_estimate: int


class ToolSurfaceCompiler:
    """Compacts a large tool surface into an inspect-on-demand manifest."""

    def __init__(self, tools: Iterable[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if not tool.name or not tool.description:
            raise ValueError("tool.name and tool.description are required")
        if tool.token_estimate <= 0:
            tool.token_estimate = estimate_tokens(self._format_full_tool(tool))
        self._tools[tool.name] = tool

    def search(self, query: str, *, limit: int = 10, allow_high_risk: bool = False) -> list[ToolSpec]:
        scored: list[tuple[float, ToolSpec]] = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            if tool.risk == "high" and not allow_high_risk:
                continue
            haystack = "\n".join([tool.name, tool.description, " ".join(tool.tags), " ".join(tool.examples)])
            score = lexical_score(query, haystack)
            if score <= 0:
                score = 0.01
            scored.append((score, tool))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [tool for _, tool in scored[: max(0, limit)]]

    def inspect(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def compile_manifest(
        self,
        query: str,
        *,
        max_loaded_tools: int,
        token_budget: int,
        allow_high_risk: bool = False,
    ) -> ToolSelection:
        candidates = self.search(query, limit=max_loaded_tools * 3 + 5, allow_high_risk=allow_high_risk)
        loaded: list[ToolSpec] = []
        deferred: list[ToolSpec] = []
        used = 0
        for tool in candidates:
            full = self._format_full_tool(tool)
            full_tokens = estimate_tokens(full)
            if len(loaded) < max_loaded_tools and used + full_tokens <= token_budget:
                loaded.append(tool)
                used += full_tokens
            else:
                deferred.append(tool)
        loaded_names = {tool.name for tool in loaded}
        for tool in self._tools.values():
            if tool.name not in loaded_names and tool not in deferred:
                deferred.append(tool)

        lines = [
            "ANVIL_TOOL_SURFACE:",
            "- Use loaded tools only when they are required by the execution DAG.",
            "- Deferred tools are discoverable by name/tag but full schemas are not loaded until needed.",
            "- High-risk tools require explicit policy approval.",
            "",
            "LOADED_TOOLS:",
        ]
        for tool in loaded:
            lines.append(self._format_full_tool(tool))
        if deferred:
            lines.append("\nDEFERRED_TOOL_INDEX:")
            for tool in deferred[:100]:
                tags = ",".join(tool.tags[:5])
                lines.append(f"- {tool.name}: {trim_to_tokens(tool.description, 30)} | risk={tool.risk} | tags={tags}")
            if len(deferred) > 100:
                lines.append(f"- [ANVIL_DEFERRED_TOOL_INDEX_TRUNCATED count={len(deferred)-100}]")
        manifest = trim_to_tokens("\n".join(lines), token_budget)
        return ToolSelection(loaded, deferred, manifest, estimate_tokens(manifest))

    @staticmethod
    def _format_full_tool(tool: ToolSpec) -> str:
        return (
            f"- name: {tool.name}\n"
            f"  description: {tool.description}\n"
            f"  risk: {tool.risk}\n"
            f"  tags: {', '.join(tool.tags)}\n"
            f"  input_schema: {tool.input_schema}\n"
            f"  output_schema: {tool.output_schema}\n"
        )


def default_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="anvil.discover_tool",
            description="Search the available tool registry and return compact candidate names without loading full schemas.",
            input_schema={"query": "string", "limit": "integer"},
            output_schema={"tools": "array"},
            risk="low",
            tags=["tool", "search", "registry"],
        ),
        ToolSpec(
            name="anvil.inspect_tool",
            description="Load the full schema and operational policy for one named tool only after discovery proves need.",
            input_schema={"name": "string"},
            output_schema={"tool_spec": "object"},
            risk="low",
            tags=["tool", "schema", "lazy-load"],
        ),
        ToolSpec(
            name="anvil.rehydrate_span",
            description="Restore exact source evidence spans from the reversible context ledger by span ID.",
            input_schema={"span_ids": "array[string]", "max_tokens": "integer"},
            output_schema={"spans": "array"},
            risk="low",
            tags=["context", "ledger", "rehydrate", "evidence"],
        ),
        ToolSpec(
            name="anvil.validate_budget",
            description="Validate that a proposed prompt or execution step stays inside token, tool, evidence, and output budgets.",
            input_schema={"text": "string", "budget": "integer"},
            output_schema={"ok": "boolean", "token_estimate": "integer"},
            risk="none",
            tags=["budget", "tokens", "validation"],
        ),
    ]
