"""Status sensors for the Bramwell companion (Sprint 10 S1).

Three sensors that let users build HA automations off Alfred's state:

- ``sensor.bramwell_alfred_status`` — online / offline / degraded
- ``sensor.bramwell_last_command`` — text of the most recent user command
- ``sensor.bramwell_last_response`` — text of the most recent Alfred reply

The sensors poll the Brain's ``/api/health`` endpoint for status; the
last-command / last-response values are updated by the conversation
entity in-process when a turn lands. This keeps polling minimal — one
GET every 30 seconds — while keeping the conversation values fresh in
real time.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
import async_timeout
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_API_TOKEN, CONF_BRAIN_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)
HEALTH_TIMEOUT_SECONDS = 5.0


COORDINATOR_KEY = "coordinator"
"""hass.data[DOMAIN][entry_id][COORDINATOR_KEY] holds the running coordinator
so the conversation entity (separate platform) can call record_turn() after
each successful turn."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the three status sensors."""
    coordinator = BramwellHealthCoordinator(hass, entry)
    # First-refresh failure (Brain unreachable at HA startup — common during
    # reboots) must NOT abort the whole config-entry setup, otherwise Voice
    # PE goes silent until the user manually reloads the integration.
    # async_refresh() polls once and stores the result; failure leaves
    # last_update_success=False but doesn't throw. The 30s polling cycle
    # recovers whenever the Brain comes back online.
    await coordinator.async_refresh()

    # Stash for the conversation entity to find — it lives on a different
    # platform (Platform.CONVERSATION) and can't reach into sensor module
    # state otherwise.
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
        COORDINATOR_KEY
    ] = coordinator

    async_add_entities(
        [
            AlfredStatusSensor(coordinator, entry),
            LastCommandSensor(coordinator, entry),
            LastResponseSensor(coordinator, entry),
        ]
    )


class BramwellHealthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the Brain's health endpoint and tracks last command/response."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"bramwell_{entry.entry_id}",
            update_interval=SCAN_INTERVAL,
        )
        self._brain_url: str = entry.data[CONF_BRAIN_URL]
        self._api_token: str = entry.data[CONF_API_TOKEN]
        self._last_command: str | None = None
        self._last_response: str | None = None

    @callback
    def record_turn(self, command: str, response: str) -> None:
        """Update last-command / last-response in-process from the conversation entity."""
        self._last_command = command
        self._last_response = response
        self.async_set_updated_data(self._compose_data(status="online"))

    async def _async_update_data(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        url = f"{self._brain_url}/api/health"
        headers = {"Authorization": f"Bearer {self._api_token}"}
        try:
            async with async_timeout.timeout(HEALTH_TIMEOUT_SECONDS):
                async with session.get(url, headers=headers) as resp:
                    if resp.status >= 500:
                        return self._compose_data(status="degraded")
                    if resp.status >= 400:
                        return self._compose_data(status="offline")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Brain unreachable: {err}") from err
        return self._compose_data(status="online")

    def _compose_data(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "last_command": self._last_command,
            "last_response": self._last_response,
        }


class _BramwellSensorBase(CoordinatorEntity[BramwellHealthCoordinator], SensorEntity):
    """Base class for the three status sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BramwellHealthCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry.entry_id


class AlfredStatusSensor(_BramwellSensorBase):
    """``sensor.bramwell_alfred_status`` — online / offline / degraded."""

    _attr_name = "Alfred status"
    _attr_icon = "mdi:robot"

    def __init__(
        self, coordinator: BramwellHealthCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_alfred_status"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("status")


class LastCommandSensor(_BramwellSensorBase):
    """``sensor.bramwell_last_command`` — text of the most recent user command."""

    _attr_name = "Last command"
    _attr_icon = "mdi:microphone-message"

    def __init__(
        self, coordinator: BramwellHealthCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_command"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("last_command")


class LastResponseSensor(_BramwellSensorBase):
    """``sensor.bramwell_last_response`` — text of the most recent Alfred reply."""

    _attr_name = "Last response"
    _attr_icon = "mdi:chat-processing"

    def __init__(
        self, coordinator: BramwellHealthCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_response"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("last_response")
