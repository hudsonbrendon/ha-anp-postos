"""Coordinator: baixa os postos das cidades e avisa sobre postos irregulares."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AnpError, AnpPostosClient, is_irregular
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
    EVENT_IRREGULAR,
    LOGGER,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import AnpPostosConfigEntry


def entry_option(entry: AnpPostosConfigEntry, key: str, default: Any) -> Any:
    """Opções sobrescrevem os dados do passo inicial."""
    return entry.options.get(key, entry.data.get(key, default))


def maps_url(station: dict[str, Any]) -> str:
    return (
        "https://www.google.com/maps/search/?api=1&query="
        f"{station['latitude']},{station['longitude']}"
    )


class AnpPostosCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """data = {city_id: {"name": str, "stations": {cod_instalacao: posto}}}."""

    config_entry: AnpPostosConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AnpPostosConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                hours=entry_option(entry, CONF_SCAN_HOURS, DEFAULT_SCAN_HOURS)
            ),
        )
        # Cookie jar próprio: a sessão APEX vive no cookie ORA_WWV_APP_204.
        self._session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
        self._store: Store[dict[str, int | None]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.notified"
        )
        self._notified: dict[str, int | None] | None = None

    async def async_close(self) -> None:
        await self._session.close()

    @property
    def max_nota(self) -> int:
        return int(entry_option(self.config_entry, CONF_MAX_NOTA, DEFAULT_MAX_NOTA))

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        cities: dict[str, str] = entry_option(self.config_entry, CONF_CITIES, {})
        fetch_details = entry_option(self.config_entry, CONF_DETAILS, DEFAULT_DETAILS)
        data: dict[str, dict[str, Any]] = {}
        for city_id, city_name in cities.items():
            # Sessão nova por cidade: as URLs assinadas dos detalhes valem só nela.
            self._session.cookie_jar.clear()
            client = AnpPostosClient(self._session)
            try:
                stations = await client.async_get_stations(city_id)
            except AnpError as err:
                if self.data and city_id in self.data:
                    LOGGER.warning("%s: mantendo dados anteriores (%s)", city_name, err)
                    data[city_id] = self.data[city_id]
                    continue
                raise UpdateFailed(f"{city_name}: {err}") from err
            for station in stations:
                station["irregular"] = is_irregular(station, self.max_nota)
                station["cidade_id"] = city_id
                if station["irregular"] and fetch_details:
                    try:
                        station["detalhes"] = await client.async_get_details(station)
                    except AnpError as err:
                        LOGGER.debug("detalhes de %s: %s", station["cnpj"], err)
            data[city_id] = {
                "name": city_name,
                "stations": {s["cod_instalacao"]: s for s in stations if s["cod_instalacao"]},
            }
        await self._async_notify(data)
        return data

    async def _async_notify(self, data: dict[str, dict[str, Any]]) -> None:
        """Avisa postos que viraram irregulares (ou pioraram a nota) desde o último aviso."""
        if self._notified is None:
            self._notified = await self._store.async_load() or {}
        current = {
            cod: s
            for city in data.values()
            for cod, s in city["stations"].items()
            if s["irregular"]
        }
        new = [
            s
            for cod, s in current.items()
            if cod not in self._notified
            or (
                s["nota"] is not None
                and self._notified[cod] is not None
                and s["nota"] < self._notified[cod]
            )
        ]
        notify_services: list[str] = entry_option(self.config_entry, CONF_NOTIFY, [])
        for station in new:
            title, message = irregular_message(station)
            persistent_notification.async_create(
                self.hass, message, title, f"{DOMAIN}_{station['cod_instalacao']}"
            )
            self.hass.bus.async_fire(EVENT_IRREGULAR, _jsonable(station))
            for service in notify_services:
                domain, _, name = service.partition(".")
                try:
                    await self.hass.services.async_call(
                        domain,
                        name,
                        {
                            "title": title,
                            "message": message,
                            "data": {"url": maps_url(station), "clickAction": maps_url(station)},
                        },
                    )
                except Exception as err:  # noqa: BLE001 - serviço de terceiro
                    LOGGER.warning("falha ao notificar via %s: %s", service, err)
        # Esquece quem saiu da lista: se voltar a ficar irregular, avisa de novo.
        self._notified = {cod: s["nota"] for cod, s in current.items()}
        await self._store.async_save(self._notified)


def irregular_message(station: dict[str, Any]) -> tuple[str, str]:
    """Título e corpo (markdown) do aviso de posto irregular."""
    name = station["nome"] or station["razao_social"]
    title = f"⛽ Posto irregular: {name}"
    lines = [
        f"**{station['razao_social']}** — CNPJ {station['cnpj_formatado']}",
        f"{station['endereco']}, {station['bairro']} — {station['municipio']}/{station['uf']}",
        f"Nota ANP: **{station['nota']}** / 5 · Distribuidora: {station['distribuidora']}",
        f"Fiscalizações: {station['fiscalizacoes']} ({station['fiscalizacoes_com_infracao']} com infração)"
        f" · Infrações: {station['infracoes']} (qualidade {station['infracoes_qualidade']},"
        f" quantidade {station['infracoes_quantidade']})"
        f" · Amostras não conformes: {station['amostras_nao_conformes']}/{station['amostras']}",
    ]
    if station.get("interditado"):
        lines.insert(2, f"🚫 **Interditado**: {station.get('motivo_interdicao') or station['interditado']}")
    if station.get("situacao") and "OPERA" not in station["situacao"].upper():
        lines.insert(2, f"Situação: **{station['situacao']}**")
    irregularidades = (station.get("detalhes") or {}).get("irregularidades") or []
    for item in irregularidades[:5]:
        lines.append(f"- {item['data']}: {item['descricao'] or item['classificacao']}")
    lines.append(f"[Abrir no mapa]({maps_url(station)})")
    return title, "\n".join(lines)


def _jsonable(station: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v.isoformat() if isinstance(v, date) else v
        for k, v in station.items()
        if not k.startswith("_")
    }
