"""Observer tests — surfacing decoded text vs. metadata-only for encrypted packets.

Packet shapes mirror real captures, including a received PKI direct message (which
arrives decoded with NO `channel` key, since protobuf omits the zero/default value).
"""

from __future__ import annotations

from meshtastic_hermes.knowledge import NodeGraph
from meshtastic_hermes.observer import Observer


def _obs() -> Observer:
    return Observer(kb=NodeGraph(db_path=":memory:"))


def test_pki_dm_text_is_surfaced():
    obs = _obs()
    # Mirrors the live capture: from=!a696579c to=!0aca4a9c, decoded TEXT, no channel.
    packet = {
        "fromId": "!a696579c",
        "toId": "!0aca4a9c",
        "from": 0xA696579C,
        "to": 0x0ACA4A9C,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Claude", "payload": b"Claude"},
        "rxSnr": -3.0,
        "hopLimit": 3,
        # no "channel" key (channel 0 omitted by protobuf), no "encrypted" key
    }
    obs.on_receive(packet)

    msgs = obs.recent_messages()
    assert len(msgs) == 1
    assert msgs[0]["text"] == "Claude"
    assert msgs[0]["from"] == "!a696579c"
    assert msgs[0]["to"] == "!0aca4a9c"

    # And it is recorded as a readable (non-encrypted) interaction.
    rows = obs.kb.interactions()
    assert rows[0]["encrypted"] == 0
    assert rows[0]["portnum"] == "TEXT_MESSAGE_APP"


def test_undecodable_encrypted_packet_is_metadata_only():
    obs = _obs()
    packet = {
        "fromId": "!da6fffb8",
        "toId": "^all",
        "encrypted": b"\x00\x01\x02\x03",  # no 'decoded' -> we cannot read it
        "channel": 8,
        "rxSnr": 2.0,
    }
    obs.on_receive(packet)

    assert obs.recent_messages() == []  # never surfaced as text
    rows = obs.kb.interactions()
    assert rows[0]["encrypted"] == 1  # logged as metadata only
    assert rows[0]["payload_size"] == 4


def test_recent_messages_newest_first_and_limited():
    obs = _obs()
    for i in range(5):
        obs.on_receive(
            {
                "fromId": "!aaaa0001",
                "toId": "^all",
                "rxTime": 1000 + i,
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": f"m{i}", "payload": b""},
            }
        )
    msgs = obs.recent_messages(limit=2)
    assert [m["text"] for m in msgs] == ["m4", "m3"]  # newest first
