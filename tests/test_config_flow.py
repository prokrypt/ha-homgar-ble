"""Config flows: Bluetooth discovery and the manual device picker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homgar_ble.const import CONF_MODEL, DOMAIN
from custom_components.homgar_ble.models import HCS701B
from custom_components.homgar_ble.session import SyncError

from .conftest import ADDRESS, DID, ble_device, payload, service_info

OTHER_ADDRESS = "AA:BB:CC:DD:00:01"
UNSUPPORTED_UUID = "ffff9191-0000-1000-8000-00805f9b34fb"
NEW_HOME_ID = 0x00123456
FLOW = "custom_components.homgar_ble.config_flow"
STRINGS = json.loads(
    (Path(__file__).parents[1] / "custom_components/homgar_ble/strings.json").read_text()
)


@pytest.fixture(autouse=True)
def no_setup():
    """The flows are tested on their own; entry setup has its own tests."""
    with patch("custom_components.homgar_ble.async_setup_entry", return_value=True):
        yield


def discovered(*infos):
    return patch(
        "custom_components.homgar_ble.config_flow.async_discovered_service_info",
        return_value=list(infos),
    )


async def test_bluetooth_discovery_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {"name": "HCS701B 1D:5B"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HCS701B 1D:5B"
    assert result["data"] == {CONF_MODEL: HCS701B.code}
    assert result["result"].unique_id == ADDRESS


async def test_bluetooth_discovery_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_bluetooth_discovery_unsupported_model(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=service_info(uuid=UNSUPPORTED_UUID),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_user_picks_a_discovered_sensor(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=OTHER_ADDRESS).add_to_hass(hass)
    infos = (
        service_info(),
        service_info(address=OTHER_ADDRESS),  # already set up
        service_info(address="AA:BB:CC:DD:00:02", uuid=UNSUPPORTED_UUID),
    )
    with discovered(*infos):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    choices = result["data_schema"].schema[CONF_ADDRESS].container
    assert choices == {ADDRESS: "HCS701B 1D:5B"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HCS701B 1D:5B"
    assert result["data"] == {CONF_MODEL: HCS701B.code}
    assert result["result"].unique_id == ADDRESS


async def test_user_flow_takes_over_discovery_in_progress(hass: HomeAssistant) -> None:
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    with discovered(service_info()):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_user_no_devices_found(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS).add_to_hass(hass)
    with discovered(service_info()):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


def unpaired():
    """Advert of a sensor never paired with the app: device ID only."""
    return service_info(payload()[:4])


def latest(info):
    """The advert HA's Bluetooth stack saw last."""
    return patch(f"{FLOW}.async_last_service_info", return_value=info)


@pytest.fixture
def pairing():
    """A connectable sensor that completes the session; yields the async_sync mock."""
    with (
        patch(f"{FLOW}.async_ble_device_from_address", return_value=ble_device()),
        patch(f"{FLOW}.new_home_id", return_value=NEW_HOME_ID),
        patch(f"{FLOW}.async_sync", AsyncMock(return_value={})) as sync,
    ):
        yield sync


async def start_unpaired(hass: HomeAssistant, choice: str) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=unpaired()
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "pair"
    assert result["menu_options"] == ["pair_app", "pair_here"]
    assert result["description_placeholders"] == {"name": "HCS701B 1D:5B"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == choice
    return result


async def test_pair_from_home_assistant(hass: HomeAssistant, pairing) -> None:
    result = await start_unpaired(hass, "pair_here")
    with latest(unpaired()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MODEL: HCS701B.code}
    pairing.assert_awaited_once()
    args = pairing.await_args.args
    assert args[0].address == ADDRESS
    assert (args[1], args[3], args[5]) == (HCS701B.code, DID, NEW_HOME_ID)


async def test_pair_from_home_assistant_fails_then_retries(
    hass: HomeAssistant, pairing
) -> None:
    result = await start_unpaired(hass, "pair_here")
    pairing.side_effect = SyncError("sensor closed the connection")
    with latest(unpaired()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "pair_failed"}

    pairing.side_effect = None
    with latest(unpaired()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_pair_from_home_assistant_without_connectable_adapter(
    hass: HomeAssistant, pairing
) -> None:
    result = await start_unpaired(hass, "pair_here")
    with latest(unpaired()), patch(f"{FLOW}.async_ble_device_from_address", return_value=None):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "pair_failed"}
    pairing.assert_not_awaited()


async def test_pair_here_skips_pairing_once_the_app_paired_it(
    hass: HomeAssistant, pairing
) -> None:
    result = await start_unpaired(hass, "pair_here")
    with latest(service_info()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    pairing.assert_not_awaited()


async def test_pair_in_the_app(hass: HomeAssistant, pairing) -> None:
    result = await start_unpaired(hass, "pair_app")
    with latest(unpaired()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_paired"}

    with latest(service_info()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HCS701B 1D:5B"
    pairing.assert_not_awaited()


async def test_user_picks_an_unpaired_sensor(hass: HomeAssistant) -> None:
    with discovered(unpaired()):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with latest(None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "pair"


def test_translations_match_strings() -> None:
    translations = Path(__file__).parents[1] / "custom_components/homgar_ble/translations"
    assert json.loads((translations / "en.json").read_text()) == STRINGS
    assert set(STRINGS["config"]["abort"]) == {
        "already_configured",
        "no_devices_found",
        "not_supported",
    }
    assert set(STRINGS["config"]["error"]) == {"not_paired", "pair_failed"}
