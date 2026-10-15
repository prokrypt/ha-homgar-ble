"""Config flow for HomGar BLE: discovered automatically via Bluetooth."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import CONF_MODEL, DOMAIN
from .models import HomGarModel, model_from_service_info


def _title(model: HomGarModel, address: str) -> str:
    return f"{model.name} {address[-5:]}"


class HomGarBleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._model: HomGarModel | None = None
        self._found: dict[str, HomGarModel] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if (model := model_from_service_info(discovery_info)) is None:
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self._model = model
        self.context["title_placeholders"] = {"name": _title(model, discovery_info.address)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None and self._model is not None
        title = _title(self._model, self._discovery.address)
        if user_input is not None:
            return self.async_create_entry(title=title, data={CONF_MODEL: self._model.code})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            model = self._found[address]
            return self.async_create_entry(
                title=_title(model, address), data={CONF_MODEL: model.code}
            )

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, False):
            if info.address in current:
                continue
            if (model := model_from_service_info(info)) is not None:
                self._found[info.address] = model
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        choices = {address: _title(model, address) for address, model in self._found.items()}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )
