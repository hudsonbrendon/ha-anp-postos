"""Parsing do ANP Com Vc - Postos contra HTML real salvo (sem Home Assistant)."""

from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "anp_postos"))
import api  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def page(name: str) -> str:
    return (FIX / f"{name}.html").read_text()


def test_cities():
    cities = api.parse_cities(page("home"))
    assert len(cities) > 5000
    assert cities["7221"] == "NATAL - RN"


def test_station_grid():
    grid = next(iter(api.parse_grids(page("lista")).values()))
    assert len(grid["columns"]) == 42 and grid["more"] and grid["total"] == 106
    assert grid["config"]["reportId"] and grid["config"]["ajaxIdentifier"]
    s = api.normalize_station(grid["rows"][0], grid["meta"][0])
    assert s["cnpj"] == "24230106000140"
    assert s["latitude"] == -5.7687279 and s["longitude"] == -35.2715724
    assert s["distribuidora_desde"] == date(2023, 11, 29)
    assert s["volume_outras_distribuidoras_pct"] == 5.043
    assert s["nota"] == 5 and s["amostras_nao_conformes"] == 1
    assert s["_url"].startswith("/ordsdw/r/sfi_apex/anpcomvcpostos/posto-geral?")


def test_irregular():
    base = {"interditado": None, "situacao": "EM OPERAÇÃO", "nota": 3}
    assert not api.is_irregular(base, 2)
    assert api.is_irregular({**base, "nota": 2}, 2)
    assert api.is_irregular({**base, "interditado": "TOTAL"}, 2)
    assert api.is_irregular({**base, "situacao": "REVOGADO"}, 2)
    assert not api.is_irregular({**base, "nota": None}, 2)


def test_details():
    links = api.parse_redirects(page("posto-geral"))
    assert {"fiscalizacoes", "amostras", "posto-detalhe", "origem-combustivel", "nota"} <= set(links)
    grids = {a: list(api.parse_grids(page(a)).values()) for a in ("fiscalizacoes", "amostras", "posto-detalhe")}
    d = api.build_details(grids, api.parse_table(page("origem-combustivel")))
    assert d["fiscalizacoes"][0] == {"df": "704646", "data": "17/4/2026", "orgao": "ANP", "infracao": "Não"}
    assert d["irregularidades"][0]["descricao"].startswith("Amostra Prova de Óleo Diesel S 10")
    assert len(d["amostras"]) == 15
    assert d["ensaios_nao_conformes"][0]["ensaio"] == "Teor de Etanol"
    assert "GASOLINA C COMUM" in d["produtos"]
    assert d["origem_combustivel"] == [{"distribuidora": "VIBRA ENERGIA S.A", "volume_pct": 100.0}]
