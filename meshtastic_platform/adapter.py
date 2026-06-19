"""Meshtastic platform adapter for Hermes Agent (kind: platform).

Makes a Meshtastic LoRa mesh a bidirectional gateway channel: inbound text
messages drive the agent, and the agent's replies are sent back over the radio.
Mirrors the structure of the bundled IRC adapter.

The agent-facing reply policy is DMs-only by default (reply to direct messages
addressed to us), which avoids channel spam and bot-to-bot loops.

Encryption: replies to a DM go out end-to-end (PKI) to the sender's node; replies
on a channel use that channel's key. We never read or reply to traffic we cannot
decrypt.

`gateway.platforms.base` / `gateway.config` only exist inside the Hermes runtime,
so they are imported lazily; outside Hermes this module still imports (the adapter
class and registration simply become no-ops), which keeps it lint/test-friendly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# This adapter imports its sibling package `meshtastic_hermes` (for gateway_bridge,
# connection, tools). When the project is pip-installed both packages are on sys.path
# and this is a no-op. When it's loaded as a *directory-drop* plugin (e.g. the repo
# cloned into ~/.hermes/plugins/), the sibling package lives one level up (repo root)
# and is NOT importable by default — add the repo root so `import meshtastic_hermes`
# works in both layouts.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:  # Available only inside the Hermes gateway runtime.
    from gateway.config import Platform
    from gateway.platforms.base import (
        BasePlatformAdapter,
        MessageEvent,
        MessageType,
        SendResult,
    )

    _HAVE_GATEWAY = True
except Exception:  # pragma: no cover - exercised only outside Hermes
    _HAVE_GATEWAY = False


def _allowed_channels_from_env():
    """Resolve the channel reply-allowlist from env.

    MESHTASTIC_REPLY_ALL=true   -> every channel.
    MESHTASTIC_REPLY_CHANNELS="1,2" -> DMs + those channel indices (your private
                                       channels; public Primary/0 excluded by default).
    Neither                     -> DMs only.
    """
    from meshtastic_hermes import gateway_bridge as gb

    if os.getenv("MESHTASTIC_REPLY_ALL", "").lower() in {"1", "true", "yes"}:
        return gb.ALL_CHANNELS
    return gb.parse_channel_spec(os.getenv("MESHTASTIC_REPLY_CHANNELS"))


if _HAVE_GATEWAY:

    class MeshtasticAdapter(BasePlatformAdapter):
        """Async adapter bridging the radio's threaded RX to the asyncio gateway."""

        def __init__(self, config, **kwargs):
            super().__init__(config=config, platform=Platform("meshtastic"))
            extra = getattr(config, "extra", {}) or {}
            self.host = os.getenv("MESHTASTIC_HOST") or extra.get("host", "")
            self.allowed_channels = _allowed_channels_from_env()
            self._loop: asyncio.AbstractEventLoop | None = None
            self._mgr = None

        @property
        def name(self) -> str:
            return "Meshtastic"

        # ── lifecycle ────────────────────────────────────────────────────
        async def connect(self) -> bool:
            if not self.host:
                self._set_fatal_error(
                    "config_missing",
                    "MESHTASTIC_HOST is not set",
                    retryable=False,
                )
                return False
            self._loop = asyncio.get_running_loop()
            from meshtastic_hermes.connection import get_manager

            self._mgr = get_manager()
            # TCPInterface construction is blocking — keep it off the event loop.
            await self._loop.run_in_executor(None, self._mgr.connect, self.host)

            from pubsub import pub

            pub.subscribe(self._on_rx, "meshtastic.receive")
            self._mark_connected()
            logger.info(
                "Meshtastic adapter connected to %s (node %s, reply allowed_channels=%r)",
                self.host,
                self._mgr.my_node_id(),
                self.allowed_channels,
            )
            return True

        async def disconnect(self) -> None:
            try:
                from pubsub import pub

                pub.unsubscribe(self._on_rx, "meshtastic.receive")
            except Exception:
                pass
            if self._mgr and self._loop:
                await self._loop.run_in_executor(None, self._mgr.disconnect)
            self._mark_disconnected()

        # ── inbound (radio RX thread -> asyncio) ─────────────────────────
        def _on_rx(self, packet, interface=None):
            """pubsub callback on the radio RX thread. Hand off to the loop."""
            try:
                from meshtastic_hermes import gateway_bridge as gb

                inbound = gb.inbound_from_packet(packet, self._mgr.my_node_id())
                if inbound is None:
                    return
                decision = gb.should_reply(inbound, allowed_channels=self.allowed_channels)
                logger.debug(
                    "inbound %s ch=%s from=%s -> %s text=%r",
                    "DM" if inbound["is_dm"] else "channel",
                    inbound["channel"],
                    inbound["from_id"],
                    "REPLY" if decision else "skip (policy)",
                    inbound["text"],
                )
                if not decision:
                    return
                # Cross the thread boundary into the gateway's event loop.
                asyncio.run_coroutine_threadsafe(self._dispatch(inbound), self._loop)
            except Exception:
                logger.exception("Meshtastic adapter: inbound bridge failed")

        async def _dispatch(self, inbound: dict) -> None:
            if not self._message_handler:
                return
            from meshtastic_hermes import gateway_bridge as gb

            chat_id = gb.chat_id_for(inbound)
            source = self.build_source(
                chat_id=chat_id,
                chat_name=inbound["from_id"],
                chat_type="dm" if inbound["is_dm"] else "group",
                user_id=inbound["from_id"],
                user_name=inbound["from_id"],
            )
            event = MessageEvent(
                text=inbound["text"],
                message_type=MessageType.TEXT,
                source=source,
                message_id=inbound["message_id"] or str(int(time.time() * 1000)),
            )
            # Base class routes to the agent handler and calls self.send() with the reply.
            await self.handle_message(event)

        # ── outbound ─────────────────────────────────────────────────────
        async def send(self, chat_id, content, reply_to=None, metadata=None):
            from meshtastic_hermes import gateway_bridge as gb
            from meshtastic_hermes import tools

            target = gb.outbound_target(str(chat_id))

            def _do_send() -> str:
                return tools.send_text(
                    {
                        "text": content,
                        "dest_id": target["dest_id"],
                        "channel_index": target["channel_index"],
                        "pki": target["pki"],
                        "wait_ack": False,  # the gateway shouldn't block on radio acks
                    }
                )

            logger.debug("sending reply to chat_id=%s target=%s", chat_id, target)
            raw = await self._loop.run_in_executor(None, _do_send)
            data = json.loads(raw)
            if data.get("error"):
                logger.warning("Meshtastic reply to %s failed: %s", chat_id, data["error"])
                return SendResult(success=False, error=data["error"])
            logger.info("Meshtastic reply sent to %s", chat_id)
            return SendResult(success=True, message_id=str(int(time.time() * 1000)))

        async def get_chat_info(self, chat_id):
            return {
                "name": chat_id,
                "type": "group" if str(chat_id).startswith("ch:") else "dm",
            }


# ── plugin registration ──────────────────────────────────────────────────
def check_requirements() -> bool:
    return bool(os.getenv("MESHTASTIC_HOST"))


def validate_config(config) -> bool:
    extra = getattr(config, "extra", {}) or {}
    return bool(os.getenv("MESHTASTIC_HOST") or extra.get("host"))


def _env_enablement():
    host = os.getenv("MESHTASTIC_HOST")
    if not host:
        return None
    return {"host": host}


def register(ctx):
    """Plugin entry point: called once by the Hermes plugin system."""
    from meshtastic_hermes.connection import enable_debug_logging

    enable_debug_logging()  # honors MESHTASTIC_DEBUG

    # Bundle skills (loaded as `meshtastic-platform:<name>`), independent of whether the
    # gateway runtime is present.
    from pathlib import Path

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)

    if not _HAVE_GATEWAY:
        logger.warning("gateway.platforms.base unavailable — Meshtastic platform not registered")
        return

    # Make the dormant-vs-active state visible: the gateway only creates+connects the
    # adapter when MESHTASTIC_HOST is set (check_fn/env_enablement gate on it). Use
    # WARNING for the unset case so it shows at the gateway's default log level (INFO
    # would be hidden unless MESHTASTIC_DEBUG raised it).
    host = os.getenv("MESHTASTIC_HOST")
    if host:
        logger.info(
            "meshtastic-platform registered (MESHTASTIC_HOST=%s, reply allowed_channels=%r)",
            host,
            _allowed_channels_from_env(),
        )
    else:
        logger.warning(
            "meshtastic-platform registered but MESHTASTIC_HOST is unset — the adapter will "
            "stay dormant (no radio connection). Set MESHTASTIC_HOST in ~/.hermes/.env."
        )

    ctx.register_platform(
        name="meshtastic",
        label="Meshtastic",
        adapter_factory=lambda cfg: MeshtasticAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=["MESHTASTIC_HOST"],
        install_hint="pip install meshtastic-hermes-plugin (bundles the meshtastic radio stack)",
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="MESHTASTIC_HOST",
        max_message_length=200,  # LoRa payloads are tiny
        emoji="📡",
        platform_hint=(
            "You are chatting over a Meshtastic LoRa mesh. Bandwidth is extremely "
            "limited (~200 bytes per message) and high-latency — keep replies very "
            "short and plain text (no markdown). Direct messages are end-to-end "
            "encrypted; channel messages are encrypted only with a shared channel key."
        ),
    )
