from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from anvil_context_compiler.api import run_server
from anvil_context_compiler.models import CompilerConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class APITests(unittest.TestCase):
    def test_compile_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_key = os.environ.pop("ANVIL_API_KEY", None)
            port = _free_port()
            thread = threading.Thread(
                target=run_server,
                kwargs={
                    "host": "127.0.0.1",
                    "port": port,
                    "config": CompilerConfig(ledger_path=str(Path(td) / "ledger.sqlite3")),
                    "allow_unauthenticated_localhost": True,
                },
                daemon=True,
            )
            try:
                thread.start()
                time.sleep(0.2)
                payload = json.dumps({"request": "Compile this request", "config": {"ledger_path": str(Path(td) / "ledger.sqlite3")}}).encode("utf-8")
                req = Request(f"http://127.0.0.1:{port}/v1/compile", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req, timeout=5) as resp:  # noqa: S310 - local test server only
                    data = json.loads(resp.read().decode("utf-8"))
            finally:
                if old_key is None:
                    os.environ.pop("ANVIL_API_KEY", None)
                else:
                    os.environ["ANVIL_API_KEY"] = old_key
            self.assertIn("cache_key", data)
            self.assertIn("execution_plan", data)

    def test_server_fails_closed_without_key_or_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_key = os.environ.pop("ANVIL_API_KEY", None)
            port = _free_port()
            thread = threading.Thread(
                target=run_server,
                kwargs={"host": "127.0.0.1", "port": port, "config": CompilerConfig(ledger_path=str(Path(td) / "ledger.sqlite3"))},
                daemon=True,
            )
            try:
                thread.start()
                time.sleep(0.2)
                req = Request(f"http://127.0.0.1:{port}/health")
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(req, timeout=5)  # noqa: S310 - local test server only
                self.assertEqual(ctx.exception.code, 401)
            finally:
                if old_key is None:
                    os.environ.pop("ANVIL_API_KEY", None)
                else:
                    os.environ["ANVIL_API_KEY"] = old_key

    def test_server_accepts_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_key = os.environ.get("ANVIL_API_KEY")
            os.environ["ANVIL_API_KEY"] = "unit-test-key"
            port = _free_port()
            thread = threading.Thread(
                target=run_server,
                kwargs={"host": "127.0.0.1", "port": port, "config": CompilerConfig(ledger_path=str(Path(td) / "ledger.sqlite3"))},
                daemon=True,
            )
            try:
                thread.start()
                time.sleep(0.2)
                denied = Request(f"http://127.0.0.1:{port}/health")
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(denied, timeout=5)  # noqa: S310 - local test server only
                self.assertEqual(ctx.exception.code, 401)

                allowed = Request(f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer unit-test-key"})
                with urlopen(allowed, timeout=5) as resp:  # noqa: S310 - local test server only
                    data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data["ok"])
            finally:
                if old_key is None:
                    os.environ.pop("ANVIL_API_KEY", None)
                else:
                    os.environ["ANVIL_API_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
