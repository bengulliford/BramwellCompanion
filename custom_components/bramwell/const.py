"""Constants for the Bramwell companion integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bramwell"
"""HA integration domain. Lives at custom_components/bramwell/."""

CONF_BRAIN_URL: Final = "brain_url"
"""Config-flow key for the user-supplied Bramwell Brain URL."""

CONF_API_TOKEN: Final = "api_token"
"""Config-flow key for the long-lived Brain bearer token."""

CONF_KOKORO_URL: Final = "kokoro_url"
"""Config-flow key for the optional Kokoro TTS endpoint. Empty disables
Bramwell TTS — users on Path B (community Wyoming-Kokoro HA add-on) or
Path C (their own HA TTS like Piper/Nabu Casa) leave this blank."""

CONF_KOKORO_VOICE: Final = "kokoro_voice"
"""Config-flow key for the Kokoro voice id (default bm_george for the
canonical British-male Alfred voice)."""

DEFAULT_BRAIN_URL: Final = "http://homeassistant.local:8080"
"""Default Brain URL when running as a HA add-on alongside Bramwell."""

DEFAULT_KOKORO_URL: Final = "http://homeassistant.local:8880"
"""Default Kokoro URL — matches the docker-compose `voice` profile's
service exposed on the Bramwell host. Users with Kokoro elsewhere
(another machine, Cloud Pro endpoint, etc.) override this."""

DEFAULT_KOKORO_VOICE: Final = "bm_george"
"""Canonical Alfred voice — British male via Kokoro."""

CONVERSATION_ENDPOINT: Final = "/api/conversation/process"
"""Brain HA-conversation-agent adapter (Sprint 10 N1, PR #73)."""

CONVERSATION_TIMEOUT_SECONDS: Final = 5.0
"""Hard timeout on each Brain POST. The Voice PE flow target is 2.5–3.0s
wake-to-first-audio per 02-PRODUCT-SPEC.md:132 — anything past 5s on the
Brain stage alone is a failure mode, not slow success."""

KOKORO_TTS_ENDPOINT: Final = "/v1/audio/speech"
"""Kokoro's OpenAI-compatible TTS endpoint."""

KOKORO_TIMEOUT_SECONDS: Final = 15.0
"""Synthesis timeout. Steady-state Kokoro returns first audio in
150–300ms; 15s gives headroom for cold-start / long replies without
hanging HA's TTS pipeline indefinitely."""

WAKE_WORD_PHRASE: Final = "Hey Alfred"
"""Single locked wake-word phrase for v1 (Sprint 10)."""

WAKE_WORD_MODEL_FILENAME: Final = "alfred.tflite"
"""microWakeWord model filename. Bundled by Sprint 10 N3; until then a
placeholder file documents the descope path."""
