"""Veredito e posto mais próximo (sem Home Assistant)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "anp_postos"))
import verdict as v  # noqa: E402

BASE = {"nome": "POSTO X", "distribuidora": "VIBRA", "irregular": False, "nota": 5, "infracoes": 0}


def test_verdict():
    assert v.verdict(BASE, 2) == v.OK
    assert v.verdict({**BASE, "nota": 4}, 2) == v.OK
    assert v.verdict({**BASE, "nota": 4, "infracoes": 1}, 2) == v.ATTENTION
    assert v.verdict({**BASE, "nota": 3}, 2) == v.ATTENTION
    assert v.verdict({**BASE, "nota": 5, "irregular": True}, 2) == v.AVOID  # interditado
    assert v.verdict({**BASE, "nota": None}, 2) == v.UNKNOWN


def test_nearest():
    casa = (-5.9414, -35.2509)
    perto = {**BASE, "latitude": -5.94141, "longitude": -35.250935}  # POSTO REAL
    longe = {**BASE, "latitude": -5.79005167, "longitude": -35.20416}
    station, dist = v.nearest_station([longe, perto, {"latitude": None}], *casa)
    assert station is perto and dist < 10
    assert 16_000 < v.distance_m(*casa, longe["latitude"], longe["longitude"]) < 18_000


def test_message():
    title, body = v.arrival_message(
        {**BASE, "nota": 2, "interditado": "INTERDIÇÃO PARCIAL", "motivo_interdicao": "BOMBA",
         "detalhes": {"irregularidades": [{"data": "1/1/2026", "descricao": "Etanol reprovado", "classificacao": ""}]}},
        v.AVOID,
    )
    assert title == "⛔ Não abasteça aqui — POSTO X"
    assert "Interditado: BOMBA" in body and "1/1/2026: Etanol reprovado" in body
