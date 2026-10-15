"""Shared fixtures and advert builders."""

from __future__ import annotations

from inspect import signature
import struct
import time

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
import pytest

from custom_components.homgar_ble.models import HCS701B

ADDRESS = "AA:BB:CC:DD:1D:5B"
DID = 0x12345678
HOME_ID = 0x00ABCDEF

# Example records from docs/PROTOCOL.md: 79.2 degF, 40 %, trend 5, 78.3-79.5 degF, 39-46 %.
ADVERT_RECORDS = bytes.fromhex("85 18 03 88 28 b8 05 e7 0f 03 1b 03 e9 27 2e")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""


def payload(flags: int = 0x15, records: bytes = ADVERT_RECORDS, did: int = DID) -> bytes:
    """Advert service data: did, flags, home ID, then TLV records."""
    return struct.pack("<IBI", did, flags, HOME_ID) + records


# Bleak before 1.0 (HA 2025.3) requires an rssi; later versions deprecate passing one.
_BLE_DEVICE_EXTRA = {"rssi": -60} if "rssi" in signature(BLEDevice).parameters else {}


def ble_device(address: str = ADDRESS) -> BLEDevice:
    return BLEDevice(address, "HG", {}, **_BLE_DEVICE_EXTRA)


def service_info(
    data: bytes | None = None,
    *,
    address: str = ADDRESS,
    uuid: str = HCS701B.service_uuid,
    connectable: bool = True,
    at: float = 0,
) -> BluetoothServiceInfoBleak:
    """A HomGar advert as Home Assistant's Bluetooth stack hands it over, `at` seconds from now."""
    service_data = {uuid: payload() if data is None else data}
    adv = AdvertisementData(
        local_name="HG",
        manufacturer_data={},
        service_data=service_data,
        service_uuids=[],
        tx_power=None,
        rssi=-60,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name="HG",
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data=service_data,
        service_uuids=[],
        source="local",
        device=ble_device(address),
        advertisement=adv,
        connectable=connectable,
        time=time.monotonic() + at,
        tx_power=None,
    )
