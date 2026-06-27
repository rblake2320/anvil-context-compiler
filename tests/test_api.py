from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from anvil_context_compiler.api import run_server
from anvil_context_compiler.models import CompilerConfig


class APITests(unittest.TestCase):
    def test_compile_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            port = 8899
            thread = threading.Thread(
                target=run_server,
                kwargs={"host": "127.0.0.1", "port": port, "config": CompilerConfig(ledger_path=str(Path(td) / "ledger.sqlite3"))},
                daemon=True,
            )
            thread.start()
            time.sleep(0.2)
            payload = json.dumps({"request": "Compile this request", "config": {"ledger_path": str(Path(td) / "ledger.sqlite3")}}).encode("utf-8")
            req = Request(f"http://127.0.0.1:{port}/v1/compile", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=5) as resp:  # noqa: S310 - local test server only
                data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("cache_key", data)
            self.assertIn("execution_plan", data)


if __name__ == "__main__":
    unittest.main()
