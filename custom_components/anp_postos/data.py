"""Tipos de runtime da integração."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import AnpPostosCoordinator

type AnpPostosConfigEntry = ConfigEntry[AnpPostosData]


@dataclass
class AnpPostosData:
    """Dados guardados em entry.runtime_data."""

    coordinator: AnpPostosCoordinator
