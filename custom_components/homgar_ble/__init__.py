"""HomGar/RainPoint BLE thermo-hygrometer (HCS701B), passive advert decoding."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import SERVICE_UUID
from .parser import decode

PLATFORMS = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

type HomGarConfigEntry = ConfigEntry[PassiveBluetoothProcessorCoordinator]


def _update(service_info: BluetoothServiceInfoBleak) -> dict[str, float | int]:
    data = service_info.service_data.get(SERVICE_UUID)
    return decode(data) if data else {}


async def async_setup_entry(hass: HomeAssistant, entry: HomGarConfigEntry) -> bool:
    address = entry.unique_id
    assert address is not None
    coordinator = PassiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        # Readings may arrive in the scan response, so ask for active scanning.
        mode=BluetoothScanningMode.ACTIVE,
        update_method=_update,
    )
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomGarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
