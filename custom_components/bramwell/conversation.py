"""Conversation entity — the core Voice PE integration point.

When a HA Voice PE puck wakes ("Hey Alfred"), HA's Assist pipeline runs
its STT, then forwards the transcript to whichever conversation.agent is
selected. This entity registers as that agent and proxies every turn to
the Brain's ``/api/conversation/process`` endpoint, then translates the
HA-shaped envelope returned by the Brain back into a HA
``IntentResponse``.

The audio path is owned end-to-end by HA on this flow — Bramwell only
sees text. See ``business/VOICE-ARCHITECTURE-BLUEPRINT.md`` §10 for why
the dashboard mic path and the Voice PE path stay separate.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import aiohttp
import async_timeout
from homeassistant.components.conversation import (
    AbstractConversationAgent,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.intent import IntentResponse, IntentResponseType

from .const import (
    CONF_BRAIN_URL,
    CONVERSATION_ENDPOINT,
    CONVERSATION_TIMEOUT_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# HA's IntentResponseType enum mirrors the Brain's response_type field.
# Mapping kept explicit so a contract drift on either side fails loudly
# at this boundary.
_RESPONSE_TYPE_MAP: dict[str, IntentResponseType] = {
    "action_done": IntentResponseType.ACTION_DONE,
    "query_answer": IntentResponseType.QUERY_ANSWER,
    "error": IntentResponseType.ERROR,
    "partial": IntentResponseType.PARTIAL_ACTION_DONE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Spin up the conversation entity for this config entry."""
    # ConversationEntity self-registers via the entity platform on
    # HA 2024.4+. Manifest pins minimum HA at 2024.12.0, so an explicit
    # `conversation.async_set_agent` would double-register the agent.
    async_add_entities([BramwellConversationAgent(hass, entry)])


class BramwellConversationAgent(ConversationEntity, AbstractConversationAgent):
    """HA conversation.agent wrapper for the Bramwell Brain."""

    _attr_has_entity_name = True
    _attr_name = "Alfred"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Init agent with the config-entry-scoped Brain URL.

        ``self.hass`` is set by HA's Entity base class in
        ``async_added_to_hass()`` — assigning here would shadow the
        lifecycle-tracked field, so we keep just the entry/URL.
        """
        self._entry = entry
        # Brain-URL-keyed unique_id (falls back to entry_id) so re-adding
        # the integration reclaims this entity instead of orphaning it.
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._brain_url: str = entry.data[CONF_BRAIN_URL]

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Match every language — Alfred's LLM does the language work."""
        return MATCH_ALL

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Forward a transcript to the Brain and translate the reply."""
        session = async_get_clientsession(self.hass)
        url = f"{self._brain_url}{CONVERSATION_ENDPOINT}"

        # HA passes ``conversation_id=None`` for the first turn of a new
        # conversation. The Brain handles that case by synthesizing a
        # session bucket, so we forward None as-is rather than making
        # one up here — keeps the canonical-id rule in one place.
        payload: dict[str, Any] = {
            "text": user_input.text,
            "conversation_id": user_input.conversation_id,
            "language": user_input.language,
            "user_id": user_input.context.user_id if user_input.context else None,
            "device_id": user_input.device_id,
        }

        try:
            async with async_timeout.timeout(CONVERSATION_TIMEOUT_SECONDS):
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        _LOGGER.warning(
                            "Brain returned HTTP %s for conversation: %s",
                            resp.status,
                            await resp.text(),
                        )
                        return self._error_result(
                            user_input,
                            "I'm afraid the Bramwell brain is unreachable, sir.",
                        )
                    body = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Brain unreachable: %s", err)
            return self._error_result(
                user_input,
                "I'm afraid I can't reach the Bramwell brain at the moment, sir.",
            )

        return self._build_result(user_input, body)

    # --- Helpers ---

    def _build_result(
        self, user_input: ConversationInput, body: dict[str, Any]
    ) -> ConversationResult:
        """Translate the Brain's HA-shaped envelope into a ConversationResult."""
        response_envelope = body.get("response", {}) or {}
        speech = (
            response_envelope.get("speech", {})
            .get("plain", {})
            .get("speech", "")
        )
        language = response_envelope.get("language") or user_input.language or "en"
        response_type_str = response_envelope.get("response_type") or "query_answer"
        response_type = _RESPONSE_TYPE_MAP.get(
            response_type_str, IntentResponseType.QUERY_ANSWER
        )

        intent = IntentResponse(language=language)
        intent.response_type = response_type
        intent.async_set_speech(speech or "")

        # Update the status sensors (sensor.bramwell_last_command /
        # sensor.bramwell_last_response) with this turn. The coordinator
        # is stashed by the sensor platform's async_setup_entry; if the
        # sensor platform hasn't loaded yet (cold-start race) skip
        # silently — the next turn will catch up.
        self._record_turn_in_coordinator(user_input.text, speech or "")

        conversation_id = body.get("conversation_id") or user_input.conversation_id
        return ConversationResult(
            response=intent, conversation_id=conversation_id
        )

    def _record_turn_in_coordinator(self, command: str, response: str) -> None:
        """Push the latest user/Alfred text into the sensor coordinator.

        Wraps the lookup in a try/except so any unexpected change in the
        sensor platform's storage shape can't crash a conversation turn.
        Last-command / last-response sensors are nice-to-have automations
        glue; they should never block voice replies on failure.
        """
        try:
            from .sensor import COORDINATOR_KEY  # local import — break cycle

            entry_data = (
                self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            )
            coordinator = entry_data.get(COORDINATOR_KEY)
            if coordinator is not None:
                coordinator.record_turn(command, response)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Skipped sensor record_turn", exc_info=True)

    def _error_result(
        self, user_input: ConversationInput, message: str
    ) -> ConversationResult:
        """Build a graceful error envelope for HA when the Brain is down."""
        intent = IntentResponse(language=user_input.language or "en")
        intent.response_type = IntentResponseType.ERROR
        intent.async_set_speech(message)
        return ConversationResult(
            response=intent, conversation_id=user_input.conversation_id
        )
