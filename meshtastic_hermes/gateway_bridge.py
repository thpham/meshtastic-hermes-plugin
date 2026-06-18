"""Bridge between Meshtastic packets and a normalized chat model.

Shared by the Hermes platform adapter ([meshtastic_platform]) and the REPL
simulator, so both map inbound radio text and outbound replies identically. These
are pure functions — no radio and no Hermes imports — so the routing/reply policy
is unit-testable without hardware.

`chat_id` scheme (a stable conversation identifier the agent/gateway keys on):
  - Direct message  -> the peer node id, e.g. "!a696579c"
  - Channel message -> "ch:<index>",   e.g. "ch:0"
"""

from __future__ import annotations

from typing import Any, Callable

# A responder turns inbound text (+ context) into a reply string. In the Hermes
# adapter the gateway/LLM plays this role; in the simulator it's a local stub.
Responder = Callable[[str, dict], str]


def normalize_node(num: Any) -> str:
    """Normalize a numeric node address to Meshtastic's !hex form."""
    if num is None:
        return ""
    if isinstance(num, str):
        return num
    try:
        return f"!{int(num):08x}"
    except (ValueError, TypeError):
        return str(num)


def inbound_from_packet(packet: dict, my_node_id: str | None) -> dict | None:
    """Normalize a received packet into an inbound message, or None to ignore it.

    Returns None for: non-text, undecodable/encrypted frames, and our own
    transmissions (loop guard). Only messages we are entitled to read surface here.
    """
    if "decoded" not in packet:
        return None  # encrypted / not for us — never auto-reply to opaque traffic
    decoded = packet.get("decoded") or {}
    if decoded.get("portnum") != "TEXT_MESSAGE_APP":
        return None

    from_id = packet.get("fromId") or normalize_node(packet.get("from"))
    if my_node_id and from_id == my_node_id:
        return None  # ignore our own echoed messages

    text = decoded.get("text")
    if text is None:
        payload = decoded.get("payload")
        if isinstance(payload, (bytes, bytearray)):
            text = payload.decode("utf-8", "replace")
    if not text:
        return None

    to_id = packet.get("toId") or normalize_node(packet.get("to"))
    is_dm = bool(my_node_id) and to_id == my_node_id
    return {
        "text": text,
        "from_id": from_id,
        "to_id": to_id,
        "channel": packet.get("channel") or 0,
        "is_dm": is_dm,
        "message_id": str(packet.get("id") or ""),
    }


def chat_id_for(inbound: dict) -> str:
    """Stable conversation id: peer node for DMs, 'ch:<index>' for channels."""
    return inbound["from_id"] if inbound["is_dm"] else f"ch:{inbound['channel']}"


def outbound_target(chat_id: str) -> dict:
    """Map a chat_id back to radio send params: dest_id, channel_index, pki.

    DM chat ids (node ids) reply end-to-end encrypted (pki); channel ids reply as
    a channel broadcast.
    """
    if chat_id.startswith("ch:"):
        try:
            channel_index = int(chat_id[3:])
        except ValueError:
            channel_index = 0
        return {"dest_id": None, "channel_index": channel_index, "pki": False}
    return {"dest_id": chat_id, "channel_index": 0, "pki": True}


# Sentinel for "reply on every channel" (vs. None = no channels, or a set of indices).
ALL_CHANNELS = "__all__"


def parse_channel_spec(spec: Any) -> set[int] | str | None:
    """Parse a channel-allowlist spec into None | set[int] | ALL_CHANNELS.

    - None or ""        -> None          (DMs only)
    - "all"             -> ALL_CHANNELS  (every channel)
    - "1,2" / "1, 2"    -> {1, 2}        (those channel indices)
    """
    if spec is None:
        return None
    text = str(spec).strip().lower()
    if not text:
        return None
    if text == "all":
        return ALL_CHANNELS
    out: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if part:
            try:
                out.add(int(part))
            except ValueError:
                continue
    return out or None


def should_reply(inbound: dict, *, allowed_channels: set[int] | str | None = None) -> bool:
    """Reply policy: always reply to DMs; reply on a channel only if it's allowed.

    ``allowed_channels``: None = DMs only; a set of indices = DMs + those channels
    (e.g. your private channels, excluding public Primary); ALL_CHANNELS = any channel.
    This keeps the public Primary channel (index 0) silent unless explicitly opted in.
    """
    if inbound["is_dm"]:
        return True
    if allowed_channels is None:
        return False
    if allowed_channels == ALL_CHANNELS:
        return True
    return inbound["channel"] in allowed_channels


def process_inbound(
    packet: dict,
    my_node_id: str | None,
    responder: Responder,
    *,
    allowed_channels: set[int] | str | None = None,
) -> dict | None:
    """End-to-end routing decision for one packet (pure; no I/O).

    Returns None to ignore, or a dict with ``action``:
      - {"action": "skip", "inbound": ...}  — readable but policy says don't reply
      - {"action": "reply", "inbound", "chat_id", "reply", "target"} — should reply
    """
    inbound = inbound_from_packet(packet, my_node_id)
    if inbound is None:
        return None
    if not should_reply(inbound, allowed_channels=allowed_channels):
        return {"action": "skip", "inbound": inbound}
    chat_id = chat_id_for(inbound)
    return {
        "action": "reply",
        "inbound": inbound,
        "chat_id": chat_id,
        "reply": responder(inbound["text"], inbound),
        "target": outbound_target(chat_id),
    }
