# Wake-word models

This directory holds the microWakeWord `.tflite` model that ships in the
HACS download. Voice PE pucks pick it up from HA's `wake_word` platform
and the user can select "Hey Alfred" in their puck's wake-word picker.

## Status

`alfred.tflite` is **not yet bundled**. It lands here when Sprint 10 N3
completes — see `business/SPRINT-10-VOICE-PE-INTEGRATION.md` §3 N3 for
the training procedure.

## Descope path (locked)

If false-positive rate stays above 2/12h after retraining, the
integration ships with a published openWakeWord placeholder
(e.g. `hey_jarvis`) and a release-notes entry that the custom "Hey
Alfred" model is coming in v1.1. Bundling the placeholder preserves the
integration ship date — Voice PE users can still wake the puck with a
phrase, just not the canonical "Hey Alfred" until the custom model
clears the false-positive bar.

The fallback file lives at `alfred_placeholder.tflite` in this directory
when the descope path is active. The HA wake-word platform registration
in `wake_word.py` (added in N2c, post-N3) selects whichever filename
exists.
