"""Binary sensors for HomGar BLE (e.g. battery low)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomGarConfigEntry, entry_model, new_processor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    processor = new_processor(entry, entry_model(entry).binary_sensors)
    entry.async_on_unload(
        processor.async_add_entities_listener(HomGarBinarySensor, async_add_entities)
    )
    entry.async_on_unload(
        entry.runtime_data.async_register_processor(processor, BinarySensorEntityDescription)
    )


class HomGarBinarySensor(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor[bool | None, dict]],
    BinarySensorEntity,
):
    @property
    def is_on(self) -> bool | None:
        return self.processor.entity_data.get(self.entity_key)
