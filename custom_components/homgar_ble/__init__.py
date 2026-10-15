"""HomGar/RainPoint BLE thermo-hygrometer (HCS701B).

Readings come from passive advertisements. Battery status is only in the report the
sensor sends over GATT, so we connect briefly whenever the advert says it wants a sync.
"""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.components.bluetooth.active_update_processor import (
    ActiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import SERVICE_UUID
from .parser import decode, device_id, wants_sync
from .session import async_sync

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

MODEL_CODE = int(SERVICE_UUID[:4], 16)  # 0x01469191 -> 0x0146
MIN_SYNC_INTERVAL = 600

type HomGarConfigEntry = ConfigEntry[ActiveBluetoothProcessorCoordinator]


def _update(service_info: BluetoothServiceInfoBleak) -> dict[str, float | int]:
    data = service_info.service_data.get(SERVICE_UUID)
    return decode(data) if data else {}


async def async_setup_entry(hass: HomeAssistant, entry: HomGarConfigEntry) -> bool:
    address = entry.unique_id
    assert address is not None

    def _needs_poll(service_info: BluetoothServiceInfoBleak, last_poll: float | None) -> bool:
        data = service_info.service_data.get(SERVICE_UUID, b"")
        return (
            hass.state is CoreState.running
            and wants_sync(data)
            and (last_poll is None or last_poll > MIN_SYNC_INTERVAL)
            and async_ble_device_from_address(hass, address, connectable=True) is not None
        )

    async def _poll(service_info: BluetoothServiceInfoBleak) -> dict[str, float | int]:
        did = device_id(service_info.service_data.get(SERVICE_UUID, b""))
        device = async_ble_device_from_address(hass, address, connectable=True)
        if did is None or device is None:
            raise RuntimeError("no connectable advertisement to sync from")
        readings = await async_sync(device, MODEL_CODE, did, dt_util.now())
        _LOGGER.debug("%s: sync report %s", address, readings)
        return readings

    coordinator = ActiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        # Readings may arrive in the scan response, so ask for active scanning.
        mode=BluetoothScanningMode.ACTIVE,
        update_method=_update,
        needs_poll_method=_needs_poll,
        poll_method=_poll,
        connectable=False,
    )
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomGarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
