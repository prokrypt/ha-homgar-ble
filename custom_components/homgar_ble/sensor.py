"""Sensors for HomGar BLE."""

from __future__ import annotations

from functools import partial

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomGarConfigEntry, device_info, entry_model
from .parser import Readings


def _to_update(
    info: DeviceInfo,
    descriptions: dict[str, SensorEntityDescription],
    readings: Readings,
) -> PassiveBluetoothDataUpdate:
    keys = {k: PassiveBluetoothEntityKey(k, None) for k in readings if k in descriptions}
    return PassiveBluetoothDataUpdate(
        devices={None: info},
        entity_descriptions={ek: descriptions[k] for k, ek in keys.items()},
        entity_data={ek: readings[k] for k, ek in keys.items()},
        entity_names={},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    descriptions = {d.key: d for d in entry_model(entry).sensors}
    processor = PassiveBluetoothDataProcessor(
        partial(_to_update, device_info(entry), descriptions)
    )
    entry.async_on_unload(
        processor.async_add_entities_listener(HomGarSensor, async_add_entities)
    )
    entry.async_on_unload(
        coordinator.async_register_processor(processor, SensorEntityDescription)
    )


class HomGarSensor(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor[float | int | None, dict]],
    SensorEntity,
):
    @property
    def native_value(self) -> float | int | None:
        return self.processor.entity_data.get(self.entity_key)
