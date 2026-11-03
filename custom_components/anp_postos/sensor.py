"""Sensores agregados por cidade."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import maps_url
from .data import AnpPostosConfigEntry
from .entity import AnpPostosEntity


def _brief(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "nome": s["nome"] or s["razao_social"],
        "cnpj": s["cnpj_formatado"],
        "nota": s["nota"],
        "endereco": f"{s['endereco']}, {s['bairro']}",
        "distribuidora": s["distribuidora"],
        "interditado": s["interditado"],
        "infracoes": s["infracoes"],
        "link_mapa": maps_url(s),
    }


def _avg(stations: list[dict[str, Any]]) -> float | None:
    notas = [s["nota"] for s in stations if s["nota"] is not None]
    return round(sum(notas) / len(notas), 2) if notas else None


@dataclass(frozen=True, kw_only=True)
class AnpSensorDescription(SensorEntityDescription):
    value_fn: Callable[[list[dict[str, Any]]], Any]
    attrs_fn: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None


SENSORS: tuple[AnpSensorDescription, ...] = (
    AnpSensorDescription(
        key="postos",
        translation_key="postos",
        icon="mdi:gas-station",
        native_unit_of_measurement="postos",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=len,
        attrs_fn=lambda st: {
            "por_distribuidora": dict(Counter(s["distribuidora"] for s in st).most_common()),
        },
    ),
    AnpSensorDescription(
        key="irregulares",
        translation_key="irregulares",
        icon="mdi:gas-station-off",
        native_unit_of_measurement="postos",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: sum(s["irregular"] for s in st),
        attrs_fn=lambda st: {
            "postos": [_brief(s) for s in sorted(st, key=lambda s: s["nota"] or 0) if s["irregular"]]
        },
    ),
    AnpSensorDescription(
        key="nota_media",
        translation_key="nota_media",
        icon="mdi:star-half-full",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_avg,
        attrs_fn=lambda st: {
            "por_nota": {
                str(n): sum(1 for s in st if s["nota"] == n) for n in range(5, -1, -1)
            },
            "melhores": [_brief(s) for s in st if s["nota"] == 5][:10],
        },
    ),
    AnpSensorDescription(
        key="interditados",
        translation_key="interditados",
        icon="mdi:cancel",
        native_unit_of_measurement="postos",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: sum(bool(s["interditado"]) for s in st),
        attrs_fn=lambda st: {"postos": [_brief(s) for s in st if s["interditado"]]},
    ),
    AnpSensorDescription(
        key="infracoes",
        translation_key="infracoes",
        icon="mdi:alert-octagon",
        native_unit_of_measurement="infrações",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: sum(s["infracoes"] for s in st),
        attrs_fn=lambda st: {
            "qualidade": sum(s["infracoes_qualidade"] for s in st),
            "quantidade": sum(s["infracoes_quantidade"] for s in st),
            "fiscalizacoes": sum(s["fiscalizacoes"] for s in st),
            "fiscalizacoes_com_infracao": sum(s["fiscalizacoes_com_infracao"] for s in st),
        },
    ),
    AnpSensorDescription(
        key="amostras_nao_conformes",
        translation_key="amostras_nao_conformes",
        icon="mdi:flask-outline",
        native_unit_of_measurement="amostras",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: sum(s["amostras_nao_conformes"] for s in st),
        attrs_fn=lambda st: {"amostras_coletadas": sum(s["amostras"] for s in st)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AnpPostosConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        AnpCitySensor(coordinator, city_id, desc)
        for city_id in coordinator.data
        for desc in SENSORS
    )


class AnpCitySensor(AnpPostosEntity, SensorEntity):
    entity_description: AnpSensorDescription
    _unrecorded_attributes = frozenset({"postos", "melhores", "por_distribuidora"})

    def __init__(self, coordinator, city_id: str, description: AnpSensorDescription) -> None:
        super().__init__(coordinator, city_id)
        self.entity_description = description
        self._attr_unique_id = f"{city_id}_{description.key}"

    @property
    def _stations(self) -> list[dict[str, Any]]:
        return list(self.coordinator.data[self.city_id]["stations"].values())

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._stations)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self._stations) if fn else None
