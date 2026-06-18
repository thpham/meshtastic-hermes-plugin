"""Tool handlers — run when the LLM calls a tool.

Contract (per the Hermes plugin guide): every handler takes ``(args, **kwargs)``,
ALWAYS returns a JSON string, and NEVER raises. Errors are returned as
``{"error": ...}`` JSON so the tool loop keeps running.

The ``meshtastic`` radio stack is a hard dependency (normally installed by pip) but
is still import-guarded inside the connection manager, so handlers that need it
surface a friendly install hint instead of crashing on a bare directory-drop install.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from .connection import MeshtasticUnavailable, get_manager
from .observer import get_observer


def _ok(data: Any) -> str:
    return json.dumps(data, default=str)


def _err(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra}, default=str)


def _guard(fn: Callable[[dict], Any]) -> Callable[..., str]:
    """Wrap a handler so it always returns JSON and never raises."""

    def wrapper(args: dict, **kwargs: Any) -> str:  # noqa: ARG001
        try:
            return fn(args or {})
        except MeshtasticUnavailable as exc:
            return _err(str(exc), code="radio_unavailable")
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:  # last-resort safety net
            return _err(f"Unexpected error: {exc}", code="internal")

    return wrapper


def _kb():
    """The KB shared with the receive observer (single source of truth)."""
    return get_observer().kb


# ----------------------------------------------------------------------
# Core messaging
# ----------------------------------------------------------------------


@_guard
def connect(args: dict) -> str:
    host = args.get("host") or os.environ.get("MESHTASTIC_HOST")
    if not host:
        return _err("No host given and MESHTASTIC_HOST is not set.")
    port = int(args.get("port", 4403))
    status = get_manager().connect(host, port)
    return _ok({"status": "connected", **status})


@_guard
def disconnect(args: dict) -> str:
    return _ok(get_manager().disconnect())


@_guard
def send_text(args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return _err("No text provided.")
    iface = get_manager().iface
    kwargs: dict[str, Any] = {"channelIndex": int(args.get("channel_index", 0))}
    if args.get("dest_id"):
        kwargs["destinationId"] = args["dest_id"]
    iface.sendText(text, **kwargs)
    return _ok({"sent": True, "text": text, "channel_index": kwargs["channelIndex"], "dest_id": args.get("dest_id")})


@_guard
def recent_messages(args: dict) -> str:
    limit = int(args.get("limit", 20))
    return _ok({"messages": get_observer().recent_messages(limit)})


# ----------------------------------------------------------------------
# Network inspection
# ----------------------------------------------------------------------


def _node_summary(node_id: str, node: dict[str, Any]) -> dict[str, Any]:
    user = node.get("user") or {}
    pos = node.get("position") or {}
    metrics = node.get("deviceMetrics") or {}
    return {
        "id": node_id,
        "short_name": user.get("shortName"),
        "long_name": user.get("longName"),
        "hw_model": user.get("hwModel"),
        "role": user.get("role"),
        "snr": node.get("snr"),
        "last_heard": node.get("lastHeard"),
        "hops_away": node.get("hopsAway"),
        "battery": metrics.get("batteryLevel"),
        "lat": pos.get("latitude"),
        "lon": pos.get("longitude"),
    }


@_guard
def list_nodes(args: dict) -> str:
    limit = int(args.get("limit", 50))
    nodes = get_manager().iface.nodes or {}
    out = [_node_summary(nid, n) for nid, n in list(nodes.items())[:limit]]
    return _ok({"count": len(out), "nodes": out})


@_guard
def node_info(args: dict) -> str:
    mgr = get_manager()
    nodes = mgr.iface.nodes or {}
    node_id = args.get("node_id") or mgr.my_node_id()
    if not node_id:
        return _err("Could not determine node id.")
    node = nodes.get(node_id)
    if node is None:
        return _err(f"Node {node_id} not found in the radio's node DB.", node_id=node_id)
    return _ok(_node_summary(node_id, node))


@_guard
def list_channels(args: dict) -> str:
    local = get_manager().iface.localNode
    channels = getattr(local, "channels", None) or []
    out = []
    for idx, ch in enumerate(channels):
        settings = getattr(ch, "settings", None)
        role = getattr(ch, "role", None)
        # role: 0=DISABLED, 1=PRIMARY, 2=SECONDARY
        if role == 0:
            continue
        out.append(
            {
                "index": idx,
                "name": getattr(settings, "name", "") or ("Primary" if role == 1 else f"ch{idx}"),
                "role": {0: "DISABLED", 1: "PRIMARY", 2: "SECONDARY"}.get(role, str(role)),
                "has_psk": bool(getattr(settings, "psk", b"")),
            }
        )
    return _ok({"count": len(out), "channels": out})


@_guard
def device_metrics(args: dict) -> str:
    mgr = get_manager()
    node_id = mgr.my_node_id()
    nodes = mgr.iface.nodes or {}
    node = nodes.get(node_id, {}) if node_id else {}
    metrics = node.get("deviceMetrics") or {}
    pos = node.get("position") or {}
    return _ok(
        {
            "node_id": node_id,
            "battery_level": metrics.get("batteryLevel"),
            "voltage": metrics.get("voltage"),
            "channel_utilization": metrics.get("channelUtilization"),
            "air_util_tx": metrics.get("airUtilTx"),
            "uptime_seconds": metrics.get("uptimeSeconds"),
            "lat": pos.get("latitude"),
            "lon": pos.get("longitude"),
            "altitude": pos.get("altitude"),
        }
    )


# ----------------------------------------------------------------------
# Knowledge base
# ----------------------------------------------------------------------


@_guard
def kb_summary(args: dict) -> str:
    return _ok(_kb().summary())


@_guard
def kb_nodes(args: dict) -> str:
    limit = int(args.get("limit", 50))
    sort = args.get("sort", "last_seen")
    return _ok({"nodes": _kb().nodes(limit=limit, sort=sort)})


@_guard
def kb_interactions(args: dict) -> str:
    limit = int(args.get("limit", 100))
    node_id = args.get("node_id")
    since = args.get("since")
    rows = _kb().interactions(node_id=node_id, since=since, limit=limit)
    return _ok({"count": len(rows), "interactions": rows})


@_guard
def kb_neighbors(args: dict) -> str:
    node_id = args.get("node_id")
    if not node_id:
        return _err("node_id is required.")
    limit = int(args.get("limit", 50))
    return _ok({"node_id": node_id, "neighbors": _kb().neighbors(node_id, limit=limit)})
