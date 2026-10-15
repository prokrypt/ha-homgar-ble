"""Decode HomGar/RainPoint HCS701B advert service data (UUID 0x01469191).

Frame: 9-byte header, then HomGar TLV records (same format the cloud uses):
  h < 0x80  : 1-byte record, code = (h >> 4) & 7
  h >= 0x80 : code = ((h >> 2) & 31) + 8, value = next (h & 3) + 1 bytes, little-endian
Temperatures are degF * 10. The sensor also sends a 4-byte beacon with no readings.
"""

from __future__ import annotations

import struct

HEADER_LEN = 9

TEM, RH, TREND, BAT, MAX_TEM, MAX_RH = 9, 10, 22, 31, 33, 34


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


FLAG_WANTS_SYNC = 0x02


def device_id(data: bytes) -> int | None:
    """Device ID (did) from the service data, needed for GATT auth."""
    return struct.unpack("<I", data[:4])[0] if len(data) >= 4 else None


def wants_sync(data: bytes) -> bool:
    """Whether the sensor is asking to be connected (it only offers auth then)."""
    return len(data) > 4 and bool(data[4] & FLAG_WANTS_SYNC)


def decode(data: bytes) -> dict[str, float | int]:
    """Return readings found in one service-data payload (empty for the beacon)."""
    if len(data) <= HEADER_LEN:
        return {}
    return decode_records(data[HEADER_LEN:])


def decode_records(data: bytes, with_dp_ids: bool = False) -> dict[str, float | int]:
    """Decode HomGar TLV records (advert body, or a 0x54/0x55 report)."""
    out: dict[str, float | int] = {}
    if with_dp_ids:
        data = _strip_dp_ids(data)
    for code, v in _parse_tlv(data):
        if code == TEM and len(v) >= 2:
            raw = struct.unpack("<h", v[:2])[0]
            if -32768 < raw < 32767:
                out["temperature"] = _f10_to_c(raw)
        elif code == RH and v and v[0] != 0xFF:
            out["humidity"] = v[0]
        elif code == MAX_TEM and len(v) >= 4:
            a, b = struct.unpack("<hh", v[:4])
            out["temperature_min"] = _f10_to_c(min(a, b))
            out["temperature_max"] = _f10_to_c(max(a, b))
        elif code == MAX_RH and len(v) >= 2:
            out["humidity_min"] = min(v[0], v[1])
            out["humidity_max"] = max(v[0], v[1])
        elif code == BAT and v:
            out["battery_level"] = v[0]
    return out
