from __future__ import annotations

from dataclasses import dataclass

from .ledger import ContextLedger
from .models import EvidenceDocument, EvidenceSpan
from .text import lexical_score, split_chunks
from .token_meter import estimate_tokens, trim_to_tokens


@dataclass(slots=True)
class CompressionResult:
    compressed_text: str
    spans: list[EvidenceSpan]
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    dropped_span_count: int


class EvidenceCompressor:
    """Budgeted extractive compressor with reversible source spans."""

    def __init__(self, ledger: ContextLedger) -> None:
        self.ledger = ledger

    def compress(self, *, query: str, documents: list[EvidenceDocument], token_budget: int) -> CompressionResult:
        original_tokens = sum(estimate_tokens(doc.text) for doc in documents)
        if token_budget <= 0 or not documents:
            return CompressionResult("", [], original_tokens, 0, 0.0, 0)

        candidates: list[tuple[float, EvidenceDocument, str]] = []
        for doc in documents:
            for chunk in split_chunks(doc.text):
                score = lexical_score(query, f"{doc.title}\n{chunk}")
                # Keep some generic context if query scoring is sparse.
                if score <= 0:
                    score = 0.01
                candidates.append((score, doc, chunk))

        candidates.sort(key=lambda item: item[0], reverse=True)
        used_tokens = 0
        spans: list[EvidenceSpan] = []
        lines: list[str] = []
        for score, doc, chunk in candidates:
            chunk_tokens = estimate_tokens(chunk)
            if used_tokens + chunk_tokens > token_budget:
                remaining = token_budget - used_tokens
                if remaining < 80:
                    continue
                chunk = trim_to_tokens(chunk, remaining)
                chunk_tokens = estimate_tokens(chunk)
            span = self.ledger.put_span(
                text=chunk,
                source_uri=doc.source_uri,
                title=doc.title,
                importance=score,
                metadata=doc.metadata | {"anvil_score": score},
            )
            spans.append(span)
            source_label = doc.title or doc.source_uri
            lines.append(f"[SPAN {span.span_id} | source={source_label} | tokens={span.token_estimate}]\n{chunk}")
            used_tokens += chunk_tokens
            if used_tokens >= token_budget:
                break

        compressed_text = "\n\n".join(lines)
        compressed_tokens = estimate_tokens(compressed_text)
        ratio = compressed_tokens / original_tokens if original_tokens else 0.0
        dropped = max(0, len(candidates) - len(spans))
        return CompressionResult(compressed_text, spans, original_tokens, compressed_tokens, ratio, dropped)
