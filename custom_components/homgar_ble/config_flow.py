"""Config flow for HomGar BLE: discovered automatically via Bluetooth.

A sensor that was never paired with the HomGar app only sends its device ID. The
flow then recommends pairing it in the app (which also offers firmware updates),
and can pair it from Home Assistant instead.
"""

from __future__ import annotations

import logging
from typing import Any

from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
    async_last_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.util import dt as dt_util

from .const import CONF_MODEL, DOMAIN
from .models import HomGarModel, model_from_service_info
from .parser import device_id, is_paired
from .session import SyncError, async_sync, new_home_id

_LOGGER = logging.getLogger(__name__)


def _title(model: HomGarModel, address: str) -> str:
    return f"{model.name} {address[-5:]}"


class HomGarBleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._model: HomGarModel | None = None
        self._found: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if (model := model_from_service_info(discovery_info)) is None:
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self._model = model
        self.context["title_placeholders"] = {"name": self._name}
        if not self._paired():
            return await self.async_step_pair()
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._create_entry()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": self._name}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovery = self._found[address]
            self._model = model_from_service_info(self._discovery)
            if not self._paired():
                return await self.async_step_pair()
            return self._create_entry()

        current = self._async_current_ids(include_ignore=False)
        choices = {}
        for info in async_discovered_service_info(self.hass, False):
            if info.address in current:
                continue
            if (model := model_from_service_info(info)) is not None:
                self._found[info.address] = info
                choices[info.address] = _title(model, info.address)
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The sensor is unpaired: pair it in the app (recommended) or from here."""
        return self.async_show_menu(
            step_id="pair",
            menu_options=["pair_app", "pair_here"],
            description_placeholders={"name": self._name},
        )

    async def async_step_pair_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            if self._paired():
                return self._create_entry()
            errors["base"] = "not_paired"
        return self.async_show_form(
            step_id="pair_app", description_placeholders={"name": self._name}, errors=errors
        )

    async def async_step_pair_here(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            if self._paired():  # paired in the app meanwhile
                return self._create_entry()
            try:
                await self._async_pair()
            except BleakError as err:
                _LOGGER.debug("%s: pairing failed: %s", self._address, err)
                errors["base"] = "pair_failed"
            else:
                return self._create_entry()
        return self.async_show_form(
            step_id="pair_here", description_placeholders={"name": self._name}, errors=errors
        )

    @property
    def _address(self) -> str:
        assert self._discovery is not None
        return self._discovery.address

    @property
    def _name(self) -> str:
        assert self._model is not None
        return _title(self._model, self._address)

    def _advert(self) -> bytes:
        """The sensor's latest service data."""
        assert self._model is not None
        info = async_last_service_info(self.hass, self._address, False) or self._discovery
        assert info is not None
        return info.service_data.get(self._model.service_uuid, b"")

    def _paired(self) -> bool:
        return is_paired(self._advert())

    async def _async_pair(self) -> None:
        assert self._model is not None
        did = device_id(self._advert())
        device = async_ble_device_from_address(self.hass, self._address, connectable=True)
        if did is None or device is None:
            raise SyncError("no connectable adapter or proxy has seen the sensor")
        await async_sync(
            device, self._model.code, self._model.fields, did, dt_util.now(), new_home_id()
        )

    def _create_entry(self) -> ConfigFlowResult:
        assert self._model is not None
        return self.async_create_entry(title=self._name, data={CONF_MODEL: self._model.code})
