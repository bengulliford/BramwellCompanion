"""Bramwell companion — registers Alfred as a HA conversation.agent.

This integration is the free-tier hands-free entrypoint to Alfred. HA owns
audio transport (mic → STT → conversation agent → TTS → speaker output via
Nabu Casa Cloud or whatever STT/TTS the user has wired in); Bramwell only
sees text-in / text-out via ``POST /api/conversation/process`` on the
Brain.

Sprint plan: ``business/SPRINT-10-VOICE-PE-INTEGRATION.md``.
Architecture: ``business/VOICE-ARCHITECTURE-BLUEPRINT.md`` §10.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_KOKORO_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# TTS platform is conditionally forwarded based on whether the user filled
# in a Kokoro URL during config flow. Skipping the platform forward keeps
# "Bramwell Alfred" out of HA's TTS dropdown for users on Path B/C
# (community Wyoming-Kokoro add-on or HA's default TTS).
_BASE_PLATFORMS: list[Platform] = [Platform.CONVERSATION, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bramwell companion from a config entry.

    The entry's ``data`` carries ``brain_url`` + ``api_token`` (always),
    plus optional ``kokoro_url`` + ``kokoro_voice`` for users who want
    the canonical Alfred voice via Bramwell-managed Kokoro. Per-entry
    runtime state lives on ``hass.data[DOMAIN][entry.entry_id]`` so
    multiple Brain hosts could be configured in the future without code
    changes.
    """
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = dict(entry.data)

    platforms = list(_BASE_PLATFORMS)
    if entry.data.get(CONF_KOKORO_URL):
        platforms.append(Platform.TTS)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    _LOGGER.info(
        "Bramwell companion ready: Brain=%s, platforms=%s",
        entry.data["brain_url"],
        [p.value for p in platforms],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down a config entry."""
    platforms = list(_BASE_PLATFORMS)
    if entry.data.get(CONF_KOKORO_URL):
        platforms.append(Platform.TTS)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
