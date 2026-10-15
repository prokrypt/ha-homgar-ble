"""Supported HomGar BLE models.

To add a model: describe it as a HomGarModel below, add it to MODELS, and add its
service_uuid to the "bluetooth" matchers in manifest.json so HA discovers it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature

from .parser import (
    BAT,
    MAX_RH,
    MAX_TEM,
    RH,
    TEM,
    Field,
    Readings,
    temp_f10,
    temp_f10_range,
    u8,
    u8_range,
)


@dataclass(frozen=True, kw_only=True)
class HomGarBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor computed from the readings; None means not in this update."""

    value_fn: Callable[[Readings], bool | None]


@dataclass(frozen=True, kw_only=True)
class HomGarModel:
    code: int  # HomGar model code, from the advert UUID; also used in the GATT auth
    name: str
    # Record code -> decoder, for adverts and sync reports alike.
    fields: Mapping[int, Field]
    # Entities, keyed by the reading they show (description.key).
    sensors: tuple[SensorEntityDescription, ...] = ()
    binary_sensors: tuple[HomGarBinarySensorDescription, ...] = ()

    @property
    def service_uuid(self) -> str:
        """Service data UUID: the 0x9191 HomGar marker plus the model code."""
        return f"{self.code:04x}9191-0000-1000-8000-00805f9b34fb"


# Reusable entity descriptions.

_TEMP = dict(
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    suggested_display_precision=1,
)
_HUM = dict(
    device_class=SensorDeviceClass.HUMIDITY,
    native_unit_of_measurement=PERCENTAGE,
)

TEMPERATURE = SensorEntityDescription(
    key="temperature", state_class=SensorStateClass.MEASUREMENT, **_TEMP
)
HUMIDITY = SensorEntityDescription(
    key="humidity", state_class=SensorStateClass.MEASUREMENT, **_HUM
)
# Min/max as kept by the sensor itself (resets on the device's own schedule).
TEMPERATURE_MIN = SensorEntityDescription(
    key="temperature_min", name="Temperature min", entity_registry_enabled_default=False, **_TEMP
)
TEMPERATURE_MAX = SensorEntityDescription(
    key="temperature_max", name="Temperature max", entity_registry_enabled_default=False, **_TEMP
)
HUMIDITY_MIN = SensorEntityDescription(
    key="humidity_min", name="Humidity min", entity_registry_enabled_default=False, **_HUM
)
HUMIDITY_MAX = SensorEntityDescription(
    key="humidity_max", name="Humidity max", entity_registry_enabled_default=False, **_HUM
)
# Raw HomGar battery status code from the sync report (0/1 = normal, higher = low).
BATTERY_STATUS = SensorEntityDescription(
    key="battery_level",
    name="Battery status",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)
BATTERY_LOW = HomGarBinarySensorDescription(
    key="battery_low",
    device_class=BinarySensorDeviceClass.BATTERY,
    value_fn=lambda r: r["battery_level"] >= 2 if "battery_level" in r else None,
)


HCS701B = HomGarModel(
    code=326,
    name="HCS701B",
    fields={
        TEM: temp_f10("temperature"),
        RH: u8("humidity", invalid=0xFF),
        MAX_TEM: temp_f10_range("temperature"),
        MAX_RH: u8_range("humidity"),
        BAT: u8("battery_level"),
    },
    sensors=(
        TEMPERATURE,
        HUMIDITY,
        TEMPERATURE_MIN,
        TEMPERATURE_MAX,
        HUMIDITY_MIN,
        HUMIDITY_MAX,
        BATTERY_STATUS,
    ),
    binary_sensors=(BATTERY_LOW,),
)

MODELS: dict[int, HomGarModel] = {m.code: m for m in (HCS701B,)}

# Entries created before models were recorded are all HCS701B.
DEFAULT_MODEL = HCS701B


def model_from_service_info(info: BluetoothServiceInfoBleak) -> HomGarModel | None:
    return next((m for m in MODELS.values() if m.service_uuid in info.service_data), None)
