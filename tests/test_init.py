"""Entry setup: adverts become entities, and a sync request triggers one GATT session."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.components.bluetooth import async_get_advertisement_callback
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.homgar_ble.const import CONF_MODEL, DOMAIN
from custom_components.homgar_ble.models import HCS701B
from custom_components.homgar_ble.session import SyncError

from .conftest import ADDRESS, DID, payload, service_info
from .test_parser import REPORT_READINGS

pytestmark = pytest.mark.usefixtures("mock_bluetooth")

SYNC = "custom_components.homgar_ble.async_sync"


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="HCS701B 1D:5B",
        data={CONF_MODEL: HCS701B.code},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def advertise(
    hass: HomeAssistant, data: bytes, connectable: bool = True, at: float = 0
) -> None:
    """Hand HA an advert stamped `at` seconds from now (the coordinator ages polls by it)."""
    async_get_advertisement_callback(hass)(service_info(data, connectable=connectable, at=at))
    await hass.async_block_till_done(wait_background_tasks=True)


def asking(humidity: int = 40) -> bytes:
    """An advert asking for a sync. HA skips adverts identical to the last one, so vary it."""
    return payload(flags=0x17, records=bytes([0x88, humidity]))


async def advertise_soon(hass: HomeAssistant, data: bytes) -> None:
    """Hand HA an advert and let ready tasks run, without waiting for a sync to finish."""
    async_get_advertisement_callback(hass)(service_info(data))
    for _ in range(5):
        await asyncio.sleep(0)


async def debouncer_cooldown(hass: HomeAssistant) -> None:
    """Let HA's poll debouncer cool down (and run any poll it queued meanwhile)."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done(wait_background_tasks=True)


def state(hass: HomeAssistant, platform: str, key: str) -> str | None:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{ADDRESS}-{key}")
    if entity_id is None:
        return None
    s = hass.states.get(entity_id)
    return s.state if s else None


async def test_advert_readings_become_sensors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    with patch(SYNC) as sync:
        await advertise(hass, payload())
    sync.assert_not_called()

    assert state(hass, "sensor", "temperature") == "26.2"
    assert state(hass, "sensor", "humidity") == "40"
    # Min/max and battery status are disabled by default.
    assert state(hass, "sensor", "temperature_min") is None
    # Battery status comes from the advert flags (0x15: normal).
    assert state(hass, "binary_sensor", "battery_low") == STATE_OFF

    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert (dr.CONNECTION_BLUETOOTH, ADDRESS) in device.connections
    assert device.name == "HCS701B 1D:5B"
    assert device.model == "HCS701B"


async def test_entry_without_model_defaults_to_hcs701b(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, title="HG", data={})
    entry.add_to_hass(hass)
    await setup(hass, entry)
    await advertise(hass, payload())
    assert state(hass, "sensor", "temperature") == "26.2"


async def test_sync_request_reads_battery(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    with patch(SYNC, AsyncMock(return_value=REPORT_READINGS)) as sync:
        await advertise(hass, payload(flags=0x17))
        sync.assert_awaited_once()
        device, model, fields, did, _now = sync.await_args.args
        assert (device.address, model, fields, did) == (
            ADDRESS,
            HCS701B.code,
            HCS701B.fields,
            DID,
        )
        # Each connection attempt may pick a fresh path to the sensor.
        assert sync.await_args.kwargs["ble_device_callback"]().address == ADDRESS
        assert state(hass, "binary_sensor", "battery_low") == STATE_OFF
        assert state(hass, "sensor", "temperature") == "27.6"


async def test_sync_sets_firmware_version(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await advertise(hass, payload())
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.sw_version is None
    with patch(SYNC, AsyncMock(return_value={**REPORT_READINGS, "firmware": 14})):
        await advertise(hass, payload(flags=0x17))
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.sw_version == "14"
    assert device.name == "HCS701B 1D:5B"


async def test_sync_at_most_every_ten_minutes(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    with patch(SYNC, AsyncMock(return_value=REPORT_READINGS)) as sync:
        await advertise(hass, asking(40))
        await debouncer_cooldown(hass)
        await advertise(hass, asking(41), at=300)
        await debouncer_cooldown(hass)
        assert sync.await_count == 1
        await advertise(hass, asking(42), at=700)
        assert sync.await_count == 2


async def test_failed_sync_retried_after_a_minute(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    with patch(SYNC, AsyncMock(side_effect=SyncError("hung up"))) as sync:
        await advertise(hass, asking(40))
        await debouncer_cooldown(hass)
        await advertise(hass, asking(41), at=30)
        await debouncer_cooldown(hass)
        assert sync.await_count == 1
        await advertise(hass, asking(42), at=90)
        assert sync.await_count == 2


async def test_no_second_connection_while_syncing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    release = asyncio.Event()

    async def slow_sync(*args):
        await release.wait()
        return REPORT_READINGS

    with patch(SYNC, AsyncMock(side_effect=slow_sync)) as sync:
        await advertise_soon(hass, asking(40))
        await advertise_soon(hass, asking(41))  # still asking while we connect
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        await debouncer_cooldown(hass)
    sync.assert_awaited_once()


async def test_replayed_poll_skipped_once_sensor_stops_asking(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """HA's poll debouncer can replay a queued poll after the sensor stopped asking."""
    await setup(hass, entry)
    poll = entry.runtime_data._poll_method
    with patch(SYNC) as sync:
        assert await poll(service_info(payload(flags=0x15))) == {}
    sync.assert_not_called()


async def test_low_battery(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    with patch(SYNC, AsyncMock(return_value={**REPORT_READINGS, "battery_low": True})):
        await advertise(hass, payload(flags=0x17))
    assert state(hass, "binary_sensor", "battery_low") == STATE_ON


async def test_low_battery_from_advert(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    with patch(SYNC) as sync:
        await advertise(hass, payload(flags=0x25))
    sync.assert_not_called()
    assert state(hass, "binary_sensor", "battery_low") == STATE_ON


async def test_no_sync_without_connectable_advert(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    with patch(SYNC) as sync:
        await advertise(hass, payload(flags=0x17), connectable=False)
    sync.assert_not_called()
    assert state(hass, "sensor", "temperature") == "26.2"


async def test_failed_sync_keeps_advert_readings(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    with patch(SYNC, AsyncMock(side_effect=SyncError("hung up"))) as sync:
        await advertise(hass, payload(flags=0x17))
        await advertise(hass, payload(flags=0x15))
    sync.assert_awaited_once()
    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, "sensor", "temperature") == "26.2"


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await advertise(hass, payload())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_readings_saved_for_restart(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict
) -> None:
    """HA saves the last update every 15 min; the descriptions must be plain JSON."""
    await setup(hass, entry)
    await advertise(hass, payload())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    saved = hass_storage["bluetooth.passive_update_processor"]["data"][entry.entry_id]
    assert saved["binary_sensor"]["entity_descriptions"] == {
        "battery_low___": {"key": "battery_low", "device_class": "battery"}
    }
    assert saved["binary_sensor"]["entity_data"] == {"battery_low___": False}
