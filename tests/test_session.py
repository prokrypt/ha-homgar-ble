"""The GATT sync session, against a scripted fake sensor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import hashlib
import struct
from typing import Any
from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from custom_components.homgar_ble import session
from custom_components.homgar_ble.models import HCS701B
from custom_components.homgar_ble.session import (
    CHAR_NOTIFY,
    CHAR_WRITE,
    SyncError,
    async_sync,
    auth_reply,
    new_home_id,
    t4,
)

from .conftest import DID, HOME_ID, ble_device
from .test_parser import REPORT_READINGS, REPORT_RECORDS, with_dp_ids

NOW = datetime(2026, 10, 15, 3, 26, 53)
CHALLENGE = bytes([1, 2, 3, 4])
STATE_VER = 0x01


def frame(op: int, payload: bytes) -> bytes:
    return bytes([op, len(payload)]) + payload


def expected_auth(challenge: bytes) -> bytes:
    """The auth answer, written out from the formula in docs/PROTOCOL.md."""
    blob = b"\x91\x91\x00" + struct.pack("<HI", HCS701B.code, DID) + challenge
    total = sum(hashlib.md5(blob.hex().upper().encode()).digest())
    return b"\xd0\x05\x00" + struct.pack("<I", total)


NEW_HOME_ID = 0x00123456


def connect_request(home_id: int = HOME_ID) -> bytes:
    return frame(
        0x52,
        struct.pack("<I", DID)
        + b"\x00"  # pCode
        + struct.pack("<H", HCS701B.code)
        + b"\x01\x02"  # hw, sw
        + struct.pack("<I", home_id)
        + bytes.fromhex("5b1dddccbbaa"),  # MAC, reversed
    )


def connect_reply(home_id: int = HOME_ID) -> bytes:
    return bytes([0xD2, 12, 0, 1, 0xE0, 0x01]) + struct.pack("<I", home_id) + bytes(4)


FIRMWARE = 0x02  # the sw byte above
SYNC_READINGS = {**REPORT_READINGS, "firmware": FIRMWARE}
CONNECT_REQUEST = connect_request()
CONNECT_REPLY = connect_reply()
TIME_REQUEST = frame(0x59, b"\x02")
TIME_REPLY = bytes([0xD9, 6, 0, 2]) + struct.pack("<I", t4(NOW))
REPORT_55 = frame(0x55, bytes([STATE_VER]) + REPORT_RECORDS)
REPORT_54 = frame(0x54, bytes([STATE_VER]) + with_dp_ids(REPORT_RECORDS))


class FakeSensor:
    """A BleakClient stand-in that plays the sensor's side of a sync.

    `script` maps each host write to the notifications the sensor answers with;
    a write it has no answer for gets none. The sensor opens with the auth challenge.
    """

    def __init__(
        self,
        script: dict[bytes, list[bytes]],
        opening: list[bytes] | None = None,
        chunk: int | None = None,
    ) -> None:
        self.script = script
        self.opening = [frame(0x50, CHALLENGE)] if opening is None else opening
        self.chunk = chunk
        self.writes: list[bytes] = []
        self.is_connected = True
        self.disconnects = 0
        self.late_writes = 0
        self.disconnected_callback: Callable[[Any], None] | None = None
        self.write_error: Exception | None = None
        self._notify: Callable[[Any, bytearray], None] | None = None

    async def connect(
        self, client_class: type, device: BLEDevice, name: str, **kwargs: Any
    ) -> FakeSensor:
        """Stands in for bleak_retry_connector.establish_connection."""
        self.disconnected_callback = kwargs["disconnected_callback"]
        return self

    async def start_notify(self, char: str, callback: Callable) -> None:
        assert char == CHAR_NOTIFY
        self._notify = callback
        self._send(self.opening)

    async def write_gatt_char(self, char: str, data: bytes, response: bool) -> None:
        assert char == CHAR_WRITE
        assert response is False
        if not self.is_connected:
            self.late_writes += 1
            raise BleakError("not connected")
        if self.write_error:
            raise self.write_error
        self.writes.append(bytes(data))
        self._send(self.script.get(bytes(data), []))

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.is_connected = False

    def hang_up(self) -> None:
        self.is_connected = False
        assert self.disconnected_callback is not None
        self.disconnected_callback(self)

    def _send(self, frames: list[bytes]) -> None:
        """Notify on the next loop iteration, split into `chunk`-byte packets if set."""
        data = b"".join(frames)
        size = self.chunk or len(data) or 1
        loop = asyncio.get_running_loop()
        for i in range(0, len(data), size):
            loop.call_soon(self._notify, None, bytearray(data[i : i + size]))


def handshake(report: bytes = REPORT_55, time_request: bool = True) -> dict[bytes, list[bytes]]:
    """The normal sync: auth, connection request, optional clock request, report."""
    after_connect = [TIME_REQUEST] if time_request else [report]
    return {
        expected_auth(CHALLENGE): [CONNECT_REQUEST],
        CONNECT_REPLY: after_connect,
        TIME_REPLY: [report],
    }


@pytest.fixture(autouse=True)
def no_ack_grace():
    with patch.object(session, "ACK_GRACE", 0):
        yield


async def run(
    sensor: FakeSensor, timeout: float | None = None, home_id: int | None = None
) -> dict:
    device = ble_device()
    with (
        patch.object(session, "establish_connection", sensor.connect),
        patch.object(session, "SESSION_TIMEOUT", timeout or session.SESSION_TIMEOUT),
    ):
        return await async_sync(device, HCS701B.code, HCS701B.fields, DID, NOW, home_id)


def test_auth_reply_golden_value() -> None:
    assert auth_reply(CHALLENGE, HCS701B.code, DID) == bytes.fromhex("d0 05 00 e3 07 00 00")
    assert auth_reply(CHALLENGE, HCS701B.code, DID) == expected_auth(CHALLENGE)


def test_t4_packs_local_time() -> None:
    assert t4(NOW) == 53 | 26 << 6 | 3 << 12 | 15 << 17 | 10 << 22 | 6 << 26 == 0x1A9E36B5


async def test_full_sync_with_clock_request() -> None:
    sensor = FakeSensor(handshake())
    assert await run(sensor) == SYNC_READINGS
    assert sensor.writes == [
        expected_auth(CHALLENGE),
        CONNECT_REPLY,
        TIME_REPLY,
        bytes([0xD5, 2, 0, STATE_VER]),
    ]
    assert sensor.disconnects == 1


async def test_sync_without_clock_request() -> None:
    sensor = FakeSensor(handshake(time_request=False))
    assert await run(sensor) == SYNC_READINGS
    assert TIME_REPLY not in sensor.writes


async def test_report_0x54_with_dp_ids() -> None:
    sensor = FakeSensor(handshake(report=REPORT_54))
    assert await run(sensor) == SYNC_READINGS
    assert sensor.writes[-1] == bytes([0xD4, 2, 0, STATE_VER])


@pytest.mark.parametrize("chunk", [1, 3, 7])
async def test_frames_split_across_notifications(chunk: int) -> None:
    sensor = FakeSensor(handshake(), chunk=chunk)
    assert await run(sensor) == SYNC_READINGS


async def test_several_frames_in_one_notification_answered_in_order() -> None:
    script = handshake()
    script[CONNECT_REPLY] = [TIME_REQUEST, REPORT_55]
    script[TIME_REPLY] = []
    sensor = FakeSensor(script)
    assert await run(sensor) == SYNC_READINGS
    assert sensor.writes[-2:] == [TIME_REPLY, bytes([0xD5, 2, 0, STATE_VER])]


async def test_other_requests_are_left_unanswered() -> None:
    """Settings, stats and other dpIds don't end the session; the report still does."""
    script = handshake()
    script[TIME_REPLY] = [frame(0x59, b"\x05"), frame(0x60, b"\x01\x02"), REPORT_55]
    sensor = FakeSensor(script)
    assert await run(sensor) == SYNC_READINGS
    assert len(sensor.writes) == 4


async def test_repeated_challenge_answered_each_time() -> None:
    sensor = FakeSensor(handshake(), opening=[frame(0x50, CHALLENGE)] * 2)
    assert await run(sensor) == SYNC_READINGS
    assert sensor.writes.count(expected_auth(CHALLENGE)) == 2


async def test_sensor_hangs_up_before_report() -> None:
    sensor = FakeSensor({expected_auth(CHALLENGE): []})
    task = asyncio.ensure_future(run(sensor))
    await asyncio.sleep(0.01)
    sensor.hang_up()
    with pytest.raises(SyncError, match="closed the connection"):
        await asyncio.wait_for(task, 1)


async def test_silent_sensor_times_out() -> None:
    """After a completed sync the sensor accepts connections but stays silent."""
    sensor = FakeSensor({}, opening=[])
    with pytest.raises(SyncError, match="no report"):
        await run(sensor, timeout=0.05)
    assert sensor.disconnects == 1


async def test_write_error_fails_fast() -> None:
    sensor = FakeSensor(handshake())
    sensor.write_error = BleakError("link lost")
    with pytest.raises(BleakError, match="link lost"):
        await asyncio.wait_for(run(sensor), 1)
    assert sensor.disconnects == 1


async def test_no_writes_after_the_session_ends() -> None:
    """Frames that arrive behind the report are never answered on a closed link."""
    script = handshake()
    script[TIME_REPLY] = [REPORT_55] + [TIME_REQUEST, frame(0x60, b"\x01")] * 5
    sensor = FakeSensor(script, chunk=2)
    assert await run(sensor) == SYNC_READINGS
    await asyncio.sleep(0.01)
    assert sensor.late_writes == 0


async def test_pairs_an_unpaired_sensor() -> None:
    """An unpaired sensor sends home ID 0; the reply gives it the new home."""
    sensor = FakeSensor(
        {
            expected_auth(CHALLENGE): [connect_request(0)],
            connect_reply(NEW_HOME_ID): [REPORT_55],
        }
    )
    assert await run(sensor, home_id=NEW_HOME_ID) == SYNC_READINGS
    assert sensor.writes[1] == connect_reply(NEW_HOME_ID)


async def test_paired_sensor_keeps_its_home() -> None:
    sensor = FakeSensor(handshake())
    assert await run(sensor, home_id=NEW_HOME_ID) == SYNC_READINGS
    assert sensor.writes[1] == CONNECT_REPLY


async def test_unpaired_sensor_stays_unpaired_without_a_home() -> None:
    sensor = FakeSensor(
        {expected_auth(CHALLENGE): [connect_request(0)], connect_reply(0): [REPORT_55]}
    )
    assert await run(sensor) == SYNC_READINGS
    assert sensor.writes[1] == connect_reply(0)


def test_new_home_id_is_a_positive_int32() -> None:
    ids = {new_home_id() for _ in range(1000)}
    assert all(0 < i < 2**31 for i in ids)
    assert len(ids) > 990
