from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Literal

CachePolicy = Literal["immutable", "mutable", "volatile", "rehydratable", "none"]
NodeType = Literal[
    "normalize_intent",
    "discover_tools",
    "inspect_context",
    "compress_evidence",
    "execute_tool",
    "synthesize",
    "validate",
]
RiskLevel = Literal["none", "low", "medium", "high"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


@dataclass(slots=True)
class CompilerConfig:
    """Runtime policy for ANVIL compilation."""

    total_token_budget: int = 12_000
    max_output_tokens: int = 1_200
    max_loaded_tools: int = 8
    max_loaded_tool_tokens: int = 1_500
    max_evidence_tokens: int = 4_000
    max_system_tokens: int = 2_000
    max_task_state_tokens: int = 900
    reserve_tokens: int = 700
    compression_ratio_hint: float = 0.35
    allow_high_risk_tools: bool = False
    ledger_path: str = ".anvil/anvil_ledger.sqlite3"
    artifact_dir: str = ".anvil/artifacts"
    require_source_hashes: bool = True
    stable_prefix_version: str = "anvil-prefix-v1"

    def clamp(self) -> "CompilerConfig":
        self.total_token_budget = max(1_000, int(self.total_token_budget))
        self.max_output_tokens = max(128, int(self.max_output_tokens))
        self.max_loaded_tools = max(0, int(self.max_loaded_tools))
        self.max_loaded_tool_tokens = max(0, int(self.max_loaded_tool_tokens))
        self.max_evidence_tokens = max(0, int(self.max_evidence_tokens))
        self.max_system_tokens = max(0, int(self.max_system_tokens))
        self.max_task_state_tokens = max(128, int(self.max_task_state_tokens))
        self.reserve_tokens = max(0, int(self.reserve_tokens))
        self.compression_ratio_hint = min(1.0, max(0.05, float(self.compression_ratio_hint)))
        return self


@dataclass(slots=True)
class EvidenceDocument:
    text: str
    source_uri: str = "inline"
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceSpan:
    span_id: str
    source_uri: str
    title: str
    text: str
    source_hash: str
    token_estimate: int
    importance: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk: RiskLevel = "low"
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    enabled: bool = True
    token_estimate: int = 0


@dataclass(slots=True)
class ContextZone:
    name: str
    purpose: str
    content: str
    cache_policy: CachePolicy
    token_estimate: int
    sha256: str
    priority: int
    ledger_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionNode:
    node_id: str
    node_type: NodeType
    description: str
    depends_on: list[str] = field(default_factory=list)
    token_budget: int = 0
    tool_name: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    acceptance_checks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BudgetAllocation:
    total: int
    stable_prefix: int
    task_state: int
    tools: int
    evidence: int
    output: int
    reserve: int
    remaining: int


@dataclass(slots=True)
class ProofStep:
    step_id: str
    event_type: str
    sha256: str
    previous_sha256: str
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompileRequest:
    request: str
    system_rules: list[str] = field(default_factory=list)
    evidence: list[EvidenceDocument] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    config: CompilerConfig = field(default_factory=CompilerConfig)
    project_name: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompileResult:
    request_id: str
    project_name: str
    normalized_intent: str
    intent_class: str
    cache_key: str
    prompt_package: str
    budget: BudgetAllocation
    zones: list[ContextZone]
    loaded_tools: list[ToolSpec]
    deferred_tools: list[ToolSpec]
    execution_plan: list[ExecutionNode]
    proof_ledger: list[ProofStep]
    warnings: list[str]
    metrics: dict[str, Any]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)
