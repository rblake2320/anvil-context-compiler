from __future__ import annotations

import re
from collections import Counter

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "i", "in", "is", "it", "its",
    "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "you", "your", "we", "our", "can",
    "could", "would", "should", "not", "no", "yes", "do", "does", "did", "done", "into", "out", "up", "down",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_#+.-]{2,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def terms(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS]


def term_counter(text: str) -> Counter[str]:
    return Counter(terms(text))


def split_chunks(text: str, max_chars: int = 1600) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    for para in paras:
        if len(para) <= max_chars:
            chunks.append(para)
            continue
        current = ""
        for sentence in [s.strip() for s in _SENTENCE_RE.split(para) if s.strip()]:
            if len(current) + len(sentence) + 1 <= max_chars:
                current = (current + " " + sentence).strip()
            else:
                if current:
                    chunks.append(current)
                current = sentence[:max_chars]
        if current:
            chunks.append(current)
    return chunks


def lexical_score(query: str, text: str) -> float:
    q = term_counter(query)
    if not q:
        return 0.0
    t = term_counter(text)
    if not t:
        return 0.0
    overlap = sum(min(q[k], t[k]) for k in q)
    rare_bonus = sum(1.0 / max(1, t[k]) for k in q if k in t)
    return float(overlap) + rare_bonus


def compact_lines(lines: list[str], max_lines: int = 50) -> str:
    clean = [line.strip() for line in lines if line and line.strip()]
    return "\n".join(clean[:max_lines])
