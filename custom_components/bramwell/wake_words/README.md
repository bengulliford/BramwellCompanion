# Wake-word models

This directory holds the microWakeWord model that ships in the HACS
download. The wake phrase is **"Alfred"** — exactly that, not
"Hey Alfred" (locked 2026-08-07).

## Who actually runs these files — read before debugging

Wake detection happens in one of two places, and they consume models
differently. **Voice PE pucks (and any ESPHome satellite using
`micro_wake_word`) run detection on-device**: the trained model must be
flashed/served to the puck through its ESPHome configuration, and the
puck never reads this directory or HA's `wake_word` platform — bundling
a model here does nothing for Voice PE by itself. **The HA-side
`wake_word` platform (`../wake_word.py`) serves streaming satellites**:
devices that forward raw audio into the Assist pipeline and rely on
Home Assistant to spot the phrase — that platform is what selects and
runs the files in this directory. The same trained "Alfred" model
serves both, but it has to travel both routes.

## Status

`alfred.tflite` is **not yet trained or bundled**. Ben trains it on the
microWakeWord trainer (see `../../../wake_word_training/` in the source
repo); it lands here once it clears the false-positive bar. Ship the
trainer's JSON manifest sidecar as `alfred.json` next to it — it
carries the trained phrase and tuning (probability cutoff, sliding
window). A bare `.tflite` still works (the platform falls back to
conventional microWakeWord tuning), and if the sidecar's `"model"` key
references the trainer's original filename the platform corrects for
it — but keep the pair consistent.

## Selection (locked)

`wake_word.py` selects whichever model filename exists —
`alfred.tflite` if present, else `alfred_placeholder.tflite`. If
neither file exists (today's state), or the selected file can't
actually be loaded, the platform logs exactly why and registers no
entity; config-entry setup never crashes over a wake-word problem.

## Descope path (locked)

If false-positive rate stays above 2/12h after retraining, the
integration ships with a published placeholder phrase (canonically
`hey_jarvis`) and a release-notes entry that the custom "Alfred" model
is coming in v1.1. The fallback file lives at
`alfred_placeholder.tflite` in this directory —
`wake_word_training/download_placeholder.py` writes it to exactly that
path.

**Honesty note on the placeholder:** `download_placeholder.py` pulls an
*openWakeWord* model, which is a different architecture from
microWakeWord. The HA-side platform can only execute microWakeWord
models, so an openWakeWord-format placeholder fails its load probe
(clear log, no entity) — it is only useful to users running the
openWakeWord add-on, and Voice PE would need the placeholder phrase
flashed on-device regardless. For a placeholder that actually runs on
the HA-side platform, drop a microWakeWord-format model (e.g. the
microWakeWord project's published `hey_jarvis`) at
`alfred_placeholder.tflite` with its manifest as
`alfred_placeholder.json`.

## Runtime (why there is no hard dependency)

HA-side inference uses `pymicro-wakeword`, deliberately NOT declared in
`manifest.json` requirements: its wheels are glibc-only, so a hard
requirement would fail pip install on HA OS/Container (Alpine musl) and
take the whole integration down with it, conversation agent included.
On glibc installs (HA Core venv / Supervised), `pip install
pymicro-wakeword` in HA's environment enables the entity after a
reload; without it the platform logs what's missing and registers
nothing. It never fakes detection.
