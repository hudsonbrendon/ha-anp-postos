"""Aviso de chegada: celular perto de um posto → push com o veredito."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from .const import (
    CONF_RADIUS,
    CONF_TRACKERS,
    DEFAULT_RADIUS,
    DOMAIN,
    EVENT_ARRIVAL,
    LOGGER,
)
from .coordinator import entry_option
from .verdict import AVOID, arrival_message, nearest_station, verdict

if TYPE_CHECKING:
    from .data import AnpPostosConfigEntry

COOLDOWN_S = 3 * 3600  # mesmo posto, mesmo celular: no máximo um aviso a cada 3 h
APPROACH_M = 700  # perto assim, pede ao app uma posição nova (iOS só atualiza a cada ~500 m)
APPROACH_COOLDOWN_S = 600
MAX_ACCURACY_M = 200


def notify_service(hass: HomeAssistant, tracker: str) -> str | None:
    """device_tracker do app → notify.mobile_app_<device_name>."""
    entry = er.async_get(hass).async_get(tracker)
    if not entry or not entry.config_entry_id:
        return None
    config = hass.config_entries.async_get_entry(entry.config_entry_id)
    if not config or config.domain != "mobile_app":
        return None
    service = f"mobile_app_{slugify(config.data.get('device_name') or config.title)}"
    return service if hass.services.has_service("notify", service) else None


@callback
def async_setup_arrival(hass: HomeAssistant, entry: AnpPostosConfigEntry) -> None:
    trackers: list[str] = entry_option(entry, CONF_TRACKERS, [])
    if not trackers:
        return
    radius = float(entry_option(entry, CONF_RADIUS, DEFAULT_RADIUS))
    coordinator = entry.runtime_data.coordinator
    sent: dict[tuple[str, str], float] = {}

    async def _notify(service: str, data: dict[str, Any]) -> None:
        try:
            await hass.services.async_call("notify", service, data)
        except Exception as err:  # noqa: BLE001 - app de terceiro
            LOGGER.warning("falha no aviso de chegada via %s: %s", service, err)

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is None or ATTR_LATITUDE not in state.attributes:
            return
        if (state.attributes.get("gps_accuracy") or 0) > MAX_ACCURACY_M:
            return
        stations = [
            s for city in (coordinator.data or {}).values() for s in city["stations"].values()
        ]
        station, dist = nearest_station(
            stations, state.attributes[ATTR_LATITUDE], state.attributes[ATTR_LONGITUDE]
        )
        if station is None or dist > APPROACH_M:
            return
        tracker = state.entity_id
        service = notify_service(hass, tracker)
        now = time.monotonic()
        if dist > radius:
            # Chegando: pede posição nova ao app para pegar o momento da parada.
            key = (tracker, "approach")
            if service and now - sent.get(key, 0) > APPROACH_COOLDOWN_S:
                sent[key] = now
                hass.async_create_task(_notify(service, {"message": "request_location_update"}))
            return
        key = (tracker, station["cod_instalacao"])
        if now - sent.get(key, 0) < COOLDOWN_S:
            return
        sent[key] = now
        level = verdict(station, coordinator.max_nota)
        title, message = arrival_message(station, level)
        geo = er.async_get(hass).async_get_entity_id(
            "geo_location", DOMAIN, station["cod_instalacao"]
        )
        hass.bus.async_fire(
            EVENT_ARRIVAL,
            {
                "tracker": tracker,
                "veredito": level,
                "distancia_m": round(dist),
                "cnpj": station["cnpj"],
                "posto": station.get("nome") or station.get("razao_social"),
                "nota": station.get("nota"),
                "entity_id": geo,
            },
        )
        if not service:
            LOGGER.debug("%s sem app de celular para avisar", tracker)
            return
        push: dict[str, Any] = {"thread-id": DOMAIN}
        if level == AVOID:
            push["interruption-level"] = "time-sensitive"
        data: dict[str, Any] = {
            "tag": f"{DOMAIN}_{station['cod_instalacao']}",
            "group": DOMAIN,
            "push": push,
        }
        if geo:  # toque abre o posto (more-info) no app
            data["url"] = data["clickAction"] = f"entityId:{geo}"
        hass.async_create_task(
            _notify(service, {"title": title, "message": message, "data": data})
        )

    entry.async_on_unload(async_track_state_change_event(hass, trackers, _changed))
