"""Bramwell Alfred TTS — proxies HA's TTS pipeline to a Kokoro endpoint.

Registered conditionally in ``__init__.py`` only when the config flow
captured a non-empty ``kokoro_url``. Path B (community Wyoming-Kokoro
HA add-on) and Path C (HA default TTS) leave the URL blank and never
see this entity in their TTS dropdown.

The Kokoro endpoint speaks the OpenAI-compatible
``/v1/audio/speech`` API (whether it's our docker-compose ``voice``
profile container, a Cloud Pro Vultr endpoint, or any other
OpenAI-compatible TTS the user has running). We pass through the
configured voice (default ``bm_george`` for the canonical
British-male Alfred) and ask for MP3 output, which HA's TTS pipeline
plays directly.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout
from homeassistant.components.tts import (
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_KOKORO_URL,
    CONF_KOKORO_VOICE,
    DEFAULT_KOKORO_VOICE,
    DOMAIN,  # noqa: F401 — re-exported for tests / future per-entry lookup
    KOKORO_TIMEOUT_SECONDS,
    KOKORO_TTS_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


# British-only subset of Kokoro v0.19's bundled voice catalog. HA's
# voice-assist pipeline filters the TTS engine picker by whether
# ``async_get_supported_voices(language)`` returns a non-empty list —
# without this catalog the Alfred TTS entity registers but renders
# **greyed out / unselectable** in the pipeline form (the symptom Ben
# hit on 2026-05-20).
#
# Voice-id 2-char prefix encodes language + gender (b=British,
# f=female, m=male). The full Kokoro v0.19 catalog has ~60 voices
# across American / British / Spanish / French / Hindi / Italian /
# Japanese / Portuguese / Mandarin sets (curl
# http://<kokoro>:8880/v1/audio/voices to enumerate yours), but
# Bramwell is the British-butler brand — restricting the engine
# picker to British voices keeps the UI on-brand. Users who want a
# non-British voice can paste any Kokoro voice id into the
# ``kokoro_voice`` field of the companion config flow (or pass it
# as the per-call ``voice`` option), and synthesis will still work;
# the engine picker just won't surface those choices.
#
# bm_george is Alfred's canonical default. Kokoro picks the trained
# language regardless of HA's pipeline language, so we return the
# same catalog for every language query.
_KOKORO_VOICES: list[Voice] = [
    Voice("bm_george", "George — British male (Alfred default)"),
    Voice("bm_lewis", "Lewis — British male"),
    Voice("bf_emma", "Emma — British female"),
    Voice("bf_alice", "Alice — British female"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Spin up the Bramwell Alfred TTS entity for this config entry."""
    async_add_entities([BramwellAlfredTts(hass, entry)])


class BramwellAlfredTts(TextToSpeechEntity):
    """HA TTS entity that proxies to a Kokoro OpenAI-compatible endpoint."""

    _attr_has_entity_name = True
    _attr_name = "Alfred"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        # ``self.hass`` is set by HA's Entity base class in
        # ``async_added_to_hass()`` — assigning here would shadow the
        # lifecycle-tracked field.
        self._entry = entry
        # Unique-id ensures HA registers a stable entity per config entry —
        # users with two Brain hosts wouldn't collide on the TTS entity.
        self._attr_unique_id = f"{entry.entry_id}_alfred_tts"
        self._kokoro_url: str = entry.data[CONF_KOKORO_URL].rstrip("/")
        self._voice: str = entry.data.get(CONF_KOKORO_VOICE) or DEFAULT_KOKORO_VOICE
        # Kokoro auth is intentionally NOT forwarded from the Brain token.
        # If a user has Kokoro behind a separate auth proxy that's a
        # follow-up — adding a dedicated kokoro_token field — not a place
        # to leak the Brain's bearer to a third service.

    @property
    def supported_languages(self) -> list[str] | str:
        # MATCH_ALL — Kokoro's voice models speak whatever language the
        # voice is trained on; HA's pipeline language is informational only.
        return MATCH_ALL

    @property
    def default_language(self) -> str:
        return "en"

    @property
    def supported_options(self) -> list[str]:
        return ["voice"]

    @callback
    def async_get_supported_voices(
        self, language: str  # noqa: ARG002 — Kokoro voice id encodes the language
    ) -> list[Voice] | None:
        """Surface Kokoro's voice catalog for HA's voice-pipeline picker.

        Without this method (or returning ``None`` / empty), HA's voice-
        assist pipeline UI registers the engine but renders it **greyed
        out / unselectable** in the TTS picker — the symptom Ben hit on
        2026-05-20. Kokoro voices speak in the voice's trained language
        regardless of HA's pipeline language, so we return the full
        catalog for every language query (``language`` is intentionally
        unused; the voice id is the language signal).

        Returns a defensive copy (PR #250 review P3.1) so a caller that
        mutates the list doesn't corrupt the module-level catalog the
        next picker query reads.
        """
        return list(_KOKORO_VOICES)

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any] | None = None
    ) -> TtsAudioType:
        """Synthesize MP3 audio for ``message`` via Kokoro.

        Returns ``(None, None)`` on failure so HA's pipeline can fall back
        to its next-configured TTS provider rather than crashing the assist
        turn. Errors get logged with full context for debugging.
        """
        session = async_get_clientsession(self.hass)
        voice = (options or {}).get("voice") or self._voice
        url = f"{self._kokoro_url}{KOKORO_TTS_ENDPOINT}"

        payload = {
            "model": "kokoro",
            "input": message,
            "voice": voice,
            "response_format": "mp3",
        }

        try:
            async with async_timeout.timeout(KOKORO_TIMEOUT_SECONDS):
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Kokoro returned HTTP %s for TTS: %s",
                            resp.status,
                            body[:200],
                        )
                        return None, None
                    audio = await resp.read()
                    return "mp3", audio
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Kokoro unreachable: %s", err)
            return None, None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected Kokoro TTS failure")
            return None, None
