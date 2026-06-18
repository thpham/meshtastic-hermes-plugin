"""Tool-handler tests using a fake interface injected into the ConnectionManager.

Covers the send paths (channel-PSK vs PKI) and the wantAck default/override without
needing a radio.
"""

from __future__ import annotations

import json

import pytest

from meshtastic_hermes import connection, tools


class FakeIface:
    def __init__(self):
        self.sendText_calls = []
        self.sendData_calls = []
        self.myInfo = None

    def sendText(self, text, **kw):
        self.sendText_calls.append((text, kw))

    def sendData(self, data, **kw):
        self.sendData_calls.append((data, kw))


@pytest.fixture
def fake_iface(monkeypatch):
    iface = FakeIface()
    # Inject into the process-wide ConnectionManager singleton; monkeypatch restores.
    monkeypatch.setattr(connection.get_manager(), "_iface", iface)
    return iface


def test_send_text_wantack_defaults_true(fake_iface):
    res = json.loads(tools.send_text({"text": "hi", "channel_index": 1}))
    assert res["sent"] is True
    assert res["want_ack"] is True
    assert res["encryption"] == "channel"
    text, kw = fake_iface.sendText_calls[0]
    assert text == "hi"
    assert kw["wantAck"] is True
    assert kw["channelIndex"] == 1


def test_send_text_wantack_can_be_disabled(fake_iface):
    json.loads(tools.send_text({"text": "yo", "want_ack": False}))
    _, kw = fake_iface.sendText_calls[0]
    assert kw["wantAck"] is False


def test_send_text_pki_uses_senddata_with_ack(fake_iface):
    res = json.loads(tools.send_text({"text": "secret", "dest_id": "!a696579c", "pki": True}))
    assert res["encryption"] == "pki"
    assert res["want_ack"] is True
    assert fake_iface.sendText_calls == []  # PKI must NOT go through sendText
    data, kw = fake_iface.sendData_calls[0]
    assert data == b"secret"
    assert kw["destinationId"] == "!a696579c"
    assert kw["pkiEncrypted"] is True
    assert kw["wantAck"] is True
