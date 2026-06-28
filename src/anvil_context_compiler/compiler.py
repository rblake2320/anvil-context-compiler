from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .budget import allocate_budget
from .compressor import EvidenceCompressor
from .hashing import sha256_json, sha256_text, short_hash
from .ledger import ContextLedger
from .models import (
    CompileRequest,
    CompileResult,
    CompilerConfig,
    ContextZone,
    EvidenceDocument,
    ExecutionNode,
    ToolSpec,
    to_jsonable,
)
from .proof import ProofLedgerBuilder
from .text import terms
from .token_meter import estimate_tokens, trim_to_tokens
from .tools import ToolSurfaceCompiler, default_tools


class AnvilCompiler:
    """Cache-aware, evidence-bound context compiler for AI agents."""

    def __init__(self, config: CompilerConfig | None = None) -> None:
        self.config = (config or CompilerConfig()).clamp()
        self.ledger = ContextLedger(self.config.ledger_path)

    def compile(self, req: CompileRequest) -> CompileResult:
        config = req.config or self.config
        config.clamp()
        # Keep compiler instance ledger aligned with per-request config.
        if str(self.ledger.path) != config.ledger_path:
            self.ledger = ContextLedger(config.ledger_path)

        request_text = req.request.strip()
        if not request_text:
            raise ValueError("CompileRequest.request cannot be empty")

        proof = ProofLedgerBuilder()
        request_hash = sha256_text(request_text)
        request_id = "req_" + request_hash[:18]
        normalized_intent = self._normalize_intent(request_text)
        intent_class = self._classify_intent(normalized_intent)
        proof.append("request_normalized", {"request_hash": request_hash, "intent": normalized_intent, "class": intent_class})

        system_text = self._stable_system_prefix(req.system_rules, config)
        system_tokens_raw = estimate_tokens(system_text)

        registry = ToolSurfaceCompiler([*default_tools(), *req.tools])
        all_tool_token_est = sum(max(1, tool.token_estimate or estimate_tokens(tool.description)) for tool in [*default_tools(), *req.tools])
        evidence_raw_tokens = sum(estimate_tokens(doc.text) for doc in req.evidence)
        budget = allocate_budget(config, system_tokens_raw, all_tool_token_est, evidence_raw_tokens)
        scope_paths = self._metadata_list(req.metadata, "scope_paths", "scope_in", "paths")
        scope_out = self._metadata_list(req.metadata, "scope_out")

        system_text = trim_to_tokens(system_text, budget.stable_prefix)
        proof.append("stable_prefix_budgeted", {"tokens": estimate_tokens(system_text), "budget": budget.stable_prefix})

        tool_selection = registry.compile_manifest(
            normalized_intent,
            max_loaded_tools=config.max_loaded_tools,
            token_budget=budget.tools,
            allow_high_risk=config.allow_high_risk_tools,
        )
        proof.append(
            "tool_surface_compiled",
            {
                "loaded": [t.name for t in tool_selection.loaded],
                "deferred_count": len(tool_selection.deferred),
                "tokens": tool_selection.token_estimate,
            },
        )

        compressor = EvidenceCompressor(self.ledger)
        compression = compressor.compress(query=normalized_intent, documents=req.evidence, token_budget=budget.evidence)
        proof.append(
            "evidence_compressed",
            {
                "original_tokens": compression.original_tokens,
                "compressed_tokens": compression.compressed_tokens,
                "ratio": compression.compression_ratio,
                "span_ids": [span.span_id for span in compression.spans],
            },
        )

        task_state = self._task_state_block(
            request_text=request_text,
            normalized_intent=normalized_intent,
            intent_class=intent_class,
            config=config,
            budget=to_jsonable(budget),
        )
        task_state = trim_to_tokens(task_state, budget.task_state)

        stable_zone = self._zone(
            name="stable_prefix",
            purpose="Reusable system policy and compiler rules; place first to maximize prompt-cache hits.",
            content=system_text,
            cache_policy="immutable",
            priority=100,
            metadata={"cache_version": config.stable_prefix_version},
        )
        task_zone = self._zone(
            name="task_state",
            purpose="Current request, normalized intent, constraints, and token budget.",
            content=task_state,
            cache_policy="mutable",
            priority=90,
            metadata={"scope_paths": scope_paths, "scope_out": scope_out},
        )
        tool_zone = self._zone(
            name="tool_surface",
            purpose="Only necessary tool schemas plus deferred index for lazy loading.",
            content=tool_selection.manifest_text,
            cache_policy="rehydratable",
            priority=80,
        )
        evidence_zone = self._zone(
            name="evidence_spans",
            purpose="Compressed evidence with exact ledger span IDs for selective rehydration.",
            content=compression.compressed_text,
            cache_policy="rehydratable",
            priority=70,
            ledger_refs=[span.span_id for span in compression.spans],
            metadata={
                "compression_ratio": compression.compression_ratio,
                "dropped_span_count": compression.dropped_span_count,
                "source_uris": sorted({doc.source_uri for doc in req.evidence if doc.source_uri}),
            },
        )
        volatile_zone = self._zone(
            name="volatile_results",
            purpose="Reserved area for tool outputs generated after compilation; never cache blindly.",
            content="[ANVIL_VOLATILE_RESULTS_EMPTY]",
            cache_policy="volatile",
            priority=10,
        )
        zones = [stable_zone, task_zone, tool_zone, evidence_zone, volatile_zone]

        cache_key = self._cache_key([stable_zone, tool_zone], config)
        proof.append("cache_key_created", {"cache_key": cache_key, "zones": [stable_zone.name, tool_zone.name]})

        plan = self._build_execution_plan(intent_class, budget, tool_selection.loaded, evidence_zone.ledger_refs)
        proof.append("execution_dag_created", {"node_ids": [node.node_id for node in plan], "node_count": len(plan)})

        prompt_package = self._render_prompt_package(zones, budget)
        plan_hash = sha256_json({"zones": [to_jsonable(z) for z in zones], "plan": [to_jsonable(n) for n in plan]})
        proof.append("prompt_package_rendered", {"prompt_tokens": estimate_tokens(prompt_package), "plan_hash": plan_hash})

        warnings = self._warnings(config, budget, compression, tool_selection, prompt_package)
        metrics = {
            "request_tokens": estimate_tokens(request_text),
            "prompt_package_tokens": estimate_tokens(prompt_package),
            "raw_system_tokens": system_tokens_raw,
            "raw_evidence_tokens": evidence_raw_tokens,
            "compressed_evidence_tokens": compression.compressed_tokens,
            "evidence_compression_ratio": compression.compression_ratio,
            "loaded_tool_count": len(tool_selection.loaded),
            "deferred_tool_count": len(tool_selection.deferred),
            "cacheable_zone_tokens": stable_zone.token_estimate + tool_zone.token_estimate,
            "rehydratable_span_count": len(compression.spans),
            "plan_hash": plan_hash,
        }
        result_metadata = {
            "scope_paths": scope_paths,
            "scope_out": scope_out,
            "evidence_source_uris": sorted({doc.source_uri for doc in req.evidence if doc.source_uri}),
            "tool_policy": {
                "allow_high_risk_tools": config.allow_high_risk_tools,
                "loaded_tool_risks": {tool.name: tool.risk for tool in tool_selection.loaded},
                "deferred_tool_risks": {tool.name: tool.risk for tool in tool_selection.deferred},
            },
        }
        self.ledger.put_compile_event(request_id, request_hash, plan_hash, metrics)

        return CompileResult(
            request_id=request_id,
            project_name=req.project_name,
            normalized_intent=normalized_intent,
            intent_class=intent_class,
            cache_key=cache_key,
            prompt_package=prompt_package,
            budget=budget,
            zones=zones,
            loaded_tools=tool_selection.loaded,
            deferred_tools=tool_selection.deferred,
            execution_plan=plan,
            proof_ledger=proof.steps,
            warnings=warnings,
            metrics=metrics,
            metadata=result_metadata,
        )

    def compile_from_dict(self, payload: dict[str, Any]) -> CompileResult:
        config_data = payload.get("config") or {}
        config = CompilerConfig(**config_data).clamp() if isinstance(config_data, dict) else CompilerConfig()
        evidence = [EvidenceDocument(**doc) if isinstance(doc, dict) else EvidenceDocument(text=str(doc)) for doc in payload.get("evidence", [])]
        tools = [ToolSpec(**tool) for tool in payload.get("tools", [])]
        req = CompileRequest(
            request=payload.get("request", ""),
            system_rules=list(payload.get("system_rules", [])),
            evidence=evidence,
            tools=tools,
            config=config,
            project_name=payload.get("project_name", "default"),
            metadata=payload.get("metadata", {}),
        )
        return self.compile(req)

    @staticmethod
    def _metadata_list(metadata: dict[str, Any], *keys: str) -> list[str]:
        values: list[str] = []
        for key in keys:
            raw = metadata.get(key)
            if raw is None:
                continue
            if isinstance(raw, str):
                candidates = [raw]
            elif isinstance(raw, (list, tuple, set)):
                candidates = [str(item) for item in raw]
            else:
                candidates = [str(raw)]
            for item in candidates:
                item = item.strip()
                if item and item not in values:
                    values.append(item)
        return values

    @staticmethod
    def _normalize_intent(text: str) -> str:
        text = re.sub(r"\s+", " ", text.strip())
        return text[:4000]

    @staticmethod
    def _classify_intent(text: str) -> str:
        t = set(terms(text))
        if {"code", "build", "implement", "repo", "api", "script", "powershell", "python"} & t:
            return "software_build"
        if {"research", "compare", "market", "latest", "current", "prove", "citation"} & t:
            return "research"
        if {"debug", "fix", "error", "traceback", "exception", "failing"} & t:
            return "debugging"
        if {"patent", "claim", "provisional", "invention"} & t:
            return "ip_strategy"
        return "general_execution"

    @staticmethod
    def _stable_system_prefix(system_rules: list[str], config: CompilerConfig) -> str:
        base_rules = [
            "ANVIL_CONTEXT_COMPILER_RULES:",
            "1. Treat context as scarce execution memory, not a dumping ground.",
            "2. Use cached immutable prefix first; keep volatile request data later.",
            "3. Load only tools proven necessary by the execution graph.",
            "4. Prefer exact evidence spans over vague summaries when correctness risk is high.",
            "5. Rehydrate ledger spans before guessing missing details.",
            "6. Before custom code: check need, native platform, stdlib, installed dependency, existing repo code, and config-only solutions.",
            "7. Validate every final answer against budget, evidence, and requested output format.",
            f"8. Stable prefix version: {config.stable_prefix_version}.",
        ]
        if system_rules:
            base_rules.append("\nPROJECT_RULES:")
            for idx, rule in enumerate(system_rules, start=1):
                base_rules.append(f"{idx}. {rule}")
        return "\n".join(base_rules)

    @staticmethod
    def _task_state_block(*, request_text: str, normalized_intent: str, intent_class: str, config: CompilerConfig, budget: dict[str, Any]) -> str:
        return "\n".join(
            [
                "ANVIL_TASK_STATE:",
                f"intent_class: {intent_class}",
                f"request: {request_text}",
                f"normalized_intent: {normalized_intent}",
                f"token_budget: {json.dumps(budget, sort_keys=True)}",
                f"allow_high_risk_tools: {config.allow_high_risk_tools}",
                "required_behavior: produce the smallest correct result; expand context only when needed.",
            ]
        )

    @staticmethod
    def _zone(
        *,
        name: str,
        purpose: str,
        content: str,
        cache_policy: str,
        priority: int,
        ledger_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContextZone:
        return ContextZone(
            name=name,
            purpose=purpose,
            content=content,
            cache_policy=cache_policy,  # type: ignore[arg-type]
            token_estimate=estimate_tokens(content),
            sha256=sha256_text(content),
            priority=priority,
            ledger_refs=ledger_refs or [],
            metadata=metadata or {},
        )

    @staticmethod
    def _cache_key(zones: list[ContextZone], config: CompilerConfig) -> str:
        payload = {
            "version": config.stable_prefix_version,
            "zones": [{"name": z.name, "sha256": z.sha256, "policy": z.cache_policy} for z in zones],
        }
        return "cache_" + sha256_json(payload)[:32]

    @staticmethod
    def _build_execution_plan(intent_class: str, budget: Any, loaded_tools: list[ToolSpec], span_refs: list[str]) -> list[ExecutionNode]:
        nodes: list[ExecutionNode] = [
            ExecutionNode(
                node_id="n1_normalize",
                node_type="normalize_intent",
                description="Confirm the minimum task scope and reject unnecessary expansion.",
                token_budget=max(128, budget.task_state // 3),
                acceptance_checks=["Intent is explicit", "Non-required work is excluded"],
            ),
            ExecutionNode(
                node_id="n2_discover_tools",
                node_type="discover_tools",
                description="Use loaded tool manifest first; inspect deferred tools only if a required capability is missing.",
                depends_on=["n1_normalize"],
                token_budget=max(128, budget.tools // 3),
                tool_name="anvil.discover_tool",
                acceptance_checks=["No full registry dump", "High-risk tools blocked unless policy allows"],
            ),
            ExecutionNode(
                node_id="n3_compress_evidence",
                node_type="compress_evidence",
                description="Use compressed evidence spans; rehydrate exact source spans only when needed.",
                depends_on=["n1_normalize"],
                token_budget=budget.evidence,
                tool_name="anvil.rehydrate_span" if span_refs else None,
                inputs={"available_span_ids": span_refs},
                acceptance_checks=["Every factual claim is tied to evidence or marked as inference"],
            ),
        ]
        if intent_class in {"software_build", "debugging"}:
            nodes.append(
                ExecutionNode(
                    node_id="n4_yagni_gate",
                    node_type="validate",
                    description="Before writing or changing code, test native/platform/stdlib/existing-code/config-only alternatives.",
                    depends_on=["n2_discover_tools", "n3_compress_evidence"],
                    token_budget=350,
                    acceptance_checks=["No custom code unless lower-cost alternatives fail", "Patch is minimal"],
                )
            )
        nodes.append(
            ExecutionNode(
                node_id="n5_synthesize",
                node_type="synthesize",
                description="Produce the smallest complete answer or action package that satisfies the request.",
                depends_on=[nodes[-1].node_id],
                token_budget=budget.output,
                acceptance_checks=["Answer fits requested format", "No avoidable verbosity", "No unsupported claims"],
            )
        )
        nodes.append(
            ExecutionNode(
                node_id="n6_validate",
                node_type="validate",
                description="Validate token budget, evidence coverage, and rollback triggers before final output.",
                depends_on=["n5_synthesize"],
                token_budget=max(128, budget.reserve // 2),
                tool_name="anvil.validate_budget",
                acceptance_checks=["Budget respected", "Rehydrate if confidence loss is detected"],
            )
        )
        return nodes

    @staticmethod
    def _render_prompt_package(zones: list[ContextZone], budget: Any) -> str:
        ordered = sorted(zones, key=lambda zone: zone.priority, reverse=True)
        parts = ["ANVIL_COMPILED_PROMPT_PACKAGE", f"TOTAL_TOKEN_BUDGET: {budget.total}", ""]
        for zone in ordered:
            parts.extend(
                [
                    f"--- ZONE: {zone.name} ---",
                    f"purpose: {zone.purpose}",
                    f"cache_policy: {zone.cache_policy}",
                    f"sha256: {zone.sha256}",
                    f"tokens_estimate: {zone.token_estimate}",
                    f"ledger_refs: {', '.join(zone.ledger_refs) if zone.ledger_refs else 'none'}",
                    zone.content,
                    "",
                ]
            )
        return "\n".join(parts).strip()

    @staticmethod
    def _warnings(config: CompilerConfig, budget: Any, compression: Any, tool_selection: Any, prompt_package: str) -> list[str]:
        warnings: list[str] = []
        prompt_tokens = estimate_tokens(prompt_package)
        if prompt_tokens > config.total_token_budget:
            warnings.append(f"Prompt package estimate exceeds total budget: {prompt_tokens}>{config.total_token_budget}")
        if compression.original_tokens and compression.compression_ratio > 0.85:
            warnings.append("Evidence compression saved little; source content may already be compact or query is too broad.")
        if tool_selection.deferred and not tool_selection.loaded:
            warnings.append("No tools loaded; only deferred index available. Increase tool budget if tool execution is expected.")
        if budget.remaining < 128:
            warnings.append("Budget is tight; answer may need rehydration or reduced output size.")
        return warnings


def compile_file_request(request: str, context_files: list[str], *, config: CompilerConfig | None = None) -> CompileResult:
    docs: list[EvidenceDocument] = []
    for file in context_files:
        path = Path(file)
        docs.append(EvidenceDocument(text=path.read_text(encoding="utf-8"), source_uri=str(path), title=path.name))
    compiler = AnvilCompiler(config)
    return compiler.compile(CompileRequest(request=request, evidence=docs, config=config or CompilerConfig()))
