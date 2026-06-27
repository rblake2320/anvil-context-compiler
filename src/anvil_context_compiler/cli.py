from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import run_server
from .compiler import AnvilCompiler
from .models import CompileRequest, CompilerConfig, EvidenceDocument, ToolSpec, to_jsonable


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | None, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def cmd_compile(args: argparse.Namespace) -> int:
    config = CompilerConfig(
        total_token_budget=args.budget,
        max_output_tokens=args.max_output_tokens,
        ledger_path=args.ledger,
        max_loaded_tools=args.max_loaded_tools,
    ).clamp()
    docs: list[EvidenceDocument] = []
    for file in args.context_file or []:
        path = Path(file)
        docs.append(EvidenceDocument(text=path.read_text(encoding="utf-8"), source_uri=str(path), title=path.name))
    tools: list[ToolSpec] = []
    if args.tool_file:
        raw_tools = _load_json(args.tool_file)
        tools = [ToolSpec(**item) for item in raw_tools]
    rules = []
    for rule_file in args.rules_file or []:
        rules.extend([line.strip() for line in Path(rule_file).read_text(encoding="utf-8").splitlines() if line.strip()])
    req = CompileRequest(
        request=args.request,
        system_rules=rules,
        evidence=docs,
        tools=tools,
        config=config,
        project_name=args.project,
    )
    result = AnvilCompiler(config).compile(req)
    _write_json(args.out, result.to_dict())
    if args.prompt_out:
        Path(args.prompt_out).write_text(result.prompt_package + "\n", encoding="utf-8")
    return 0


def cmd_rehydrate(args: argparse.Namespace) -> int:
    compiler = AnvilCompiler(CompilerConfig(ledger_path=args.ledger))
    spans = compiler.ledger.rehydrate(args.span_id, max_tokens=args.max_tokens)
    _write_json(args.out, {"spans": [to_jsonable(s) for s in spans]})
    return 0


def cmd_list_spans(args: argparse.Namespace) -> int:
    compiler = AnvilCompiler(CompilerConfig(ledger_path=args.ledger))
    spans = compiler.ledger.list_spans(limit=args.limit)
    _write_json(args.out, {"spans": [to_jsonable(s) for s in spans]})
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = CompilerConfig(ledger_path=args.ledger, total_token_budget=args.budget).clamp()
    run_server(args.host, args.port, config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anvil", description="ANVIL Context Compiler CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="Compile a request into an ANVIL prompt package and execution DAG")
    c.add_argument("--request", required=True)
    c.add_argument("--project", default="default")
    c.add_argument("--context-file", action="append", default=[])
    c.add_argument("--rules-file", action="append", default=[])
    c.add_argument("--tool-file")
    c.add_argument("--budget", type=int, default=12_000)
    c.add_argument("--max-output-tokens", type=int, default=1_200)
    c.add_argument("--max-loaded-tools", type=int, default=8)
    c.add_argument("--ledger", default=".anvil/anvil_ledger.sqlite3")
    c.add_argument("--out")
    c.add_argument("--prompt-out")
    c.set_defaults(func=cmd_compile)

    r = sub.add_parser("rehydrate", help="Restore exact context spans from the ledger")
    r.add_argument("--span-id", action="append", required=True)
    r.add_argument("--max-tokens", type=int)
    r.add_argument("--ledger", default=".anvil/anvil_ledger.sqlite3")
    r.add_argument("--out")
    r.set_defaults(func=cmd_rehydrate)

    ls = sub.add_parser("list-spans", help="List recent context ledger spans")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--ledger", default=".anvil/anvil_ledger.sqlite3")
    ls.add_argument("--out")
    ls.set_defaults(func=cmd_list_spans)

    s = sub.add_parser("serve", help="Run local HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--ledger", default=".anvil/anvil_ledger.sqlite3")
    s.add_argument("--budget", type=int, default=12_000)
    s.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
