"""Cliente do ANP Com Vc - Postos (https://anpcomvcpostos.anp.gov.br).

O site é um app Oracle APEX 24.2 (app 204) sem API pública. Fluxo reconstruído
(detalhes em REVERSE_ENGINEERING.md):

1. GET home -> sessão APEX (cookie + p_instance) e lista de cidades (<select P1_CIDADE>).
2. Dynamic Action PL/SQL (wwv_flow.ajax) com P1_CIDADE -> devolve P1_MUNICIPIO/P1_UF.
3. Submit AJAX (wwv_flow.accept, request busca_cidade_lista) -> redirectURL assinada.
4. Página postos-lista: Interactive Grid com 42 colunas (25 linhas embutidas);
   o resto vem do fetch do IG (wwv_flow.ajax, regions[].fetchData).
5. Cada linha traz a URL assinada do posto-geral, que leva às páginas de
   fiscalizações, amostras, produtos e origem do combustível.

Os ajaxIdentifier/checksums são amarrados à sessão, então tudo é lido da página.
Este módulo não importa Home Assistant (testável isolado).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import html
import json
import re
from typing import Any
from urllib.parse import unquote, urljoin

import aiohttp

ORIGIN = "https://anpcomvcpostos.anp.gov.br"
BASE = f"{ORIGIN}/ordsdw/"
HOME = f"{BASE}r/sfi_apex/anpcomvcpostos/home"
SITE_URL = f"{ORIGIN}/"
APP_ID = "204"
TIMEOUT = aiohttp.ClientTimeout(total=90)
HEADERS = {"User-Agent": "Mozilla/5.0 (HomeAssistant anp_postos)"}
AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}


class AnpError(Exception):
    """Erro genérico do site da ANP."""


class AnpConnectionError(AnpError):
    """Falha de rede/timeout."""


# ---------------------------------------------------------------- parsing puro


def _unescape_js(text: str) -> str:
    return text.replace("\\u002F", "/").replace("\\u0026", "&").replace("\\u0025", "%")


def _input_value(page: str, element_id: str) -> str | None:
    tag = re.search(r'<input[^>]*id="%s"[^>]*>' % re.escape(element_id), page)
    if not tag:
        return None
    value = re.search(r'value="([^"]*)"', tag.group(0))
    return html.unescape(value.group(1)) if value else None


def parse_cities(page: str) -> dict[str, str]:
    """{id: "NATAL - RN"} a partir do <select id="P1_CIDADE"> da home."""
    start = page.find('id="P1_CIDADE"')
    end = page.find("</select>", start)
    if start < 0 or end < 0:
        raise AnpError("lista de cidades não encontrada")
    return {
        cid: html.unescape(name).strip()
        for cid, name in re.findall(
            r'<option value="(\d+)"[^>]*>([^<]+)</option>', page[start:end]
        )
    }


def parse_number(value: Any) -> float | None:
    """'5,043' / '-05,76872790' -> float (formato pt-BR do APEX)."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(".", "").replace(",", ".")) if "," in str(
            value
        ) else float(value)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_number(value)
    return None if number is None else int(number)


def parse_date(value: Any) -> date | None:
    """'29/11/2023' -> date."""
    try:
        return datetime.strptime(str(value), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_grids(page: str) -> dict[str, dict[str, Any]]:
    """Todas as Interactive Grids da página.

    Retorna {region_id: {"columns": [...], "rows": [{col: valor}], "meta": [...],
    "more": bool, "config": {...}}}. As linhas embutidas seguem a ordem do
    array columns da config do IG; o último item de cada linha é o metadado
    (salt/protected/links).
    """
    grids: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r"var gIg(\d+)data = (\{.*?\n\})\s*;", page, re.S):
        region = match.group(1)
        data = json.loads(match.group(2))
        cfg_at = page.find(f"#R{region}_ig")
        cfg_end = page.find('"ajaxColumns"', cfg_at)
        columns = [
            json.loads(f'"{name}"')
            for name in re.findall(
                r'\{"id":"\d+","name":"((?:[^"\\]|\\.)*)"', page[cfg_at:cfg_end]
            )
        ]
        cfg = page[cfg_at : page.find("\n", cfg_at)]

        def _cfg(key: str, src: str = cfg) -> str | None:
            found = re.search(r'"%s":"([^"]+)"' % key, src)
            return _unescape_js(found.group(1)) if found else None

        report = re.search(r'"savedReports":\[\{"id":"(\d+)"', cfg)
        rows, meta = [], []
        for values in data.get("values", []):
            extra = values[-1] if values and isinstance(values[-1], dict) else {}
            meta.append(extra)
            rows.append(dict(zip(columns, values, strict=False)))
        grids[region] = {
            "columns": columns,
            "rows": rows,
            "meta": meta,
            "more": bool(data.get("moreData")),
            "total": data.get("totalRows"),
            "config": {
                "id": region,
                "ajaxIdentifier": _cfg("ajaxIdentifier"),
                "ajaxColumns": _cfg("ajaxColumns"),
                "reportId": report.group(1) if report else None,
            },
        }
    return grids


def parse_table(page: str) -> list[dict[str, str]]:
    """Primeiro relatório clássico (t-Report) como lista de dicts."""
    table = re.search(r'<table[^>]*class="t-Report-report[^"]*"[^>]*>(.*?)</table>', page, re.S)
    if not table:
        return []
    headers = [html.unescape(h) for h in re.findall(r'<th[^>]*id="([^"]+)"', table.group(1))]
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", table.group(1), re.S):
        cells = [
            html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        ]
        if cells:
            rows.append(dict(zip(headers, cells, strict=False)))
    return rows


def parse_redirects(page: str) -> dict[str, str]:
    """{alias_da_pagina: url_assinada} dos botões apex.navigation.redirect."""
    page = _unescape_js(page)
    links = {
        alias: url
        for url, alias in (
            (m.group(1), m.group(2))
            for m in re.finditer(
                r"redirect\('(/ordsdw/r/sfi_apex/anpcomvcpostos/([a-z0-9-]+)\?[^']+)'", page
            )
        )
    }
    nota = re.search(r"url=([^&']*nota[^&']*)", page)
    if nota:
        links["nota"] = unquote(unquote(nota.group(1)))
    return links


def normalize_station(row: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Linha do IG postos-lista -> dict com tipos Python e chaves estáveis."""

    def text(key: str) -> str | None:
        value = row.get(key)
        return html.unescape(str(value)).strip() or None if value is not None else None

    lat = parse_number(row.get("LAT_NUM")) or parse_number(row.get("LATITUDE"))
    lon = parse_number(row.get("LON_NUM")) or parse_number(row.get("LONGITUDE"))
    url = ((meta or {}).get("fields") or {}).get("CNPJ", {}).get("url")
    return {
        "cod_instalacao": text("COD_INSTALACAO"),
        "cnpj": text("CNPJ"),
        "cnpj_formatado": text("CNPJ_TXT"),
        "razao_social": text("RAZAO_SOCIAL"),
        "nome": text("NOME"),
        "distribuidora": text("DISTRIBUIDORA"),
        "distribuidora_desde": parse_date(row.get("DISTRIBUIDORA_DATA_INICIO")),
        "volume_outras_distribuidoras_pct": parse_number(
            row.get("PARTICIAPCAO_DITRIBUIDORA_PERC")
        ),
        "status_recebimento": text("STATUS_RECEBIMENTO"),
        "tipo": text("POSTO_TIPO"),
        "interditado": text("INTERDITADO"),
        "motivo_interdicao": text("MOTIVO_INTERDICAO"),
        "situacao": text("SITUACAO_CORRIGIDA") or text("SITUACAO_ATUAL"),
        "endereco": text("ENDERECO"),
        "complemento": text("COMPLEMENTO"),
        "bairro": text("BAIRRO"),
        "cep": text("CEP"),
        "municipio": text("MUNICIPIO"),
        "uf": text("UF"),
        "latitude": lat,
        "longitude": lon,
        "autorizacao": text("AUTORIZACAO"),
        "numero_despacho": text("NUMERO_DESPACHO"),
        "portaria_resolucao": text("PORTARIA_RESOLUCAO"),
        "numero_processo": text("N_PROCESSO"),
        "dou_envio": parse_date(row.get("DOU_DATA_ENVIO")),
        "dou_publicacao": parse_date(row.get("DOU_DATA_PUBLICACAO")),
        "tempo_autorizacao_anos": parse_int(row.get("TEMPO_AUTORIZACAO_ANOS")),
        "fiscalizacoes": parse_int(row.get("FISCALIZACOES_TOTAL")) or 0,
        "fiscalizacoes_sem_infracao": parse_int(row.get("FISCALIZACOES_SEM_INFRACAO")) or 0,
        "fiscalizacoes_com_infracao": parse_int(row.get("FISCALIZACOES_COM_INFRACAO")) or 0,
        "infracoes_qualidade": parse_int(row.get("INFRACAO_QUALIDADE")) or 0,
        "infracoes_quantidade": parse_int(row.get("INFRACAO_QUANTIDADE")) or 0,
        "infracoes": parse_int(row.get("INFRACAO_TOTAL")) or 0,
        "amostras": parse_int(row.get("AMOSTRAS_TOTAL")) or 0,
        "amostras_nao_conformes": parse_int(row.get("AMOSTRAS_NC")) or 0,
        "amostras_conformes": parse_int(row.get("AMOSTRAS_CONFORME")) or 0,
        "nota": parse_int(row.get("NOTA")),
        "_url": _unescape_js(url) if url else None,
    }


def is_irregular(station: dict[str, Any], max_nota: int) -> bool:
    """Irregular = interditado, fora de operação, ou nota <= limite."""
    if station.get("interditado"):
        return True
    situacao = (station.get("situacao") or "").upper()
    if situacao and "OPERA" not in situacao:
        return True
    nota = station.get("nota")
    return nota is not None and nota <= max_nota


def build_details(
    grids: dict[str, list[dict[str, Any]]], origem: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Grids das páginas fiscalizacoes/amostras/posto-detalhe + tabela de origem -> dict.

    Os nomes de coluna dessas grids são frases ("Número do Documento de
    Fiscalização"), então a leitura é posicional.
    """
    details: dict[str, Any] = {}
    fisc = grids.get("fiscalizacoes") or []
    if fisc:
        details["fiscalizacoes"] = [
            {"df": _nth(r, 0), "data": _nth(r, 1), "orgao": _nth(r, 2), "infracao": _nth(r, 3)}
            for r in fisc[0]["rows"]
        ]
    if len(fisc) > 1:
        details["irregularidades"] = [
            {
                "df": _nth(r, 0),
                "data": _nth(r, 1),
                "componente": _nth(r, 2),
                "classificacao": _nth(r, 3),
                "descricao": _nth(r, 4),
            }
            for r in fisc[1]["rows"]
        ]
    amostras = grids.get("amostras") or []
    if amostras:
        details["amostras"] = [
            {"data": _nth(r, 0), "produto": _nth(r, 1), "conforme": _nth(r, 2)}
            for r in amostras[0]["rows"]
        ]
    if len(amostras) > 1:
        details["ensaios_nao_conformes"] = [
            {"data": _nth(r, 0), "produto": _nth(r, 1), "ensaio": _nth(r, 2), "resultado": _nth(r, 3)}
            for r in amostras[1]["rows"]
        ]
    produtos = grids.get("posto-detalhe") or []
    if produtos:
        details["produtos"] = sorted({r["PRODUTO"] for r in produtos[0]["rows"] if r.get("PRODUTO")})
    if origem is not None:
        details["origem_combustivel"] = [
            {
                "distribuidora": r.get("DISTRIBUIDORA DA ORIGEM DO COMBUSTÍVEL"),
                "volume_pct": parse_number(r.get("VOLUME RECEBIDO %")),
            }
            for r in origem
        ]
    return details


def _nth(row: dict[str, Any], index: int) -> Any:
    values = [v for v in row.values() if not isinstance(v, dict)]
    if index >= len(values):
        return None
    return html.unescape(values[index]) if isinstance(values[index], str) else values[index]


# ---------------------------------------------------------------- cliente HTTP


@dataclass
class _Page:
    url: str
    text: str
    instance: str = ""
    step: str = ""
    context: str = ""
    salt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class AnpPostosClient:
    """Uma instância = uma sessão APEX (cookie jar próprio)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, url: str) -> _Page:
        text = await self._request("GET", url)
        return _Page(
            url=url,
            text=text,
            instance=_input_value(text, "pInstance") or "",
            step=_input_value(text, "pFlowStepId") or "",
            context=_input_value(text, "pContext") or "",
            salt=_input_value(text, "pSalt") or "",
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> str:
        try:
            async with self._session.request(
                method, url, timeout=TIMEOUT, headers={**HEADERS, **kwargs.pop("headers", {})}, **kwargs
            ) as resp:
                if resp.status >= 400:
                    raise AnpError(f"HTTP {resp.status} em {url.split('?')[0]}")
                return await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AnpConnectionError(str(err)) from err

    async def _ajax(self, page: _Page, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        text = await self._request(
            "POST",
            f"{BASE}{endpoint}?p_context={page.context}",
            data={
                "p_flow_id": APP_ID,
                "p_flow_step_id": page.step,
                "p_instance": page.instance,
                "p_debug": "",
                **data,
            },
            headers={**AJAX_HEADERS, "Referer": page.url},
        )
        try:
            return json.loads(text)
        except ValueError as err:
            # APEX devolve a home em HTML quando a sessão/checksum não bate.
            raise AnpError(f"resposta inesperada de {endpoint}") from err

    async def async_get_cities(self) -> dict[str, str]:
        """Todas as cidades com postos ({id: 'NOME - UF'})."""
        return parse_cities((await self._get(HOME)).text)

    async def async_get_stations(self, city_id: str) -> list[dict[str, Any]]:
        """Todos os postos autorizados de uma cidade (42 campos do IG)."""
        home = await self._get(HOME)
        protected = _input_value(home.text, "pPageItemsProtected")
        da = re.search(
            r'"ajaxIdentifier":"([^"]+)","attribute01":"#P1_CIDADE"', home.text
        )
        if not da:
            raise AnpError("dynamic action da cidade não encontrada")
        items = await self._ajax(
            home,
            "wwv_flow.ajax",
            {
                "p_request": "PLUGIN=" + _unescape_js(da.group(1)),
                "p_json": json.dumps(
                    {
                        "pageItems": {
                            "itemsToSubmit": [{"n": "P1_CIDADE", "v": city_id}],
                            "protected": protected,
                            "rowVersion": "",
                        },
                        "salt": home.salt,
                    }
                ),
            },
        )
        values = {i["id"]: i["value"] for i in items.get("item", [])}
        submit = await self._ajax(
            home,
            "wwv_flow.accept",
            {
                "p_request": "busca_cidade_lista",
                "p_reload_on_submit": "S",
                "p_page_submission_id": _input_value(home.text, "pPageSubmissionId"),
                "p_json": json.dumps(
                    {
                        "pageItems": {
                            "itemsToSubmit": [
                                {"n": "P1_CIDADE_BUSCA", "v": ""},
                                {"n": "P1_CIDADE", "v": city_id},
                                {"n": "P1_CNPJ", "v": ""},
                                {"n": "P1_MUNICIPIO", "v": values.get("P1_MUNICIPIO", "")},
                                {"n": "P1_UF", "v": values.get("P1_UF", "")},
                            ],
                            "protected": protected,
                            "rowVersion": "",
                            "formRegionChecksums": [],
                        },
                        "salt": home.salt,
                    }
                ),
            },
        )
        if not submit.get("redirectURL"):
            raise AnpError(f"cidade {city_id} rejeitada: {submit.get('errors')}")
        lista = await self._get(urljoin(BASE, submit["redirectURL"]))
        grids = parse_grids(lista.text)
        if not grids:
            raise AnpError("grid de postos não encontrada")
        grid = next(iter(grids.values()))
        rows, meta = grid["rows"], grid["meta"]
        if grid["more"]:
            rows, meta = await self._fetch_grid(lista, grid)
        return [normalize_station(r, m) for r, m in zip(rows, meta, strict=False)]

    async def _fetch_grid(self, page: _Page, grid: dict[str, Any]) -> tuple[list, list]:
        """Busca todas as linhas de um IG paginado (fetchData maxRows alto)."""
        resp = await self._ajax(
            page,
            "wwv_flow.ajax",
            {
                "p_json": json.dumps(
                    {
                        "regions": [
                            {
                                **grid["config"],
                                "view": "grid",
                                "fetchData": {"version": 1, "firstRow": 1, "maxRows": 10000},
                            }
                        ],
                        "salt": page.salt,
                    }
                )
            },
        )
        values = resp["regions"][0]["fetchedData"]["values"]
        rows, meta = [], []
        for v in values:
            meta.append(v[-1] if v and isinstance(v[-1], dict) else {})
            rows.append(dict(zip(grid["columns"], v, strict=False)))
        return rows, meta

    async def async_get_details(self, station: dict[str, Any]) -> dict[str, Any]:
        """Fiscalizações, irregularidades, amostras, produtos e origem do combustível.

        Usa a URL assinada da linha, então precisa ser chamada na mesma sessão
        de async_get_stations.
        """
        if not station.get("_url"):
            return {}
        geral = await self._get(urljoin(BASE, station["_url"]))
        links = parse_redirects(geral.text)
        grids: dict[str, list[dict[str, Any]]] = {}
        origem = None
        for alias in ("fiscalizacoes", "amostras", "posto-detalhe", "origem-combustivel"):
            if alias not in links:
                continue
            sub = await self._get(urljoin(ORIGIN, links[alias]))
            if alias == "origem-combustivel":
                origem = parse_table(sub.text)
                continue
            grids[alias] = list(parse_grids(sub.text).values())
            for grid in grids[alias]:
                if grid["more"]:  # >25 linhas: completa via fetch do IG
                    grid["rows"], grid["meta"] = await self._fetch_grid(sub, grid)
        return build_details(grids, origem)
