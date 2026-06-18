"""Tests for the inbound/outbound bridge and reply policy (pure, no radio)."""

from __future__ import annotations

from meshtastic_hermes import gateway_bridge as gb

MY = "!0aca4a9c"
PEER = "!a696579c"


def _dm(text="hi", from_id=PEER):
    return {
        "fromId": from_id,
        "toId": MY,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": text, "payload": b""},
    }


def _channel(text="hello all", channel=0):
    return {
        "fromId": PEER,
        "toId": "^all",
        "channel": channel,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": text, "payload": b""},
    }


def _echo(text, inbound):
    return f"re: {text}"


def test_inbound_dm_parsed_and_flagged():
    inb = gb.inbound_from_packet(_dm("yo"), MY)
    assert inb["is_dm"] is True
    assert inb["from_id"] == PEER
    assert inb["text"] == "yo"
    assert gb.chat_id_for(inb) == PEER


def test_inbound_channel_chat_id():
    inb = gb.inbound_from_packet(_channel("hey", channel=1), MY)
    assert inb["is_dm"] is False
    assert gb.chat_id_for(inb) == "ch:1"


def test_ignores_own_messages_and_encrypted_and_nontext():
    assert gb.inbound_from_packet(_dm(from_id=MY), MY) is None  # loop guard
    assert gb.inbound_from_packet({"fromId": PEER, "encrypted": b"\x00"}, MY) is None
    assert gb.inbound_from_packet(
        {"fromId": PEER, "toId": MY, "decoded": {"portnum": "TELEMETRY_APP"}}, MY
    ) is None


def test_outbound_target_dm_is_pki():
    t = gb.outbound_target(PEER)
    assert t == {"dest_id": PEER, "channel_index": 0, "pki": True}


def test_outbound_target_channel_is_broadcast():
    t = gb.outbound_target("ch:2")
    assert t == {"dest_id": None, "channel_index": 2, "pki": False}


def test_process_inbound_replies_to_dm():
    res = gb.process_inbound(_dm("ping"), MY, _echo)
    assert res["action"] == "reply"
    assert res["chat_id"] == PEER
    assert res["reply"] == "re: ping"
    assert res["target"]["pki"] is True


def test_process_inbound_skips_channel_by_default():
    res = gb.process_inbound(_channel("spam"), MY, _echo)
    assert res["action"] == "skip"  # DMs only by default


def test_process_inbound_replies_on_all_channels():
    res = gb.process_inbound(_channel("spam", channel=3), MY, _echo, allowed_channels=gb.ALL_CHANNELS)
    assert res["action"] == "reply"
    assert res["chat_id"] == "ch:3"
    assert res["target"] == {"dest_id": None, "channel_index": 3, "pki": False}


def test_channel_allowlist_dms_plus_private_only():
    # Allow channel 1 (private) but not 0 (public Primary).
    allowed = {1}
    assert gb.process_inbound(_channel("x", channel=1), MY, _echo, allowed_channels=allowed)["action"] == "reply"
    assert gb.process_inbound(_channel("x", channel=0), MY, _echo, allowed_channels=allowed)["action"] == "skip"
    # DMs always reply regardless of the channel allowlist.
    assert gb.process_inbound(_dm("hi"), MY, _echo, allowed_channels=allowed)["action"] == "reply"


def test_parse_channel_spec():
    assert gb.parse_channel_spec(None) is None
    assert gb.parse_channel_spec("") is None
    assert gb.parse_channel_spec("all") == gb.ALL_CHANNELS
    assert gb.parse_channel_spec("1") == {1}
    assert gb.parse_channel_spec("1, 2 ,3") == {1, 2, 3}
    assert gb.parse_channel_spec("x,2") == {2}  # bad entries ignored


def test_process_inbound_ignores_own_message():
    assert gb.process_inbound(_dm(from_id=MY), MY, _echo) is None
