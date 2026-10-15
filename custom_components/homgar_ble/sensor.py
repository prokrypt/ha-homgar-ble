"""Sensors for HomGar BLE."""

from __future__ import annotations

from functools import partial

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomGarConfigEntry, device_info

_TEMP = dict(
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    suggested_display_precision=1,
)
_HUM = dict(
    device_class=SensorDeviceClass.HUMIDITY,
    native_unit_of_measurement=PERCENTAGE,
)

DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "temperature": SensorEntityDescription(
        key="temperature", state_class=SensorStateClass.MEASUREMENT, **_TEMP
    ),
    "humidity": SensorEntityDescription(
        key="humidity", state_class=SensorStateClass.MEASUREMENT, **_HUM
    ),
    # Min/max as kept by the sensor itself (resets on the device's own schedule).
    "temperature_min": SensorEntityDescription(
        key="temperature_min", name="Temperature min", entity_registry_enabled_default=False, **_TEMP
    ),
    "temperature_max": SensorEntityDescription(
        key="temperature_max", name="Temperature max", entity_registry_enabled_default=False, **_TEMP
    ),
    "humidity_min": SensorEntityDescription(
        key="humidity_min", name="Humidity min", entity_registry_enabled_default=False, **_HUM
    ),
    "humidity_max": SensorEntityDescription(
        key="humidity_max", name="Humidity max", entity_registry_enabled_default=False, **_HUM
    ),
    # Raw HomGar battery status code from the sync report (0/1 = normal, higher = low).
    "battery_level": SensorEntityDescription(
        key="battery_level",
        name="Battery status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
}


def _to_update(
    info: DeviceInfo, readings: dict[str, float | int]
) -> PassiveBluetoothDataUpdate:
    keys = {k: PassiveBluetoothEntityKey(k, None) for k in readings if k in DESCRIPTIONS}
    return PassiveBluetoothDataUpdate(
        devices={None: info},
        entity_descriptions={ek: DESCRIPTIONS[k] for k, ek in keys.items()},
        entity_data={ek: readings[k] for k, ek in keys.items()},
        entity_names={},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(partial(_to_update, device_info(entry)))
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
