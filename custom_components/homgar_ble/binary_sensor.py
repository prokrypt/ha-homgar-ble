"""Binary sensors for HomGar BLE (e.g. battery low, from the GATT sync report)."""

from __future__ import annotations

from dataclasses import fields
from functools import partial

from homeassistant.components.binary_sensor import (
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

from . import HomGarConfigEntry, device_info, entry_model
from .models import HomGarBinarySensorDescription
from .parser import Readings


def _plain(description: HomGarBinarySensorDescription) -> BinarySensorEntityDescription:
    """The description without value_fn: HA saves update descriptions as JSON for restarts."""
    return BinarySensorEntityDescription(
        **{f.name: getattr(description, f.name) for f in fields(description) if f.name != "value_fn"}
    )


def _to_update(
    info: DeviceInfo,
    descriptions: tuple[HomGarBinarySensorDescription, ...],
    readings: Readings,
) -> PassiveBluetoothDataUpdate:
    found = [
        (PassiveBluetoothEntityKey(d.key, None), d, v)
        for d in descriptions
        if (v := d.value_fn(readings)) is not None
    ]
    return PassiveBluetoothDataUpdate(
        devices={None: info} if found else {},
        entity_descriptions={ek: _plain(d) for ek, d, _ in found},
        entity_data={ek: v for ek, _, v in found},
        entity_names={},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomGarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(
        partial(_to_update, device_info(entry), entry_model(entry).binary_sensors)
    )
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
