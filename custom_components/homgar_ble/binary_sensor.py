"""Battery-low binary sensor for HomGar BLE (from the GATT sync report)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomGarConfigEntry

BATTERY_LOW = BinarySensorEntityDescription(
    key="battery_low", device_class=BinarySensorDeviceClass.BATTERY
)


def _to_update(readings: dict[str, float | int]) -> PassiveBluetoothDataUpdate:
    if "battery_level" not in readings:
        return PassiveBluetoothDataUpdate(devices={}, entity_descriptions={}, entity_data={}, entity_names={})
    key = PassiveBluetoothEntityKey("battery_low", None)
    return PassiveBluetoothDataUpdate(
        devices={None: DeviceInfo(manufacturer="HomGar/RainPoint", model="HCS701B")},
        entity_descriptions={key: BATTERY_LOW},
        # HomGar battery status: 0/1 = normal, higher = low.
        entity_data={key: readings["battery_level"] >= 2},
        entity_names={},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(_to_update)
    entry.async_on_unload(
        processor.async_add_entities_listener(HomGarBinarySensor, async_add_entities)
    )
    entry.async_on_unload(
        coordinator.async_register_processor(processor, BinarySensorEntityDescription)
    )


class HomGarBinarySensor(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor[bool | None, dict]],
    BinarySensorEntity,
):
    @property
    def is_on(self) -> bool | None:
        return self.processor.entity_data.get(self.entity_key)
