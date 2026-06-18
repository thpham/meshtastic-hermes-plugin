"""Standalone harness — exercise the plugin WITHOUT a running Hermes agent.

It registers the plugin through a fake Hermes context (so registration, schemas,
hooks and the real tool handlers are all exercised), then lets you invoke tools
directly. The ``meshtastic_kb_*`` tools work fully offline; connecting/observing
needs a reachable Meshtastic node over TCP.

Note: each invocation is a fresh process, so the live connection (an in-process
singleton) does NOT carry across separate `call` runs. Use `repl` for stateful
flows (connect once, then send/read), or `observe` for a one-shot capture.

Usage:
    python -m meshtastic_hermes list
    python -m meshtastic_hermes call meshtastic_kb_summary
    python -m meshtastic_hermes repl 192.168.55.73
    python -m meshtastic_hermes observe 192.168.55.73 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from . import register


class FakeContext:
    """Minimal stand-in for the Hermes registration context.

    Captures everything ``register(ctx)`` wires up so the harness can dispatch
    tools and (optionally) fire hooks exactly as Hermes would.
    """

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict[str, Any]] = {}
        self.cli_commands: dict[str, dict[str, Any]] = {}

    def register_tool(self, name, toolset, schema, handler, **_kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, event, fn):
        self.hooks.setdefault(event, []).append(fn)

    def register_command(self, name, handler, description=""):
        self.commands[name] = {"handler": handler, "description": description}

    def register_cli_command(self, name, help="", setup_fn=None, handler_fn=None):  # noqa: A002
        self.cli_commands[name] = {"help": help, "setup_fn": setup_fn, "handler_fn": handler_fn}


def build_registry() -> FakeContext:
    """Run the plugin's real ``register(ctx)`` against a fake context."""
    ctx = FakeContext()
    register(ctx)
    return ctx


def _pretty(result: str) -> str:
    """Tool handlers return JSON strings; pretty-print when possible."""
    try:
        return json.dumps(json.loads(result), indent=2)
    except (ValueError, TypeError):
        return str(result)


def _cmd_list(ctx: FakeContext, _args) -> int:
    for name, tool in ctx.tools.items():
        desc = (tool["schema"].get("description") or "").strip().splitlines()
        print(f"{name}\n    {desc[0] if desc else ''}")
    hooks = sum(len(v) for v in ctx.hooks.values())
    print(
        f"\n{len(ctx.tools)} tools, {hooks} hooks, "
        f"{len(ctx.commands)} slash command(s), {len(ctx.cli_commands)} CLI command(s)"
    )
    return 0


def _cmd_call(ctx: FakeContext, args) -> int:
    tool = ctx.tools.get(args.tool)
    if tool is None:
        print(json.dumps({"error": f"unknown tool {args.tool!r}", "available": sorted(ctx.tools)}))
        return 1
    try:
        payload = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON args: {exc}"}))
        return 1
    print(_pretty(tool["handler"](payload)))
    return 0


def _cmd_observe(ctx: FakeContext, args) -> int:
    def call(name: str, payload: dict | None = None) -> str:
        return ctx.tools[name]["handler"](payload or {})

    print(_pretty(call("meshtastic_connect", {"host": args.host})))
    print(f"Observing {args.host} for {args.seconds}s (Ctrl-C to stop early)...", file=sys.stderr)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    for tool in ("meshtastic_list_nodes", "meshtastic_recent_messages", "meshtastic_kb_summary"):
        print(f"\n# {tool}")
        print(_pretty(call(tool)))
    call("meshtastic_disconnect")
    return 0


def _cmd_repl(ctx: FakeContext, args) -> int:
    def call(name: str, payload: dict | None = None) -> str:
        return ctx.tools[name]["handler"](payload or {})

    host = args.host or os.environ.get("MESHTASTIC_HOST")
    if host:
        print(_pretty(call("meshtastic_connect", {"host": host})))

    print(
        "Interactive REPL — the connection persists across calls in this one process.\n"
        "  <tool> [json-args]   e.g.  meshtastic_send_text {\"text\": \"hi\"}\n"
        "  help | quit",
        file=sys.stderr,
    )
    while True:
        try:
            line = input("meshtastic> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        if line in ("help", "?"):
            _cmd_list(ctx, args)
            continue
        name, _, raw = line.partition(" ")
        if name not in ctx.tools:
            print(json.dumps({"error": f"unknown tool {name!r}", "available": sorted(ctx.tools)}))
            continue
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"invalid JSON args: {exc}"}))
            continue
        print(_pretty(call(name, payload)))

    try:
        call("meshtastic_disconnect")
    except Exception:
        pass
    return 0


def main(argv=None) -> int:
    ctx = build_registry()
    parser = argparse.ArgumentParser(
        prog="meshtastic_hermes", description="Standalone harness for the Meshtastic Hermes plugin"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List registered tools, hooks and commands")
    p_call = sub.add_parser("call", help="Call a tool with optional JSON args")
    p_call.add_argument("tool")
    p_call.add_argument("args", nargs="?", default="", help="JSON object, e.g. '{\"limit\": 5}'")
    p_obs = sub.add_parser("observe", help="Connect to a node, observe traffic, dump nodes/KB")
    p_obs.add_argument("host")
    p_obs.add_argument("seconds", nargs="?", type=int, default=30)
    p_repl = sub.add_parser("repl", help="Interactive shell with a persistent connection")
    p_repl.add_argument("host", nargs="?", help="Auto-connect on start (else MESHTASTIC_HOST)")

    ns = parser.parse_args(argv)
    dispatch = {
        "list": _cmd_list,
        "call": _cmd_call,
        "observe": _cmd_observe,
        "repl": _cmd_repl,
    }
    return dispatch[ns.cmd](ctx, ns)


if __name__ == "__main__":
    raise SystemExit(main())
