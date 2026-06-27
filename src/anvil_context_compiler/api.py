from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .compiler import AnvilCompiler
from .models import CompilerConfig, to_jsonable


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


class AnvilAPIHandler(BaseHTTPRequestHandler):
    server_version = "ANVILContextCompiler/1.0"

    def _authorized(self) -> bool:
        required = os.getenv("ANVIL_API_KEY", "").strip()
        if not required:
            return True
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {required}"

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 10_000_000:
            raise ValueError("Payload too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return _json_response(self, HTTPStatus.OK, {"ok": True, "service": "anvil-context-compiler"})
        if parsed.path == "/v1/ledger/spans":
            qs = parse_qs(parsed.query)
            limit = int((qs.get("limit") or ["50"])[0])
            compiler = self.server.compiler  # type: ignore[attr-defined]
            spans = compiler.ledger.list_spans(limit=limit)
            return _json_response(self, HTTPStatus.OK, {"spans": [to_jsonable(s) for s in spans]})
        return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            compiler = self.server.compiler  # type: ignore[attr-defined]
            if parsed.path == "/v1/compile":
                result = compiler.compile_from_dict(payload)
                return _json_response(self, HTTPStatus.OK, result.to_dict())
            if parsed.path == "/v1/ledger/rehydrate":
                span_ids = list(payload.get("span_ids", []))
                max_tokens = payload.get("max_tokens")
                spans = compiler.ledger.rehydrate(span_ids, max_tokens=max_tokens)
                return _json_response(self, HTTPStatus.OK, {"spans": [to_jsonable(s) for s in spans]})
            return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as exc:  # Defensive API boundary.
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": type(exc).__name__, "message": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.getenv("ANVIL_HTTP_LOG", "0") == "1":
            super().log_message(format, *args)


def run_server(host: str = "127.0.0.1", port: int = 8787, config: CompilerConfig | None = None) -> None:
    server = ThreadingHTTPServer((host, port), AnvilAPIHandler)
    server.compiler = AnvilCompiler(config or CompilerConfig())  # type: ignore[attr-defined]
    print(f"ANVIL Context Compiler listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ANVIL Context Compiler HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--ledger", default=".anvil/anvil_ledger.sqlite3")
    args = parser.parse_args()
    run_server(args.host, args.port, CompilerConfig(ledger_path=args.ledger))


if __name__ == "__main__":
    main()
