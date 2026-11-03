"""Config/Options flow: escolha das cidades, limite de nota e notificações."""

from __future__ import annotations

from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .api import AnpError, AnpPostosClient
from .const import (
    CONF_CITIES,
    CONF_DETAILS,
    CONF_MAX_NOTA,
    CONF_NOTIFY,
    CONF_SCAN_HOURS,
    DEFAULT_DETAILS,
    DEFAULT_MAX_NOTA,
    DEFAULT_SCAN_HOURS,
    DOMAIN,
)


async def _fetch_cities() -> dict[str, str]:
    # Sessão curta e isolada: o cookie APEX não pode vazar para a sessão do HA.
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
        return await AnpPostosClient(session).async_get_cities()


def _schema(hass, cities: dict[str, str], current: dict[str, Any]) -> vol.Schema:
    notify = sorted(f"notify.{s}" for s in hass.services.async_services().get("notify", {}))
    return vol.Schema(
        {
            vol.Required(CONF_CITIES, default=list(current.get(CONF_CITIES, {}))): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=k, label=v) for k, v in cities.items()],
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_MAX_NOTA, default=current.get(CONF_MAX_NOTA, DEFAULT_MAX_NOTA)
            ): NumberSelector(NumberSelectorConfig(min=0, max=4, step=1, mode=NumberSelectorMode.SLIDER)),
            vol.Optional(CONF_NOTIFY, default=current.get(CONF_NOTIFY, [])): SelectSelector(
                SelectSelectorConfig(options=notify, multiple=True, custom_value=True)
            ),
            vol.Required(
                CONF_SCAN_HOURS, default=current.get(CONF_SCAN_HOURS, DEFAULT_SCAN_HOURS)
            ): NumberSelector(NumberSelectorConfig(min=1, max=168, step=1, unit_of_measurement="h")),
            vol.Required(
                CONF_DETAILS, default=current.get(CONF_DETAILS, DEFAULT_DETAILS)
            ): BooleanSelector(),
        }
    )


def _clean(user_input: dict[str, Any], cities: dict[str, str]) -> dict[str, Any]:
    return {
        **user_input,
        CONF_CITIES: {c: cities[c] for c in user_input[CONF_CITIES] if c in cities},
        CONF_MAX_NOTA: int(user_input[CONF_MAX_NOTA]),
        CONF_SCAN_HOURS: int(user_input[CONF_SCAN_HOURS]),
    }


class AnpPostosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Uma entrada só; as cidades ficam nela."""

    VERSION = 1
    _cities: dict[str, str]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if not getattr(self, "_cities", None):
            try:
                self._cities = await _fetch_cities()
            except AnpError:
                return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            if not user_input.get(CONF_CITIES):
                errors[CONF_CITIES] = "no_cities"
            else:
                return self.async_create_entry(
                    title="ANP Postos", data=_clean(user_input, self._cities)
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, self._cities, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnpPostosOptionsFlow:
        return AnpPostosOptionsFlow()


class AnpPostosOptionsFlow(OptionsFlow):
    """Troca cidades, limite e notificações sem recriar a integração."""

    _cities: dict[str, str] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._cities is None:
            try:
                self._cities = await _fetch_cities()
            except AnpError:
                return self.async_abort(reason="cannot_connect")
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_CITIES):
                errors[CONF_CITIES] = "no_cities"
            else:
                return self.async_create_entry(data=_clean(user_input, self._cities))
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(self.hass, self._cities, current), errors=errors
        )
