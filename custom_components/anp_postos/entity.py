"""Base: um dispositivo por cidade."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SITE_URL
from .const import ATTRIBUTION, DOMAIN
from .coordinator import AnpPostosCoordinator


class AnpPostosEntity(CoordinatorEntity[AnpPostosCoordinator]):
    """Entidade ligada ao dispositivo 'Postos <cidade>'."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: AnpPostosCoordinator, city_id: str) -> None:
        super().__init__(coordinator)
        self.city_id = city_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, city_id)},
            name=f"Postos {coordinator.data[city_id]['name']}",
            manufacturer="ANP",
            model="ANP Com Vc - Postos",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SITE_URL,
        )

    @property
    def available(self) -> bool:
        return super().available and self.city_id in (self.coordinator.data or {})
