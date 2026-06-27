from __future__ import annotations

from typing import Any

from .hashing import sha256_json, sha256_text
from .models import ProofStep


class ProofLedgerBuilder:
    """Append-only hash chain for prompt/package decisions."""

    def __init__(self) -> None:
        self.steps: list[ProofStep] = []
        self._previous = "GENESIS"

    def append(self, event_type: str, payload: Any, metadata: dict[str, Any] | None = None) -> ProofStep:
        payload_hash = sha256_json({"event_type": event_type, "payload": payload, "previous": self._previous})
        step = ProofStep(
            step_id="proof_" + sha256_text(f"{len(self.steps)}:{payload_hash}")[:16],
            event_type=event_type,
            sha256=payload_hash,
            previous_sha256=self._previous,
            metadata=metadata or {},
        )
        self.steps.append(step)
        self._previous = payload_hash
        return step
