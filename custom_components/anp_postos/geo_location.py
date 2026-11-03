"""Um geo_location por posto: aparece no card de mapa (geo_location_sources: anp_postos)."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.location import distance

from .const import DOMAIN, STATIC_URL
from .coordinator import maps_url
from .data import AnpPostosConfigEntry
from .entity import AnpPostosEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AnpPostosConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[tuple[str, str]] = set()

    @callback
    def _sync() -> None:
        current = {
            (city_id, cod)
            for city_id, city in (coordinator.data or {}).items()
            for cod in city["stations"]
        }
        new = current - known
        if new:
            known.update(new)
            async_add_entities(AnpPostoGeolocation(coordinator, c, s) for c, s in new)
        # Posto que sumiu da lista da ANP (descredenciado) sai do registro.
        registry = er.async_get(hass)
        for city_id, cod in known - current:
            known.discard((city_id, cod))
            if entity_id := registry.async_get_entity_id("geo_location", DOMAIN, cod):
                registry.async_remove(entity_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AnpPostoGeolocation(AnpPostosEntity, GeolocationEvent):
    """Posto no mapa; estado = distância de casa (km)."""

    _attr_source = DOMAIN
    _attr_has_entity_name = False  # nome = nome do posto, sem prefixo da cidade
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:gas-station"
    _unrecorded_attributes = frozenset(
        {"detalhes", "fiscalizacoes_detalhe", "irregularidades", "amostras_detalhe"}
    )

    def __init__(self, coordinator, city_id: str, cod: str) -> None:
        super().__init__(coordinator, city_id)
        self.cod = cod
        self._attr_unique_id = cod

    @property
    def station(self) -> dict[str, Any] | None:
        city = (self.coordinator.data or {}).get(self.city_id)
        return city["stations"].get(self.cod) if city else None

    @property
    def available(self) -> bool:
        return super().available and self.station is not None

    @property
    def name(self) -> str | None:
        s = self.station
        return (s["nome"] or s["razao_social"]) if s else None

    @property
    def latitude(self) -> float | None:
        return self.station["latitude"] if self.station else None

    @property
    def longitude(self) -> float | None:
        return self.station["longitude"] if self.station else None

    @property
    def distance(self) -> float | None:
        s = self.station
        if not s or s["latitude"] is None:
            return None
        meters = distance(
            self.hass.config.latitude, self.hass.config.longitude, s["latitude"], s["longitude"]
        )
        return round(meters / 1000, 2) if meters is not None else None

    @property
    def entity_picture(self) -> str | None:
        s = self.station
        if not s:
            return None
        if s.get("interditado"):
            return f"{STATIC_URL}/interditado.svg"
        nota = s.get("nota")
        return f"{STATIC_URL}/nota_{nota if nota in range(6) else 'x'}.svg"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self.station
        if not s:
            return None
        attrs = {
            k: v.isoformat() if isinstance(v, date) else v
            for k, v in s.items()
            if not k.startswith("_") and k not in ("detalhes", "latitude", "longitude", "cidade_id")
        }
        attrs["link_mapa"] = maps_url(s)
        detalhes = s.get("detalhes") or {}
        if detalhes:
            attrs["produtos"] = detalhes.get("produtos")
            attrs["origem_combustivel"] = detalhes.get("origem_combustivel")
            attrs["fiscalizacoes_detalhe"] = detalhes.get("fiscalizacoes")
            attrs["irregularidades"] = detalhes.get("irregularidades")
            attrs["amostras_detalhe"] = detalhes.get("ensaios_nao_conformes")
        return attrs
