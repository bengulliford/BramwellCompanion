"""Config flow for Bramwell companion.

Captures the Brain URL + long-lived bearer token and validates them with a
lightweight ping against the conversation endpoint before persisting. A
typo or wrong token surfaces here, not later as a silent failure inside
HA's Assist pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_TOKEN,
    CONF_BRAIN_URL,
    CONF_KOKORO_URL,
    CONF_KOKORO_VOICE,
    CONVERSATION_ENDPOINT,
    CONVERSATION_TIMEOUT_SECONDS,
    DEFAULT_BRAIN_URL,
    DEFAULT_KOKORO_URL,
    DEFAULT_KOKORO_VOICE,
    DOMAIN,
    KOKORO_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class BramwellConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Bramwell companion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step user flow: collect URL + token, validate, create entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            brain_url: str = user_input[CONF_BRAIN_URL].rstrip("/")
            api_token: str = user_input[CONF_API_TOKEN]
            kokoro_url_raw = (user_input.get(CONF_KOKORO_URL) or "").strip()
            kokoro_url = kokoro_url_raw.rstrip("/") if kokoro_url_raw else ""
            kokoro_voice = (
                user_input.get(CONF_KOKORO_VOICE) or DEFAULT_KOKORO_VOICE
            ).strip() or DEFAULT_KOKORO_VOICE

            error_key = await self._validate_brain(brain_url, api_token)
            if error_key is None and kokoro_url:
                # Kokoro is optional — only validate when the user actually
                # filled it in. Path B / Path C users leave it blank and
                # never see this branch.
                error_key = await self._validate_kokoro(kokoro_url)

            if error_key is None:
                # The Brain URL is the natural unique-id for this entry —
                # pointing two HA installs at the same Brain is supported,
                # but the same HA install shouldn't register the same Brain
                # twice.
                await self.async_set_unique_id(brain_url)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_BRAIN_URL: brain_url,
                    CONF_API_TOKEN: api_token,
                    CONF_KOKORO_URL: kokoro_url,  # "" when disabled
                    CONF_KOKORO_VOICE: kokoro_voice,
                }
                return self.async_create_entry(
                    title=f"Bramwell ({brain_url})",
                    data=data,
                )
            errors["base"] = error_key

        # Kokoro URL defaults to "" rather than DEFAULT_KOKORO_URL so the
        # average user (Path B / Path C) doesn't have validation pre-fail
        # on a Kokoro endpoint that doesn't exist on their setup. The
        # field's description in translations/en.json points users at the
        # canonical localhost URL when they DO want to fill it in.
        schema = vol.Schema(
            {
                vol.Required(CONF_BRAIN_URL, default=DEFAULT_BRAIN_URL): str,
                vol.Required(CONF_API_TOKEN): str,
                vol.Optional(CONF_KOKORO_URL, default=""): str,
                vol.Optional(CONF_KOKORO_VOICE, default=DEFAULT_KOKORO_VOICE): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def _validate_brain(self, brain_url: str, api_token: str) -> str | None:
        """Round-trip a ping against /api/conversation/process.

        Returns ``None`` on success; on failure returns one of the
        translation keys defined in ``translations/en.json`` so the form
        can render a useful error to the user.
        """
        session = async_get_clientsession(self.hass)
        url = f"{brain_url}{CONVERSATION_ENDPOINT}"
        headers = {"Authorization": f"Bearer {api_token}"}
        payload = {
            "text": "ping",
            "conversation_id": "bramwell-companion-config-flow",
            "language": "en",
        }
        try:
            async with async_timeout.timeout(CONVERSATION_TIMEOUT_SECONDS):
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 401 or resp.status == 403:
                        return "invalid_auth"
                    if resp.status >= 400:
                        _LOGGER.warning(
                            "Bramwell brain returned %s during config validation",
                            resp.status,
                        )
                        return "cannot_connect"
                    body = await resp.json()
                    # Lightweight contract check — must look like an HA
                    # IntentResponse envelope. Anything else is "wrong
                    # endpoint" not "wrong token."
                    if "response" not in body or "conversation_id" not in body:
                        return "unexpected_response"
        except aiohttp.ClientError as err:
            _LOGGER.debug("Bramwell brain unreachable: %s", err)
            return "cannot_connect"
        except TimeoutError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Bramwell brain")
            return "unknown"
        return None

    async def _validate_kokoro(self, kokoro_url: str) -> str | None:
        """Probe Kokoro's /health to make sure the user typed a real URL.

        Lightweight — Kokoro responds to GET /health in <50ms when up. We
        don't try a synthesis round-trip here (that's the steady-state
        path's job); just confirm the host responds.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(KOKORO_TIMEOUT_SECONDS):
                async with session.get(f"{kokoro_url}/health") as resp:
                    if resp.status >= 400:
                        _LOGGER.warning(
                            "Kokoro health returned %s during config validation",
                            resp.status,
                        )
                        return "kokoro_unreachable"
        except aiohttp.ClientError as err:
            _LOGGER.debug("Kokoro unreachable: %s", err)
            return "kokoro_unreachable"
        except TimeoutError:
            return "kokoro_unreachable"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Kokoro")
            return "unknown"
        return None
