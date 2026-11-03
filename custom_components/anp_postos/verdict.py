"""Posto mais próximo + veredito "abasteço ou não" (sem Home Assistant, testável)."""

from __future__ import annotations

from collections.abc import Iterable
from math import asin, cos, radians, sin, sqrt
from typing import Any

OK, ATTENTION, AVOID, UNKNOWN = "ok", "atencao", "evitar", "sem_nota"

TITLES = {
    OK: "✅ Pode abastecer",
    ATTENTION: "⚠️ Abasteça com atenção",
    AVOID: "⛔ Não abasteça aqui",
    UNKNOWN: "❔ Posto sem nota na ANP",
}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine em metros."""
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(a))


def nearest_station(
    stations: Iterable[dict[str, Any]], lat: float, lon: float
) -> tuple[dict[str, Any] | None, float]:
    """(posto mais próximo, distância em m). ponytail: varredura linear; SP inteiro
    (~1500 postos) leva ~1 ms, índice espacial só se juntar o Brasil todo."""
    best, best_d = None, float("inf")
    for station in stations:
        if station.get("latitude") is None:
            continue
        d = distance_m(lat, lon, station["latitude"], station["longitude"])
        if d < best_d:
            best, best_d = station, d
    return best, best_d


def verdict(station: dict[str, Any], max_nota: int) -> str:
    """Irregular → evitar; nota até max_nota+1 ou amostra/infração recente → atenção."""
    if station.get("irregular"):
        return AVOID
    nota = station.get("nota")
    if nota is None:
        return UNKNOWN
    if nota <= max_nota + 1 or (nota < 5 and station.get("infracoes")):
        return ATTENTION
    return OK


def arrival_message(station: dict[str, Any], level: str) -> tuple[str, str]:
    """Título e corpo curtos para push no celular (texto puro, sem markdown)."""
    name = station.get("nome") or station.get("razao_social")
    title = f"{TITLES[level]} — {name}"
    nota = station.get("nota")
    lines = [
        f"Nota ANP {nota}/5 · {station.get('distribuidora')}" if nota is not None
        else f"Sem nota · {station.get('distribuidora')}",
    ]
    if station.get("interditado"):
        lines.append(f"Interditado: {station.get('motivo_interdicao') or station['interditado']}")
    elif station.get("situacao") and "OPERA" not in station["situacao"].upper():
        lines.append(f"Situação: {station['situacao']}")
    lines.append(
        f"{station.get('fiscalizacoes', 0)} fiscalizações, {station.get('infracoes', 0)} infrações"
        f" (qualidade {station.get('infracoes_qualidade', 0)}, quantidade"
        f" {station.get('infracoes_quantidade', 0)}), amostras ruins"
        f" {station.get('amostras_nao_conformes', 0)}/{station.get('amostras', 0)}"
    )
    detalhes = station.get("detalhes") or {}
    for item in (detalhes.get("irregularidades") or [])[:2]:
        lines.append(f"{item['data']}: {item['descricao'] or item['classificacao']}")
    if level == OK:
        lines.append("Sem infrações da ANP nos últimos 5 anos.")
    return title, "\n".join(lines)
