"""Sensors for HomGar BLE."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomGarConfigEntry, entry_model, new_processor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    processor = new_processor(entry, entry_model(entry).sensors)
    entry.async_on_unload(
        processor.async_add_entities_listener(HomGarSensor, async_add_entities)
    )
    entry.async_on_unload(
        entry.runtime_data.async_register_processor(processor, SensorEntityDescription)
    )


class HomGarSensor(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor[float | int | None, dict]],
    SensorEntity,
):
    @property
    def native_value(self) -> float | int | None:
        return self.processor.entity_data.get(self.entity_key)
