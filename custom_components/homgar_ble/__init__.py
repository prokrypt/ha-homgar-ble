"""HomGar/RainPoint BLE devices (see models.py for the supported models).

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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import CONF_MODEL
from .models import DEFAULT_MODEL, MODELS, HomGarModel
from .parser import Readings, decode, device_id, wants_sync
from .session import async_sync

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

MIN_SYNC_INTERVAL = 600
RETRY_INTERVAL = 60  # after a failed sync

type HomGarConfigEntry = ConfigEntry[ActiveBluetoothProcessorCoordinator]


def entry_model(entry: ConfigEntry) -> HomGarModel:
    """The entry's model; entries from before models were recorded have none."""
    code = entry.data.get(CONF_MODEL)
    return DEFAULT_MODEL if code is None else MODELS[code]


def device_info(entry: HomGarConfigEntry) -> DeviceInfo:
    """Name the device after the config entry ("HCS701B 1D:5B") instead of the BLE name "HG"."""
    return DeviceInfo(
        name=entry.title, manufacturer="HomGar/RainPoint", model=entry_model(entry).name
    )


async def async_setup_entry(hass: HomeAssistant, entry: HomGarConfigEntry) -> bool:
    address = entry.unique_id
    assert address is not None
    model = entry_model(entry)

    def _update(service_info: BluetoothServiceInfoBleak) -> Readings:
        data = service_info.service_data.get(model.service_uuid)
        return decode(data, model.fields) if data else {}

    syncing = False

    def _needs_poll(service_info: BluetoothServiceInfoBleak, last_poll: float | None) -> bool:
        data = service_info.service_data.get(model.service_uuid, b"")
        if syncing or hass.state is not CoreState.running or not wants_sync(data):
            return False
        interval = MIN_SYNC_INTERVAL if coordinator.last_poll_successful else RETRY_INTERVAL
        return (last_poll is None or last_poll > interval) and (
            async_ble_device_from_address(hass, address, connectable=True) is not None
        )

    async def _poll(service_info: BluetoothServiceInfoBleak) -> Readings:
        nonlocal syncing
        data = service_info.service_data.get(model.service_uuid, b"")
        if not wants_sync(data):
            # The poll debouncer may replay a poll queued while the last sync was
            # connecting; the sensor only talks to us while it asks for a sync.
            _LOGGER.debug("%s: sensor no longer asks for a sync, skipping", address)
            return {}
        did = device_id(data)
        device = async_ble_device_from_address(hass, address, connectable=True)
        if did is None or device is None:
            raise RuntimeError("no connectable advertisement to sync from")
        syncing = True
        try:
            readings = await async_sync(device, model.code, model.fields, did, dt_util.now())
        finally:
            syncing = False
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
