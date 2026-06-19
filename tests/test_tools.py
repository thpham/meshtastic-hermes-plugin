"""Tool-handler tests using a fake interface injected into the ConnectionManager.

Covers the send paths (channel-PSK vs PKI), wantAck default/override, and the
synchronous delivery-ack (onResponse) capture — without needing a radio.
"""

from __future__ import annotations

import json
import logging

from meshtastic_hermes import connection, tools


def test_enable_debug_logging_toggle(monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        monkeypatch.delenv("MESHTASTIC_DEBUG", raising=False)
        assert connection.enable_debug_logging() is False

        monkeypatch.setenv("MESHTASTIC_DEBUG", "1")
        assert connection.enable_debug_logging() is True
        mesh = [h for h in root.handlers if getattr(h, "_mesh_debug", False)]
        assert len(mesh) == 1
        # idempotent — a second call must not add a duplicate handler
        connection.enable_debug_logging()
        assert sum(getattr(h, "_mesh_debug", False) for h in root.handlers) == 1

        # The handler emits only meshtastic records (works for the mangled name too).
        h = mesh[0]
        yes = logging.LogRecord(
            "hermes_plugins.x__meshtastic_platform.adapter", logging.INFO, "", 0, "m", None, None
        )
        gw = logging.LogRecord("gateway.run", logging.INFO, "", 0, "m", None, None)
        lib = logging.LogRecord("meshtastic.mesh_interface", logging.DEBUG, "", 0, "m", None, None)
        assert h.filter(yes)          # our plugin (mangled name) passes
        assert not h.filter(gw)       # unrelated logger excluded
        assert not h.filter(lib)      # noisy radio library excluded
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


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


def test_close_locked_preserves_target_host(monkeypatch):
    # Regression: _close_locked must NOT clear _host/_port — _open() reads them right
    # after calling _close_locked(), so nulling them made it connect to None.
    mgr = connection.ConnectionManager()
    mgr._host = "192.168.55.73"
    mgr._port = 4403
    mgr._close_locked()
    assert mgr._host == "192.168.55.73"
    assert mgr._port == 4403


def test_supervisor_lifecycle(monkeypatch):
    # connect() starts a maintained connection (supervisor) without a real radio;
    # disconnect() stops it. _open is stubbed to "succeed".
    mgr = connection.ConnectionManager()
    monkeypatch.setattr(mgr, "_open", lambda: setattr(mgr, "_iface", object()))
    st = mgr.connect("1.2.3.4")
    try:
        assert st["connected"] is True
        assert mgr._want_connected is True
        assert mgr._supervisor is not None and mgr._supervisor.is_alive()
    finally:
        mgr.disconnect()
    assert mgr._want_connected is False
    mgr._supervisor.join(timeout=5)
    assert not mgr._supervisor.is_alive()


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
