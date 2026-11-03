"""ANP Postos: postos de combustível da ANP (nota, fiscalizações, amostras) no Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, STATIC_URL
from .coordinator import AnpPostosCoordinator
from .data import AnpPostosConfigEntry, AnpPostosData

PLATFORMS: list[Platform] = [Platform.GEO_LOCATION, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve os marcadores coloridos por nota (entity_picture no mapa)."""
    if hass.http is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "static"), True)]
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AnpPostosConfigEntry) -> bool:
    coordinator = AnpPostosCoordinator(hass, entry)
    entry.runtime_data = AnpPostosData(coordinator=coordinator)
    await coordinator.async_config_entry_first_refresh()
    # Cidade removida nas opções: some o dispositivo (e as entidades dele).
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not any(i[1] in coordinator.data for i in device.identifiers if i[0] == DOMAIN):
            devices.async_remove_device(device.id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AnpPostosConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: AnpPostosConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
