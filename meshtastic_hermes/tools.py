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
import threading
from typing import Any, Callable

from .connection import MeshtasticUnavailable, get_manager
from .observer import get_observer

# Meshtastic portnum for plain text messages (portnums.proto TEXT_MESSAGE_APP).
_TEXT_MESSAGE_APP = 1


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
    channel_index = int(args.get("channel_index", 0))
    dest_id = args.get("dest_id")
    pki = bool(args.get("pki", False))
    # Reliable delivery by default: the firmware retries and reports ack/nak. Helps
    # messages survive lossy multi-hop links.
    want_ack = bool(args.get("want_ack", True))
    # Block for the ack/nak by default for DIRECTED messages (a single recipient, so
    # the ack is meaningful); broadcasts have no single recipient, so don't block.
    wait_ack = bool(args.get("wait_ack", bool(dest_id) and want_ack))
    ack_timeout = float(args.get("ack_timeout", 15.0))

    if pki and not dest_id:
        return _err("pki=true requires dest_id — public-key encryption is point-to-point.")

    iface = get_manager().iface

    # We send everything via sendData(portNum=TEXT_MESSAGE_APP) — identical on-air to
    # sendText — because only sendData exposes onResponseAckPermitted, needed to have
    # the routing ACK invoke our callback. pkiEncrypted toggles end-to-end encryption.
    send_kwargs: dict[str, Any] = {
        "portNum": _TEXT_MESSAGE_APP,
        "channelIndex": channel_index,
        "wantAck": want_ack,
        "pkiEncrypted": pki,
    }
    if dest_id:
        send_kwargs["destinationId"] = dest_id

    ack: dict[str, Any] | None = None
    if want_ack and wait_ack:
        event = threading.Event()
        captured: dict[str, Any] = {}

        def _on_response(resp: dict) -> None:
            routing = (resp.get("decoded") or {}).get("routing") or {}
            captured["reason"] = routing.get("errorReason", "NONE")
            captured["from"] = resp.get("fromId")
            event.set()

        iface.sendData(
            text.encode("utf-8"),
            onResponse=_on_response,
            onResponseAckPermitted=True,
            **send_kwargs,
        )
        if event.wait(ack_timeout):
            reason = captured.get("reason", "NONE")
            ack = {
                "status": "delivered" if reason == "NONE" else "failed",
                "reason": reason,
                "from": captured.get("from"),
            }
        else:
            ack = {"status": "no_ack", "reason": "TIMEOUT", "timeout_s": ack_timeout}
    else:
        iface.sendData(text.encode("utf-8"), **send_kwargs)

    return _ok(
        {
            "sent": True,
            "encryption": "pki" if pki else "channel",
            "want_ack": want_ack,
            "ack": ack,
            "text": text,
            "channel_index": channel_index,
            "dest_id": dest_id,
        }
    )


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
