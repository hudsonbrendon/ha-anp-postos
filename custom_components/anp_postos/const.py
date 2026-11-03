"""Constantes da integração ANP Postos."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "anp_postos"
ATTRIBUTION = "Dados: ANP Com Vc - Postos (anpcomvcpostos.anp.gov.br)"

CONF_CITIES = "cities"
CONF_MAX_NOTA = "max_nota"
CONF_NOTIFY = "notify_services"
CONF_SCAN_HOURS = "scan_interval_hours"
CONF_DETAILS = "fetch_details"

DEFAULT_MAX_NOTA = 2
DEFAULT_SCAN_HOURS = 12
DEFAULT_DETAILS = True

EVENT_IRREGULAR = f"{DOMAIN}_posto_irregular"
STATIC_URL = f"/{DOMAIN}"

# Cores da legenda do mapa do site (Nota 0..5).
NOTA_COLORS = {
    0: "#d93025",
    1: "#ff9a4d",
    2: "#ffd43b",
    3: "#9ad800",
    4: "#1faf5b",
    5: "#084c2e",
}
