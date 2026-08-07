# Bramwell Companion

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bengulliford&repository=BramwellCompanion&category=integration)
[![Validate](https://github.com/bengulliford/BramwellCompanion/actions/workflows/validate.yml/badge.svg)](https://github.com/bengulliford/BramwellCompanion/actions/workflows/validate.yml)

Home Assistant integration for [Bramwell](https://bramwell.app), the
self-hosted smart-home butler. It connects Home Assistant's Assist
surfaces to a running [Bramwell add-on](https://github.com/bengulliford/Bramwell):

- **Conversation agent** — registers **Alfred** (the Bramwell brain) as
  a `conversation` agent, so any Assist surface (Voice PE pucks, the
  mobile app's voice button, the dashboard Assist icon, automations
  calling `conversation.process`) can talk to it.
- **Text-to-speech** — an optional TTS entity backed by a
  Kokoro-compatible endpoint, speaking in Alfred's voice (`bm_george`
  by default).
- **Wake word** — a `wake_word` platform for Home-Assistant-side
  detection on streaming satellites. See the honest status note below.
- **Sensors** — Alfred's health plus the last command and response, for
  building automations on top of conversations.

Home Assistant owns the audio transport (microphone capture,
speech-to-text, speaker output); this integration exchanges text with
the Bramwell brain over your local network.

## Requirements

- Home Assistant **2024.12.0** or newer.
- A running Bramwell brain — normally the
  [Bramwell add-on](https://github.com/bengulliford/Bramwell) on the
  same Home Assistant machine, but any host reachable from Home
  Assistant works.
- [HACS](https://hacs.xyz) for the recommended install path.

## Installation

### Via HACS (custom repository)

Click the badge above, or manually:

1. In Home Assistant, open **HACS**.
2. Open the three-dot menu (top right) → **Custom repositories**.
3. Add `https://github.com/bengulliford/BramwellCompanion` with
   category **Integration**.
4. Search for **Bramwell Companion** in HACS and click **Download**.
5. Restart Home Assistant.

### Manual

Copy `custom_components/bramwell/` into the `custom_components/` folder
of your Home Assistant configuration directory, then restart Home
Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration** and search
   for **Bramwell**.
2. Enter the brain URL. The default,
   `http://homeassistant.local:8080`, is correct when Bramwell runs as
   a Home Assistant add-on.
3. Optionally enter a Kokoro TTS URL and voice. Leave the URL blank to
   skip Bramwell TTS and keep whatever TTS your pipelines already use
   (Piper, Nabu Casa cloud, the community Wyoming-Kokoro add-on, …).

### Use Alfred in an Assist pipeline

1. Open **Settings → Voice assistants**.
2. Pick the pipeline you want Alfred to power (or create one).
3. Under **Conversation agent**, choose **Alfred**.
4. Save, then try it from the Assist icon in the sidebar.

## Wake word — current status

The integration ships a `wake_word` platform for satellites that stream
raw audio into the Assist pipeline and rely on Home Assistant to spot
the phrase. The custom **"Alfred"** microWakeWord model is still in
training and **not yet bundled**: until it ships in a release, the
platform registers no wake-word entity and logs exactly why. Nothing is
faked — if a wake-word entity exists, it can genuinely detect.

Two further honest caveats:

- **Voice PE pucks and other ESPHome `micro_wake_word` satellites run
  wake detection on-device.** They get models through their ESPHome
  configuration, not from this integration — a model bundled here does
  nothing for Voice PE by itself.
- Home-Assistant-side detection needs the `pymicro-wakeword` runtime,
  which only publishes glibc wheels. It is therefore not a hard
  requirement of this integration; on HA OS / Container (musl) the
  platform stays dormant rather than breaking the rest of the
  integration.

## Sensors

| Sensor | Value |
|---|---|
| `sensor.bramwell_alfred_status` | `online` / `offline` / `degraded` |
| `sensor.bramwell_last_command` | text of the most recent user utterance |
| `sensor.bramwell_last_response` | text of the most recent Alfred reply |

Useful for triggering automations off Alfred's state — for example,
running the bedtime scene when Alfred says good night.

## Troubleshooting

**Can't reach the brain.** The default URL
`http://homeassistant.local:8080` assumes the Bramwell add-on runs on
the Home Assistant host. For other deployments, point the config flow
at wherever the brain's HTTP port is reachable from Home Assistant.

**Alfred doesn't appear in the conversation-agent dropdown.** Restart
Home Assistant after installing; the conversation entity registers at
startup.

**Assist wakes but Alfred doesn't reply.** Check
`sensor.bramwell_alfred_status` — if it shows `degraded` or `offline`,
the brain is unreachable. Each conversation turn has a 30-second
timeout, matching Home Assistant's convention for LLM-backed agents.

## Related projects

- [Bramwell add-on](https://github.com/bengulliford/Bramwell) — the
  brain this integration talks to.
- [bramwell.app](https://bramwell.app) — project site.

This repository is a read-only mirror of the `companion/` directory in
the Bramwell source tree; issues are welcome here, pull requests land
upstream first.

## License

MIT — see [LICENSE](LICENSE).
