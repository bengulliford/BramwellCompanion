"""Constants for the Bramwell companion integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bramwell"
"""HA integration domain. Lives at custom_components/bramwell/."""

CONF_BRAIN_URL: Final = "brain_url"
"""Config-flow key for the user-supplied Bramwell Brain URL."""

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

CONVERSATION_TIMEOUT_SECONDS: Final = 30.0
"""Hard timeout on each per-turn Brain conversation POST. The Voice PE
flow target is 2.5–3.0s wake-to-first-audio per 02-PRODUCT-SPEC.md:132,
but with Gemini + tool calls + state lookups the realistic envelope is
4–8s — clipping at 5s turns "slightly slow" into HTTP 499 (client-
closed) and intermittent turn failures (observed 2026-05-19 in live
testing). 30s aligns with the HA convention for LLM-backed conversation
agents (Google Generative AI / OpenAI integrations all use
30–60s) and treats *exceeding* this window as the real failure mode,
not 5s.

NOTE — config-flow setup uses CONNECT_TIMEOUT_SECONDS below, NOT this
constant. PR #245 review (round 1, P3) flagged that the setup-flow
connectivity check would otherwise inherit 30s, so a misconfigured host
shows a long spinner before "can't connect". Setup wants fast-fail."""

CONNECT_TIMEOUT_SECONDS: Final = 5.0
"""Setup-time connectivity-check timeout. A one-shot ping in the config
flow's user-form submit, NOT a per-conversation-turn ceiling. Stays at
5s so a misconfigured host / port returns "cannot_connect"
quickly instead of dragging the integration-add dialog to 30s."""

KOKORO_TTS_ENDPOINT: Final = "/v1/audio/speech"
"""Kokoro's OpenAI-compatible TTS endpoint."""

KOKORO_TIMEOUT_SECONDS: Final = 15.0
"""Synthesis timeout. Steady-state Kokoro returns first audio in
150–300ms; 15s gives headroom for cold-start / long replies without
hanging HA's TTS pipeline indefinitely."""

WAKE_WORD_PHRASE: Final = "Alfred"
"""Single locked wake-word phrase for v1 — exactly "Alfred", NOT
"Hey Alfred" (founder decision, 2026-08-07). Advertised by wake_word.py
when alfred.tflite ships without a manifest sidecar; a manifest's own
``wake_word`` field (what the model was actually trained on) wins."""

WAKE_WORD_MODEL_FILENAME: Final = "alfred.tflite"
"""Custom microWakeWord model filename. Ben trains it on the
microWakeWord trainer; it lands in wake_words/ together with its
``alfred.json`` manifest sidecar (phrase + tuning). Not bundled yet —
wake_word.py degrades gracefully until it exists."""

WAKE_WORD_PLACEHOLDER_FILENAME: Final = "alfred_placeholder.tflite"
"""Descope-path fallback filename (locked). wake_word.py prefers
WAKE_WORD_MODEL_FILENAME and selects this when it's the only file;
wake_word_training/download_placeholder.py drops the openWakeWord
placeholder at this path."""

WAKE_WORD_PLACEHOLDER_PHRASE: Final = "Hey Jarvis"
"""Advertised phrase when the placeholder ships without a manifest
sidecar. hey_jarvis is the locked canonical placeholder choice; a
manifest's ``wake_word`` field overrides this."""
