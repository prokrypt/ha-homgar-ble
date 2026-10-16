"""TLV framing and field decoding, checked against the examples in docs/PROTOCOL.md."""

from __future__ import annotations

import random

import pytest

from custom_components.homgar_ble.models import HCS701B
from custom_components.homgar_ble.parser import (
    BAT,
    MAX_RH,
    MAX_TEM,
    RH,
    TEM,
    TREND,
    _parse_tlv,
    _strip_dp_ids,
    decode,
    decode_records,
    device_id,
    temp_f10,
    temp_f10_range,
    u8,
    u8_range,
    wants_sync,
)

from .conftest import ADVERT_RECORDS, DID, payload

FIELDS = HCS701B.fields

# Readings for ADVERT_RECORDS (79.2 degF, 40 %, 78.3-79.5 degF, 39-46 %).
ADVERT_READINGS = {
    "temperature": 26.2,
    "humidity": 40,
    "temperature_min": 25.7,
    "temperature_max": 26.4,
    "humidity_min": 39,
    "humidity_max": 46,
    "battery_level": 1,  # flags 0x15
}

# The 0x55 report example from docs/PROTOCOL.md, after the opcode, length and stateVer bytes.
REPORT_RECORDS = bytes.fromhex("dc 01 85 31 03 88 2a b8 0d e7 26 03 31 03 e9 2a 34")
REPORT_READINGS = {
    "battery_level": 1,
    "temperature": 27.6,  # 81.7 degF
    "humidity": 42,
    "temperature_min": 27.0,  # 80.6 degF
    "temperature_max": 27.6,
    "humidity_min": 42,
    "humidity_max": 52,
}


def with_dp_ids(records: bytes) -> bytes:
    """Re-encode records in the 0x54 format: a dpId byte in front of each record."""
    out = bytearray()
    for dp, start, end in _record_spans(records):
        out += bytes([dp]) + records[start:end]
    return bytes(out)


def _record_spans(records: bytes):
    i, dp = 0, 1
    while i < len(records):
        h = records[i]
        n = 1 if h < 0x80 else 2 + (h & 3)
        yield dp, i, i + n
        i, dp = i + n, dp + 1


def test_tlv_framing_of_the_documented_advert() -> None:
    assert _parse_tlv(ADVERT_RECORDS) == [
        (TEM, bytes.fromhex("1803")),
        (RH, bytes.fromhex("28")),
        (TREND, bytes.fromhex("05")),
        (MAX_TEM, bytes.fromhex("0f031b03")),
        (MAX_RH, bytes.fromhex("272e")),
    ]


def test_tlv_one_byte_and_extended_codes() -> None:
    # h < 0x80: code in bits 4-6, value in the low nibble.
    assert _parse_tlv(b"\x35") == [(3, b"\x05")]
    # Code 39 (header 0xfc-0xff) takes the real code from the next byte, plus 39.
    assert _parse_tlv(bytes([0xFC, 0x02, 0xAA])) == [(41, b"\xaa")]
    assert _parse_tlv(bytes([0xFD, 0x00, 0x01, 0x02])) == [(39, b"\x01\x02")]


def test_tlv_truncated_input_does_not_raise() -> None:
    assert _parse_tlv(b"\xfc") == []
    # A cut-off value comes back short; field decoders reject it.
    assert _parse_tlv(b"\x85\x18") == [(TEM, b"\x18")]
    assert decode_records(b"\x85\x18", FIELDS) == {}


def test_decode_documented_advert() -> None:
    assert decode(payload(), FIELDS) == ADVERT_READINGS


def test_decode_documented_report_0x55() -> None:
    assert decode_records(REPORT_RECORDS, FIELDS) == REPORT_READINGS


def test_decode_report_0x54_with_dp_ids() -> None:
    framed = with_dp_ids(REPORT_RECORDS)
    assert _strip_dp_ids(framed) == REPORT_RECORDS
    assert decode_records(framed, FIELDS, with_dp_ids=True) == REPORT_READINGS


def test_strip_dp_ids_keeps_extended_code_byte() -> None:
    record = bytes([0xFC, 0x02, 0xAA])
    assert _strip_dp_ids(b"\x07" + record) == record


@pytest.mark.parametrize("data", [b"", b"\x01\x02\x03\x04", payload(records=b"")])
def test_beacon_and_header_only_have_no_readings(data: bytes) -> None:
    assert decode(data, FIELDS) == {}


def test_unknown_record_codes_are_ignored() -> None:
    assert decode_records(bytes.fromhex("b8 05 35"), FIELDS) == {}


@pytest.mark.parametrize(("flags", "level"), [(0x15, 1), (0x03, 0), (0x17, 1), (0x25, 2), (0x35, 3)])
def test_battery_from_flags(flags: int, level: int) -> None:
    assert decode(payload(flags=flags), FIELDS)["battery_level"] == level


def test_no_battery_from_flags_for_models_without_it() -> None:
    fields = {code: f for code, f in FIELDS.items() if code != BAT}
    assert "battery_level" not in decode(payload(), fields)


def test_device_id_and_sync_flag() -> None:
    assert device_id(payload()) == DID
    assert device_id(b"\x01\x02\x03") is None
    assert not wants_sync(payload(flags=0x15))
    assert wants_sync(payload(flags=0x17))
    assert wants_sync(payload(flags=0x03))
    # The beacon has no flags byte.
    assert not wants_sync(payload()[:4])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (b"\x18\x03", {"t": 26.2}),
        (b"\x00\x00", {"t": -17.8}),  # 0 degF
        (b"\x9c\xff", {"t": -23.3}),  # -10.0 degF, signed
        (b"\x00\x80", {}),  # -32768: no reading
        (b"\xff\x7f", {}),  # 32767: no reading
        (b"\x18", {}),
    ],
)
def test_temp_f10(value: bytes, expected: dict) -> None:
    assert temp_f10("t")(value) == expected


def test_temp_f10_range_orders_min_and_max() -> None:
    field = temp_f10_range("t")
    assert field(bytes.fromhex("1b030f03")) == {"t_min": 25.7, "t_max": 26.4}
    assert field(bytes.fromhex("0f031b03")) == {"t_min": 25.7, "t_max": 26.4}
    assert field(bytes.fromhex("ff7fff7f")) == {}
    assert field(bytes.fromhex("0f03")) == {}


def test_u8_fields() -> None:
    assert u8("h", invalid=0xFF)(b"\x28") == {"h": 40}
    assert u8("h", invalid=0xFF)(b"\xff") == {}
    assert u8("h")(b"") == {}
    assert u8_range("h", invalid=0xFF)(b"\x2e\x27") == {"h_min": 39, "h_max": 46}
    assert u8_range("h", invalid=0xFF)(b"\xff\xff") == {}
    assert u8_range("h", invalid=0xFF)(b"\x27") == {}


def test_sentinel_min_max_records_are_dropped() -> None:
    """Sentinels used to decode to 1802.6 degC and 255 %."""
    assert decode_records(bytes.fromhex("e7 ff 7f ff 7f e9 ff ff"), FIELDS) == {}


def test_random_payloads_never_raise() -> None:
    """Fuzz: arbitrary bytes give readings of the right type, or nothing, never an error."""
    rng = random.Random(9191)
    keys = set().union(*(f(b"\x01\x02\x03\x04") for f in FIELDS.values()))
    for _ in range(20_000):
        data = rng.randbytes(rng.randrange(0, 40))
        for readings in (
            decode(data, FIELDS),
            decode_records(data, FIELDS),
            decode_records(data, FIELDS, with_dp_ids=True),
        ):
            assert set(readings) <= keys
            assert all(isinstance(v, int | float) for v in readings.values())
        device_id(data)
        wants_sync(data)
