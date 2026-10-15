"""The model registry: every model is discoverable and its entities have readings to show."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.homgar_ble.models import (
    BATTERY_LOW,
    DEFAULT_MODEL,
    HCS701B,
    MODELS,
    HomGarModel,
    model_from_service_info,
)

from .conftest import service_info

MANIFEST = json.loads(
    (Path(__file__).parents[1] / "custom_components/homgar_ble/manifest.json").read_text()
)

ALL_MODELS = pytest.mark.parametrize("model", MODELS.values(), ids=lambda m: m.name)


def readings_keys(model: HomGarModel) -> set[str]:
    """Every reading the model's field decoders can produce."""
    sample = bytes([1, 2, 3, 4])  # long enough for any field, no sentinels
    return set().union(*(field(sample) for field in model.fields.values()))


def test_hcs701b_service_uuid() -> None:
    assert HCS701B.service_uuid == "01469191-0000-1000-8000-00805f9b34fb"


def test_registry_is_keyed_by_model_code() -> None:
    assert all(code == model.code for code, model in MODELS.items())
    assert MODELS[DEFAULT_MODEL.code] is DEFAULT_MODEL


def test_manifest_matches_every_model() -> None:
    """HA only offers discovery for UUIDs listed in the manifest's bluetooth matchers."""
    matched = {m["service_data_uuid"] for m in MANIFEST["bluetooth"]}
    assert matched == {model.service_uuid for model in MODELS.values()}


@ALL_MODELS
def test_sensors_show_readings_the_model_decodes(model: HomGarModel) -> None:
    keys = [d.key for d in model.sensors]
    assert len(keys) == len(set(keys)), "duplicate sensor keys"
    assert set(keys) <= readings_keys(model)


@ALL_MODELS
def test_binary_sensors_have_readings_to_work_from(model: HomGarModel) -> None:
    keys = [d.key for d in model.binary_sensors]
    assert len(keys) == len(set(keys)), "duplicate binary sensor keys"
    full = {key: 1 for key in readings_keys(model)}
    for description in model.binary_sensors:
        assert description.value_fn({}) is None
        assert description.value_fn(full) is not None, description.key


@pytest.mark.parametrize(("level", "low"), [(0, False), (1, False), (2, True), (3, True)])
def test_battery_low(level: int, low: bool) -> None:
    assert BATTERY_LOW.value_fn({"battery_level": level}) is low


def test_battery_low_absent_without_battery_reading() -> None:
    assert BATTERY_LOW.value_fn({"temperature": 20.0}) is None


def test_model_from_service_info() -> None:
    assert model_from_service_info(service_info()) is HCS701B
    other = service_info(uuid="ffff9191-0000-1000-8000-00805f9b34fb")
    assert model_from_service_info(other) is None
