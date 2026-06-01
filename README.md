# Bramwell Companion

Registers Alfred (the Bramwell brain) as a Home Assistant
`conversation.agent` so any HA Assist surface — Voice PE pucks, the
mobile app's voice button, the dashboard Assist icon — can talk to
Alfred end-to-end. Bundles the "Hey Alfred" microWakeWord model so
Voice PE pucks can wake on the canonical phrase.

This integration is the **free-tier hands-free path** to Alfred. HA owns
audio transport (microphone capture, STT, TTS, speaker output via Nabu
Casa Cloud or whatever STT/TTS the user has wired in); Bramwell only
sees text-in / text-out via the brain's `/api/conversation/process`
endpoint.

For the architecture of why this path stays text-only — and how it
relates to the dashboard mic path that is owned end-to-end by the
Bramwell stack — see
`business/VOICE-ARCHITECTURE-BLUEPRINT.md` §10 in the main repo.

## Install

### From HACS (custom repository — Day 1 path)

1. In HA, open **HACS → Integrations**.
2. Click the three-dot menu in the top right → **Custom repositories**.
3. Add `https://github.com/bengulliford/BramwellCompanion` as an
   **Integration** category repository.
4. Search for **Bramwell Companion** in HACS Integrations and click
   **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration** and search
   for **Bramwell**. Enter your brain URL.

HACS Default repository submission is a Q4 2026 milestone, not a launch
dependency — the custom repo path above is the supported install on
Day 1.

### Configure as the Assist conversation agent

1. **Settings → Voice assistants**.
2. Pick the pipeline you want Alfred to power (or create a new one).
3. Under **Conversation agent**, choose **Alfred** (registered by this
   integration).
4. Save. Try it from the Assist icon in the HA sidebar — type "what's
   the temperature" and Alfred should reply.

### Wake word on a Voice PE puck

1. **Settings → Devices & services → ESPHome → your Voice PE puck →
   Configure**.
2. Under **Wake word**, pick **Hey Alfred**.
3. Save. Say "Hey Alfred, turn off the kitchen lights" — the puck
   wakes, HA captures the utterance, runs STT, hands the transcript to
   Alfred via this integration, gets the reply text back, runs TTS, and
   plays the audio out the puck speaker.

The wake-word file is bundled inside this HACS download. HA's
wake-word selection is per-device — we make "Hey Alfred" available, the
user picks it.

## What's free vs paid

Voice PE integration via `conversation.agent` is included in the **free
tier** for every Bramwell user — there is no license check on the
brain's conversation endpoint. Per-tool capability gates inside the
brain's `ToolExecutor` continue to apply (e.g., browser-agent tools are
gated to paid tiers per `business/06-LICENSE-ARCHITECTURE.md`).

## Sensors

The integration also registers three sensors:

| Sensor | Value |
|---|---|
| `sensor.bramwell_alfred_status` | online / offline / degraded |
| `sensor.bramwell_last_command` | text of the most recent user utterance |
| `sensor.bramwell_last_response` | text of the most recent Alfred reply |

Useful for triggering HA automations off Alfred's state ("when Alfred
says 'good night,' run the bedtime scene").

## Compatibility

- Home Assistant 2024.12.0+
- Bramwell brain `0.x` with the `/api/conversation/process` endpoint
  (Sprint 10 N1 — Brain PR #73 / merged into `dev`)
- Any HA conversation surface (Voice PE puck, mobile app, dashboard
  Assist, automation actions calling `conversation.process`)

## Troubleshooting

**Can't reach the brain.** The config flow's URL field defaults to
`http://homeassistant.local:8080` which works when Bramwell runs as a
HA add-on. For other deployments, point at wherever the brain's HTTP
port is reachable from HA. The brain doesn't need to be on the same
machine — anywhere on the network is fine.

**Alfred doesn't appear in the Assist conversation-agent dropdown.**
Restart HA after installing the integration. The conversation entity
registers on HA startup; it doesn't pick up mid-runtime in older HA
versions.

**Voice PE wakes but Alfred doesn't reply.** Check
`sensor.bramwell_alfred_status` — if `degraded` or `offline`, the
brain is unreachable. The integration has a 5-second hard timeout per
turn, after which the puck plays a graceful "I'm afraid I can't reach
the Bramwell brain at the moment, sir."

## License

MIT — see `LICENSE`.
