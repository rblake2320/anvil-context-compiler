from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from anvil_context_compiler import AnvilCompiler
from anvil_context_compiler.compressor import EvidenceCompressor
from anvil_context_compiler.ledger import ContextLedger
from anvil_context_compiler.models import CompileRequest, CompilerConfig, EvidenceDocument, ToolSpec
from anvil_context_compiler.token_meter import estimate_tokens, trim_to_tokens
from anvil_context_compiler.tools import ToolSurfaceCompiler


class TokenMeterTests(unittest.TestCase):
    def test_estimate_and_trim(self) -> None:
        text = "hello world " * 1000
        self.assertGreater(estimate_tokens(text), 100)
        trimmed = trim_to_tokens(text, 80)
        self.assertLessEqual(estimate_tokens(trimmed), 120)


class LedgerTests(unittest.TestCase):
    def test_put_and_rehydrate_span(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = ContextLedger(str(Path(td) / "ledger.sqlite3"))
            span = ledger.put_span(text="Exact evidence text", source_uri="unit", importance=9.0)
            restored = ledger.rehydrate([span.span_id])
            self.assertEqual(restored[0].text, "Exact evidence text")
            self.assertEqual(restored[0].span_id, span.span_id)

    def test_compile_events_are_hash_chained_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ledger.sqlite3"
            ledger = ContextLedger(str(db_path))
            ledger.put_compile_event("evt", "req_hash_1", "plan_hash_1", {"tokens": 10})
            ledger.put_compile_event("evt", "req_hash_2", "plan_hash_2", {"tokens": 12})
            self.assertTrue(ledger.verify_compile_events())

            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("UPDATE compile_events SET plan_hash = ? WHERE event_id = ?", ("tampered", "evt"))
                conn.commit()
            finally:
                conn.close()
            self.assertFalse(ledger.verify_compile_events())

    def test_compile_event_anchor_detects_tail_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ledger.sqlite3"
            ledger = ContextLedger(str(db_path))
            ledger.put_compile_event("evt", "req_hash_1", "plan_hash_1", {"tokens": 10})
            ledger.put_compile_event("evt", "req_hash_2", "plan_hash_2", {"tokens": 12})
            self.assertTrue(ledger.verify_compile_events(require_anchor=True))

            conn = sqlite3.connect(str(db_path))
            try:
                last_rowid = conn.execute("SELECT rowid FROM compile_events ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                conn.execute("DELETE FROM compile_events WHERE rowid = ?", (last_rowid,))
                conn.commit()
            finally:
                conn.close()
            self.assertFalse(ledger.verify_compile_events(require_anchor=True))


class CompressorTests(unittest.TestCase):
    def test_compress_under_budget_with_spans(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = ContextLedger(str(Path(td) / "ledger.sqlite3"))
            compressor = EvidenceCompressor(ledger)
            doc = EvidenceDocument(
                text="""
                The ANVIL compiler caches immutable prompt prefixes.

                Random irrelevant paragraph about fruit and chairs.

                Tool-surface compilation loads only needed tool schemas.
                """,
                source_uri="doc://test",
                title="ANVIL Notes",
            )
            result = compressor.compress(query="cache prompt tools", documents=[doc], token_budget=120)
            self.assertGreaterEqual(len(result.spans), 1)
            self.assertIn("SPAN", result.compressed_text)
            self.assertLessEqual(result.compressed_tokens, 180)


class ToolCompilerTests(unittest.TestCase):
    def test_tool_selection_defers_unneeded_tools(self) -> None:
        tools = [
            ToolSpec(name="tool.alpha", description="Search files and inspect code", tags=["code", "search"]),
            ToolSpec(name="tool.beta", description="Send high risk production deploy", risk="high", tags=["deploy"]),
        ]
        compiler = ToolSurfaceCompiler(tools)
        selection = compiler.compile_manifest("inspect code", max_loaded_tools=1, token_budget=500)
        self.assertEqual(selection.loaded[0].name, "tool.alpha")
        self.assertTrue(any(t.name == "tool.beta" for t in selection.deferred))


class CompilerTests(unittest.TestCase):
    def test_compile_creates_cache_key_dag_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CompilerConfig(total_token_budget=3000, ledger_path=str(Path(td) / "ledger.sqlite3"))
            compiler = AnvilCompiler(config)
            result = compiler.compile(
                CompileRequest(
                    request="Build a minimal API and do not write unnecessary code.",
                    evidence=[EvidenceDocument(text="Use native stdlib HTTP if dependency budget is zero.", source_uri="inline", title="Rule")],
                    tools=[ToolSpec(name="repo.search", description="Search repository symbols and files", tags=["repo", "code"])],
                    config=config,
                )
            )
            self.assertTrue(result.cache_key.startswith("cache_"))
            self.assertGreaterEqual(len(result.execution_plan), 5)
            self.assertTrue(any(zone.name == "evidence_spans" for zone in result.zones))
            self.assertGreater(result.metrics["prompt_package_tokens"], 0)

    def test_compile_preserves_scope_and_tool_policy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CompilerConfig(total_token_budget=3000, ledger_path=str(Path(td) / "ledger.sqlite3"))
            compiler = AnvilCompiler(config)
            result = compiler.compile(
                CompileRequest(
                    request="Build a minimal API.",
                    evidence=[EvidenceDocument(text="Use src only.", source_uri="docs/spec.md", title="Spec")],
                    tools=[ToolSpec(name="deploy.prod", description="Deploy production", risk="high", tags=["deploy"])],
                    config=config,
                    metadata={"scope_paths": ["src"], "scope_out": ["prod"]},
                )
            )
            self.assertEqual(result.metadata["scope_paths"], ["src"])
            self.assertEqual(result.metadata["scope_out"], ["prod"])
            self.assertIn("docs/spec.md", result.metadata["evidence_source_uris"])
            self.assertEqual(result.metadata["tool_policy"]["deferred_tool_risks"]["deploy.prod"], "high")


if __name__ == "__main__":
    unittest.main()
