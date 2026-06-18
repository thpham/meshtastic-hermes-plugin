"""Receive observer: turns raw mesh packets into KB rows + a recent-text buffer.

Subscribed to the ``meshtastic.receive`` pubsub topic. Every packet — decoded or
encrypted — contributes metadata to the knowledge base. Only packets we are
actually entitled to read (decoded TEXT_MESSAGE_APP frames on our channels) have
their text surfaced in the in-memory recent-messages buffer; encrypted packets
contribute metadata only, never content.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from . import knowledge

_RECENT_MAXLEN = 200


def _node_id(num: Any) -> str:
    """Normalize a numeric node address to Meshtastic's !hex form."""
    if num is None:
        return ""
    if isinstance(num, str):
        return num
    try:
        return f"!{int(num):08x}"
    except (ValueError, TypeError):
        return str(num)


class Observer:
    def __init__(self, kb: knowledge.NodeGraph | None = None):
        self.kb = kb or knowledge.NodeGraph()
        self._recent: deque[dict[str, Any]] = deque(maxlen=_RECENT_MAXLEN)
        self._lock = threading.Lock()

    def on_receive(self, packet: dict[str, Any], interface=None) -> None:  # noqa: ARG002
        """Pubsub callback. Must never raise (would break the receive thread)."""
        try:
            self._handle(packet)
        except Exception:
            # Swallow — a single malformed packet must not kill the listener.
            pass

    def _handle(self, packet: dict[str, Any]) -> None:
        decoded = packet.get("decoded") or {}
        is_encrypted = "decoded" not in packet or bool(packet.get("encrypted"))
        from_node = packet.get("fromId") or _node_id(packet.get("from"))
        to_node = packet.get("toId") or _node_id(packet.get("to")) or knowledge.BROADCAST_ID
        portnum = decoded.get("portnum")
        payload = decoded.get("payload") or packet.get("encrypted") or b""
        ts = packet.get("rxTime") or time.time()

        self.kb.record_packet(
            {
                "ts": float(ts),
                "from_node": from_node,
                "to_node": to_node,
                "channel": packet.get("channel"),
                "portnum": portnum if not is_encrypted else "ENCRYPTED",
                "encrypted": is_encrypted,
                "hop_limit": packet.get("hopLimit"),
                "rx_snr": packet.get("rxSnr"),
                "rx_rssi": packet.get("rxRssi"),
                "payload_size": len(payload) if payload else 0,
            }
        )

        # Enrich node identity from NODEINFO frames when available.
        if portnum == "NODEINFO_APP":
            user = decoded.get("user") or {}
            self.kb.upsert_node(
                from_node,
                float(ts),
                num=packet.get("from"),
                short_name=user.get("shortName"),
                long_name=user.get("longName"),
                hw_model=user.get("hwModel"),
                role=user.get("role"),
            )

        # Surface decoded text only — never decrypt or store encrypted content.
        if not is_encrypted and portnum == "TEXT_MESSAGE_APP":
            text = decoded.get("text")
            if text is None and isinstance(payload, (bytes, bytearray)):
                try:
                    text = payload.decode("utf-8", "replace")
                except Exception:
                    text = None
            with self._lock:
                self._recent.append(
                    {
                        "ts": float(ts),
                        "from": from_node,
                        "to": to_node,
                        "channel": packet.get("channel"),
                        "text": text,
                    }
                )

    def recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        return items[-limit:][::-1]


# Process-wide singleton, sharing the KB with tool handlers.
_OBSERVER: Observer | None = None


def get_observer() -> Observer:
    global _OBSERVER
    if _OBSERVER is None:
        _OBSERVER = Observer()
    return _OBSERVER
