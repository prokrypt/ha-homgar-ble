"""One GATT sync session with a HomGar BLE sensor, as the HomGar app does it.

The sensor offers a session only while its advert flags ask for a sync. Sequence:
  device 50 04 <challenge>   -> host D0 05 00 <auth sum LE32>
  device 52 (did, fw, home)  -> host D2 0C 00 <slot> E0 01 <home LE32> 00 00 00 00
  device 59 01 02 (time)     -> host D9 06 00 02 <T4 local time LE32>   (sometimes)
  device 54/55 <report>      -> host D4/D5 02 00 <stateVer>
Any other request (settings, stats, history) is logged and left unanswered; the
session ends once the report is in, or when the sensor hangs up, or on timeout.

A sensor that was never paired with the app accepts a session at any time and sends
home ID 0; answering with another home ID pairs it with that home.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import logging
import secrets
import struct

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .parser import Field, Readings, decode_records

_LOGGER = logging.getLogger(__name__)

CHAR_WRITE = "4f68a301-b458-c812-9999-43686f75717a"
CHAR_NOTIFY = "4f68a302-b458-c812-9999-43686f75717a"

# Sub-device index the HomGar cloud assigns; 1 for the only BLE device in a home.
SLOT = 1
DP_TIME = 2
SESSION_TIMEOUT = 20
# Time for the final write-without-response (the report ack) to leave the adapter.
ACK_GRACE = 0.5


class SyncError(BleakError):
    """The sensor did not complete the sync handshake."""


def auth_reply(challenge: bytes, model: int, did: int, pcode: int = 0) -> bytes:
    blob = b"\x91\x91" + bytes([pcode]) + struct.pack("<HI", model, did) + challenge
    total = sum(hashlib.md5(blob.hex().upper().encode()).digest())
    return bytes([0xD0, 5, 0]) + struct.pack("<I", total)


def new_home_id() -> int:
    """A home ID for pairing without the app. The sensor stores it and echoes it back
    in later sessions; nothing else checks it."""
    return secrets.randbelow(0x7FFFFFFF) + 1


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
    device: BLEDevice,
    model: int,
    fields: Mapping[int, Field],
    did: int,
    now: datetime,
    home_id: int | None = None,
    ble_device_callback: Callable[[], BLEDevice] | None = None,
) -> Readings:
    """Connect, authenticate, collect the status report, disconnect.

    `model` is the HomGar model code for the auth; `fields` decode the report.
    `home_id` pairs an unpaired sensor with that home; a paired one keeps its own.
    `ble_device_callback` gives each connection attempt the current best path to the sensor.
    The readings also hold "firmware", the version the sensor sent in its 0x52 frame.
    """
    loop = asyncio.get_running_loop()
    result: asyncio.Future[Readings] = loop.create_future()
    frames: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue()
    buf = bytearray()
    firmware: Readings = {}

    def fail(err: BaseException) -> None:
        if not result.done():
            result.set_exception(err)

    def on_disconnect(_: BleakClientWithServiceCache) -> None:
        # The sensor drops the link after ~5 s without a valid auth answer.
        fail(SyncError("sensor closed the connection before sending its report"))

    client = await establish_connection(
        BleakClientWithServiceCache,
        device,
        device.name or device.address,
        disconnected_callback=on_disconnect,
        ble_device_callback=ble_device_callback,
    )

    async def send(data: bytes) -> None:
        _LOGGER.debug("%s: write %s", device.address, data.hex(" "))
        await client.write_gatt_char(CHAR_WRITE, data, response=False)

    async def handle(op: int, p: bytes) -> None:
        if op == 0x50 and len(p) == 4:
            await send(auth_reply(p, model, did))
        elif op == 0x52 and len(p) >= 13:
            firmware["firmware"] = p[8]
            home = p[9:13]
            if home == bytes(4) and home_id is not None:
                home = struct.pack("<I", home_id)
                _LOGGER.debug("%s: pairing with home ID %d", device.address, home_id)
            await send(bytes([0xD2, 12, 0, SLOT, 0xE0, 0x01]) + home + bytes(4))
        elif op == 0x59 and p == bytes([DP_TIME]):
            await send(bytes([0xD9, 6, 0, DP_TIME]) + struct.pack("<I", t4(now)))
        elif op in (0x54, 0x55) and p:
            await send(bytes([op | 0x80, 2, 0, p[0]]))
            if not result.done():
                result.set_result(decode_records(p[1:], fields, with_dp_ids=op == 0x54) | firmware)
        else:
            _LOGGER.debug("%s: ignoring frame 0x%02x %s", device.address, op, p.hex(" "))

    async def consume() -> None:
        # One consumer so replies go out in the order the frames arrived.
        try:
            while True:
                op, payload = await frames.get()
                await handle(op, payload)
        except BleakError as err:
            fail(err)

    def on_notify(_: object, data: bytearray) -> None:
        _LOGGER.debug("%s: notify %s", device.address, data.hex(" "))
        buf.extend(data)
        while len(buf) >= 2 and len(buf) >= 2 + buf[1]:
            op, n = buf[0], buf[1]
            frames.put_nowait((op, bytes(buf[2 : 2 + n])))
            del buf[: 2 + n]

    consumer = loop.create_task(consume())
    try:
        await client.start_notify(CHAR_NOTIFY, on_notify)
        try:
            readings = await asyncio.wait_for(result, SESSION_TIMEOUT)
        except TimeoutError as err:
            raise SyncError(
                f"no report within {SESSION_TIMEOUT} s (is the sensor asking for a sync?)"
            ) from err
        await asyncio.sleep(ACK_GRACE)
        return readings
    finally:
        consumer.cancel()
        result.cancel()  # no-op once it holds the report or an error
        if client.is_connected:
            await client.disconnect()
