"""Tool-handler tests using a fake interface injected into the ConnectionManager.

Covers the send paths (channel-PSK vs PKI), wantAck default/override, and the
synchronous delivery-ack (onResponse) capture — without needing a radio.
"""

from __future__ import annotations

import json
import logging

from meshtastic_hermes import connection, tools


def test_enable_debug_logging_toggle(monkeypatch):
    lg = logging.getLogger("meshtastic_hermes")
    saved_handlers, saved_propagate = list(lg.handlers), lg.propagate
    try:
        monkeypatch.delenv("MESHTASTIC_DEBUG", raising=False)
        assert connection.enable_debug_logging() is False

        monkeypatch.setenv("MESHTASTIC_DEBUG", "1")
        assert connection.enable_debug_logging() is True
        assert any(getattr(h, "_mesh_debug", False) for h in lg.handlers)
        # idempotent — a second call must not add a duplicate handler
        connection.enable_debug_logging()
        assert sum(getattr(h, "_mesh_debug", False) for h in lg.handlers) == 1
    finally:
        lg.handlers[:] = saved_handlers
        lg.propagate = saved_propagate
        pl = logging.getLogger("meshtastic_platform")
        pl.handlers[:] = [h for h in pl.handlers if not getattr(h, "_mesh_debug", False)]
        pl.propagate = True


class FakeIface:
    """Records sendData calls and optionally simulates the firmware's routing ack.

    `ack_reason=None` means "never call onResponse" (simulates a lost/no ack).
    """

    def __init__(self, ack_reason="NONE"):
        self.sendData_calls = []
        self.myInfo = None
        self._ack_reason = ack_reason

    def sendData(self, data, **kw):
        self.sendData_calls.append((data, kw))
        cb = kw.get("onResponse")
        if cb is not None and self._ack_reason is not None:
            cb({
                "fromId": kw.get("destinationId"),
                "decoded": {"routing": {"errorReason": self._ack_reason}},
            })


def _inject(monkeypatch, iface):
    monkeypatch.setattr(connection.get_manager(), "_iface", iface)
    return iface


def test_broadcast_uses_senddata_no_ack_wait(monkeypatch):
    fake = _inject(monkeypatch, FakeIface())
    res = json.loads(tools.send_text({"text": "hi", "channel_index": 1}))
    assert res["sent"] is True
    assert res["want_ack"] is True
    assert res["encryption"] == "channel"
    assert res["ack"] is None  # broadcasts don't block for an ack
    data, kw = fake.sendData_calls[0]
    assert data == b"hi"
    assert kw["channelIndex"] == 1
    assert kw["wantAck"] is True
    assert kw["pkiEncrypted"] is False
    assert "destinationId" not in kw  # broadcast
    assert "onResponse" not in kw     # no ack wait for broadcast


def test_dm_pki_waits_and_reports_delivered(monkeypatch):
    fake = _inject(monkeypatch, FakeIface(ack_reason="NONE"))
    res = json.loads(tools.send_text({"text": "secret", "dest_id": "!a696579c", "pki": True}))
    assert res["encryption"] == "pki"
    assert res["ack"]["status"] == "delivered"
    data, kw = fake.sendData_calls[0]
    assert data == b"secret"
    assert kw["destinationId"] == "!a696579c"
    assert kw["pkiEncrypted"] is True
    assert kw["wantAck"] is True
    assert kw["onResponseAckPermitted"] is True


def test_dm_reports_failure_on_nak(monkeypatch):
    _inject(monkeypatch, FakeIface(ack_reason="MAX_RETRANSMIT"))
    res = json.loads(tools.send_text({"text": "x", "dest_id": "!a696579c"}))
    assert res["ack"]["status"] == "failed"
    assert res["ack"]["reason"] == "MAX_RETRANSMIT"


def test_dm_reports_no_ack_on_timeout(monkeypatch):
    _inject(monkeypatch, FakeIface(ack_reason=None))  # never acks
    res = json.loads(tools.send_text({"text": "x", "dest_id": "!a696579c", "ack_timeout": 0.1}))
    assert res["ack"]["status"] == "no_ack"
    assert res["ack"]["reason"] == "TIMEOUT"


def test_want_ack_false_disables_reliability(monkeypatch):
    fake = _inject(monkeypatch, FakeIface())
    res = json.loads(tools.send_text({"text": "yo", "want_ack": False}))
    assert res["want_ack"] is False
    assert res["ack"] is None
    _, kw = fake.sendData_calls[0]
    assert kw["wantAck"] is False
    assert "onResponse" not in kw


def test_pki_requires_dest(monkeypatch):
    _inject(monkeypatch, FakeIface())
    res = json.loads(tools.send_text({"text": "hi", "pki": True}))
    assert "requires dest_id" in res["error"]
