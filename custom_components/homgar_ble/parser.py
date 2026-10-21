"""Decode HomGar BLE advert service data (UUID 0x<model>9191) and sync reports.

Frame: 9-byte header, then HomGar TLV records (same format the cloud uses):
  h < 0x80  : 1-byte record, code = (h >> 4) & 7
  h >= 0x80 : code = ((h >> 2) & 31) + 8, value = next (h & 3) + 1 bytes, little-endian
The framing is shared by HomGar devices; what each record code means is per model, so a
model maps the codes it sends to field decoders (see models.py).
Temperatures are degF * 10. A 4-byte payload is a beacon with no readings.
The battery status rides in the advert's flags byte, as the HomGar app reads it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import struct

HEADER_LEN = 9

# Record codes seen so far.
TEM, RH, TREND, BAT, MAX_TEM, MAX_RH = 9, 10, 22, 31, 33, 34

type Readings = dict[str, float | int]
# Turns one record's value bytes into readings (empty if the value is unusable).
type Field = Callable[[bytes], Readings]


def _parse_tlv(b: bytes) -> list[tuple[int, bytes]]:
    i, out = 0, []
    while i < len(b):
        h = b[i]
        if h < 0x80:
            out.append(((h >> 4) & 7, bytes([h & 0x0F])))
            i += 1
            continue
        n = (h & 3) + 1
        code = ((h >> 2) & 31) + 8
        if code == 39:  # extended code in next byte
            i += 1
            if i >= len(b):
                break
            code = b[i] + 39
        out.append((code, b[i + 1 : i + 1 + n]))
        i += 1 + n
    return out


def _strip_dp_ids(b: bytes) -> bytes:
    """Drop the dpId byte in front of each record (0x54 report format)."""
    out, i = bytearray(), 0
    while i + 1 < len(b):
        i += 1  # dpId
        h = b[i]
        n = 1 if h < 0x80 else 2 + (h & 3) + (1 if ((h >> 2) & 31) == 31 else 0)
        out += b[i : i + n]
        i += n
    return bytes(out)


def _f10_to_c(raw: int) -> float:
    return round((raw / 10.0 - 32) * 5 / 9, 1)


def _valid_temp(raw: int) -> bool:
    """S16 extremes are the sensor's 'no reading' markers."""
    return -32768 < raw < 32767


# Field decoders. Each factory takes the reading key(s) it fills in.


def temp_f10(key: str) -> Field:
    """S16 degF * 10, reported in degC."""

    def field(v: bytes) -> Readings:
        if len(v) < 2:
            return {}
        raw = struct.unpack("<h", v[:2])[0]
        return {key: _f10_to_c(raw)} if _valid_temp(raw) else {}

    return field


def temp_f10_range(key: str) -> Field:
    """2 x S16 degF * 10 (min and max, either order) -> key_min, key_max in degC."""

    def field(v: bytes) -> Readings:
        if len(v) < 4:
            return {}
        a, b = struct.unpack("<hh", v[:4])
        if not (_valid_temp(a) and _valid_temp(b)):
            return {}
        return {f"{key}_min": _f10_to_c(min(a, b)), f"{key}_max": _f10_to_c(max(a, b))}

    return field


def u8(key: str, invalid: int | None = None) -> Field:
    """U8, skipped when it equals `invalid`."""

    def field(v: bytes) -> Readings:
        return {key: v[0]} if v and v[0] != invalid else {}

    return field


def u8_range(key: str, invalid: int | None = None) -> Field:
    """2 x U8 (min and max, either order) -> key_min, key_max; skipped if either is `invalid`."""

    def field(v: bytes) -> Readings:
        if len(v) < 2 or invalid in v[:2]:
            return {}
        return {f"{key}_min": min(v[0], v[1]), f"{key}_max": max(v[0], v[1])}

    return field


FLAG_HOME_ID = 0x01
FLAG_WANTS_SYNC = 0x02
# Battery status in bits 4-5, same scale as the BAT record (0/1 normal, higher low).
FLAG_BATTERY = 0x30


def device_id(data: bytes) -> int | None:
    """Device ID (did) from the service data, needed for GATT auth."""
    return struct.unpack("<I", data[:4])[0] if len(data) >= 4 else None


def is_paired(data: bytes) -> bool:
    """Whether the sensor belongs to a HomGar home; an unpaired one sends only its device ID."""
    return len(data) > 4 and bool(data[4] & FLAG_HOME_ID)


def wants_sync(data: bytes) -> bool:
    """Whether the sensor is asking to be connected (it only offers auth then)."""
    return len(data) > 4 and bool(data[4] & FLAG_WANTS_SYNC)


def decode(data: bytes, fields: Mapping[int, Field]) -> Readings:
    """Return readings found in one service-data payload (empty for the beacon)."""
    if len(data) <= HEADER_LEN:
        return {}
    out = decode_records(data[HEADER_LEN:], fields)
    if bat := fields.get(BAT):
        # The app turns these bits into a BAT record for models that have one.
        out.update(bat(bytes([(data[4] & FLAG_BATTERY) >> 4])))
    return out


def decode_records(
    data: bytes, fields: Mapping[int, Field], with_dp_ids: bool = False
) -> Readings:
    """Decode HomGar TLV records (advert body, or a 0x54/0x55 report)."""
    out: Readings = {}
    if with_dp_ids:
        data = _strip_dp_ids(data)
    for code, v in _parse_tlv(data):
        if field := fields.get(code):
            out.update(field(v))
    return out
