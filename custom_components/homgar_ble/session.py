"""One GATT sync session with a HomGar BLE sensor, as the HomGar app does it.

The sensor offers a session only while its advert flags ask for a sync. Sequence:
  device 50 04 <challenge>   -> host D0 05 00 <auth sum LE32>
  device 52 ..  (did, home)  -> host D2 0C 00 <slot> E0 01 <home LE32> 00 00 00 00
  device 59 01 02 (time)     -> host D9 06 00 02 <T4 local time LE32>   (sometimes)
  device 54/55 <report>      -> host D4/D5 02 00 <stateVer>
Any other settings request is left unanswered and the session ends.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import logging
import struct

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .parser import decode_records

_LOGGER = logging.getLogger(__name__)

CHAR_WRITE = "4f68a301-b458-c812-9999-43686f75717a"
CHAR_NOTIFY = "4f68a302-b458-c812-9999-43686f75717a"

# Sub-device index the HomGar cloud assigns; 1 for the only BLE device in a home.
SLOT = 1
DP_TIME = 2
SESSION_TIMEOUT = 20


def auth_reply(challenge: bytes, model: int, did: int, pcode: int = 0) -> bytes:
    blob = b"\x91\x91" + bytes([pcode]) + struct.pack("<HI", model, did) + challenge
    total = sum(hashlib.md5(blob.hex().upper().encode()).digest())
    return bytes([0xD0, 5, 0]) + struct.pack("<I", total)


def t4(now: datetime) -> int:
    return (
        now.second
        | now.minute << 6
        | now.hour << 12
        | now.day << 17
        | now.month << 22
        | (now.year - 2020) << 26
    )


async def async_sync(
    device: BLEDevice, model: int, did: int, now: datetime
) -> dict[str, float | int]:
    """Connect, authenticate, collect the status report, disconnect."""
    result: asyncio.Future[dict[str, float | int]] = (
        asyncio.get_running_loop().create_future()
    )
    buf = bytearray()
    client = await establish_connection(
        BleakClientWithServiceCache, device, device.name or device.address
    )

    async def send(data: bytes) -> None:
        _LOGGER.debug("%s: write %s", device.address, data.hex(" "))
        await client.write_gatt_char(CHAR_WRITE, data, response=False)

    async def handle(op: int, p: bytes) -> None:
        if op == 0x50 and len(p) == 4:
            await send(auth_reply(p, model, did))
        elif op == 0x52 and len(p) >= 13:
            await send(bytes([0xD2, 12, 0, SLOT, 0xE0, 0x01]) + p[9:13] + bytes(4))
        elif op == 0x59 and p == bytes([DP_TIME]):
            await send(bytes([0xD9, 6, 0, DP_TIME]) + struct.pack("<I", t4(now)))
        elif op in (0x54, 0x55) and p:
            await send(bytes([op | 0x80, 2, 0, p[0]]))
            if not result.done():
                result.set_result(decode_records(p[1:], with_dp_ids=op == 0x54))
        elif not result.done():
            result.set_exception(
                RuntimeError(f"unexpected frame 0x{op:02x} {p.hex(' ')}")
            )

    def on_notify(_: object, data: bytearray) -> None:
        _LOGGER.debug("%s: notify %s", device.address, data.hex(" "))
        buf.extend(data)
        while len(buf) >= 2 and len(buf) >= 2 + buf[1]:
            op, n = buf[0], buf[1]
            payload = bytes(buf[2 : 2 + n])
            del buf[: 2 + n]
            asyncio.get_running_loop().create_task(handle(op, payload))

    try:
        await client.start_notify(CHAR_NOTIFY, on_notify)
        return await asyncio.wait_for(result, SESSION_TIMEOUT)
    finally:
        await client.disconnect()
