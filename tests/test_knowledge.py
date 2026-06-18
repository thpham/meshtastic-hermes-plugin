"""Unit tests for the knowledge base — no radio required.

These exercise the metadata-only recording path with synthetic packet dicts that
mimic both decoded and encrypted Meshtastic frames.
"""

from __future__ import annotations

import pytest

from meshtastic_hermes.knowledge import BROADCAST_ID, NodeGraph, default_db_path


@pytest.fixture
def kb():
    graph = NodeGraph(db_path=":memory:")
    yield graph
    graph.close()


def _decoded(from_node, to_node, ts, portnum="TEXT_MESSAGE_APP", channel=0):
    return {
        "ts": ts,
        "from_node": from_node,
        "to_node": to_node,
        "channel": channel,
        "portnum": portnum,
        "encrypted": False,
        "hop_limit": 3,
        "rx_snr": 5.5,
        "rx_rssi": -80,
        "payload_size": 12,
    }


def _encrypted(from_node, to_node, ts, channel=8):
    return {
        "ts": ts,
        "from_node": from_node,
        "to_node": to_node,
        "channel": channel,
        "portnum": "ENCRYPTED",
        "encrypted": True,
        "hop_limit": 3,
        "rx_snr": 2.0,
        "rx_rssi": -95,
        "payload_size": 40,
    }


def test_record_decoded_and_encrypted(kb):
    kb.record_packet(_decoded("!aaaa0001", "!aaaa0002", 100.0))
    kb.record_packet(_encrypted("!aaaa0002", BROADCAST_ID, 101.0))

    summary = kb.summary()
    assert summary["nodes"] == 2
    assert summary["packets"] == 2
    assert summary["encrypted_packets"] == 1
    assert summary["decoded_packets"] == 1
    # channel 0 and channel 8 both seen
    assert summary["channels_seen"] == 2


def test_encrypted_metadata_only_no_payload_stored(kb):
    # We record size + flags but never any content/text from encrypted frames.
    kb.record_packet(_encrypted("!bbbb0001", "!bbbb0002", 200.0))
    rows = kb.interactions()
    assert len(rows) == 1
    row = rows[0]
    assert row["encrypted"] == 1
    assert row["payload_size"] == 40
    # Schema has no content/text/payload column — only metadata is persisted.
    assert "text" not in row and "payload" not in row


def test_node_packet_counts_and_sort(kb):
    for i in range(3):
        kb.record_packet(_decoded("!cccc0001", BROADCAST_ID, 300.0 + i))
    kb.record_packet(_decoded("!cccc0002", BROADCAST_ID, 310.0))

    by_packets = kb.nodes(sort="packets")
    assert by_packets[0]["node_id"] == "!cccc0001"
    assert by_packets[0]["packets"] == 3
    assert by_packets[1]["packets"] == 1


def test_neighbors_inference(kb):
    # A -> B twice, C -> A once  => A's neighbors are B (2) and C (1)
    kb.record_packet(_decoded("!a", "!b", 400.0))
    kb.record_packet(_decoded("!a", "!b", 401.0))
    kb.record_packet(_decoded("!c", "!a", 402.0))

    neighbors = kb.neighbors("!a")
    by_peer = {n["peer"]: n["count"] for n in neighbors}
    assert by_peer == {"!b": 2, "!c": 1}


def test_interactions_filter_by_node_and_since(kb):
    kb.record_packet(_decoded("!x", "!y", 500.0))
    kb.record_packet(_decoded("!y", "!z", 600.0))

    only_x = kb.interactions(node_id="!x")
    assert len(only_x) == 1

    recent = kb.interactions(since=550.0)
    assert len(recent) == 1
    assert recent[0]["from_node"] == "!y"


def test_db_path_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_HERMES_DB", "/custom/kb.sqlite")
    monkeypatch.setenv("HERMES_HOME", "/var/lib/hermes/.hermes")
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/hermes")
    assert default_db_path() == "/custom/kb.sqlite"


def test_db_path_uses_hermes_home(monkeypatch):
    # HERMES_HOME is the Hermes-native location (next to its config.yaml).
    monkeypatch.delenv("MESHTASTIC_HERMES_DB", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/var/lib/hermes/.hermes")
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/hermes")  # outranked by HERMES_HOME
    assert default_db_path() == "/var/lib/hermes/.hermes/meshtastic_kb.sqlite"


def test_db_path_uses_systemd_state_directory(monkeypatch):
    monkeypatch.delenv("MESHTASTIC_HERMES_DB", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    # systemd may hand over a colon-separated list; first entry wins.
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/hermes:/var/lib/other")
    assert default_db_path() == "/var/lib/hermes/meshtastic_kb.sqlite"


def test_db_path_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("MESHTASTIC_HERMES_DB", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("STATE_DIRECTORY", raising=False)
    monkeypatch.setenv("HOME", "/home/alice")
    assert default_db_path() == "/home/alice/.hermes/meshtastic_kb.sqlite"


def test_upsert_node_identity_merges_fields(kb):
    kb.upsert_node("!d", 700.0, short_name="DAVE", long_name="Dave Node")
    kb.upsert_node("!d", 710.0, hw_model="TBEAM")  # later frame adds hw, keeps names

    node = kb.nodes()[0]
    assert node["short_name"] == "DAVE"
    assert node["long_name"] == "Dave Node"
    assert node["hw_model"] == "TBEAM"
    assert node["last_seen"] == 710.0
    assert node["first_seen"] == 700.0
