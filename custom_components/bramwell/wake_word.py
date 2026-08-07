"""Bramwell wake-word platform — HA-side "Alfred" detection for streaming satellites.

Architecture honesty: wake detection runs in one of two places, and this
platform serves exactly one of them.

- **On-device (Voice PE / ESPHome ``micro_wake_word``)**: the puck runs the
  model in firmware and only streams audio AFTER it hears the phrase. Models
  reach the puck via its ESPHome configuration / wake-word picker, NOT via
  this platform — a model bundled here does nothing for Voice PE until it is
  flashed or served to the device.
- **HA-side (this platform)**: satellites without on-device wake stream raw
  audio through the Assist pipeline, and Home Assistant runs detection by
  calling this entity. That is what ``BramwellWakeWord`` provides.

Model selection follows the locked descope design in ``wake_words/README.md``:
prefer the custom ``alfred.tflite`` (phrase: "Alfred"), fall back to
``alfred_placeholder.tflite``, and degrade gracefully — clear log line, no
entity, never a crashed config-entry setup — when neither file exists or the
selected file cannot actually run.

Inference uses ``pymicro-wakeword`` (the microWakeWord runtime), deliberately
NOT declared in ``manifest.json`` requirements: its wheels are glibc-only
(manylinux/macos/win — no musllinux), so a hard requirement would fail pip on
HA OS / Container (Alpine musl) and take the whole integration down with it,
conversation agent included. The import is optional at runtime instead; when
it is missing we log exactly what that means and register nothing. An entity
is only ever added after a successful validation load — if it exists, it can
genuinely detect. We never fake detection.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.components.wake_word import (
    DetectionResult,
    WakeWord,
    WakeWordDetectionEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    WAKE_WORD_MODEL_FILENAME,
    WAKE_WORD_PHRASE,
    WAKE_WORD_PLACEHOLDER_FILENAME,
    WAKE_WORD_PLACEHOLDER_PHRASE,
)

_LOGGER = logging.getLogger(__name__)

_WAKE_WORDS_DIR = Path(__file__).parent / "wake_words"

# Conventional microWakeWord v2 tuning, used only when a model ships without
# its JSON manifest sidecar. The published v2 manifests (okay_nabu,
# hey_jarvis, …) use exactly these values; a model's own manifest always wins.
_DEFAULT_PROBABILITY_CUTOFF = 0.97
_DEFAULT_SLIDING_WINDOW_SIZE = 5


@dataclass(frozen=True)
class _PreparedRuntime:
    """A selected wake model that passed its validation load.

    ``load()`` returns a FRESH ``(MicroWakeWord, MicroWakeWordFeatures)``
    pair — both hold rolling stream state (feature strides, probability
    window), so every detection stream needs its own instances.
    """

    model_path: Path
    wake_word_id: str
    phrase: str
    is_placeholder: bool
    load: Callable[[], tuple[Any, Any]]
    synthesized_manifest: Path | None


def _import_runtime() -> tuple[Any, Any]:
    """Import the optional microWakeWord runtime.

    Isolated seam so tests can patch it (CI has no pymicro-wakeword) and so
    the ImportError branch in ``_prepare`` stays honest about what failed.
    """
    from pymicro_wakeword import (  # pylint: disable=import-outside-toplevel
        MicroWakeWord,
        MicroWakeWordFeatures,
    )

    return MicroWakeWord, MicroWakeWordFeatures


def _select_model(wake_words_dir: Path) -> tuple[Path, str, bool] | None:
    """Pick the bundled model per the locked order.

    Returns ``(model_path, fallback_phrase, is_placeholder)`` for the first
    filename that exists — ``alfred.tflite`` first, then the descope
    placeholder — or ``None`` when neither is bundled.
    """
    for filename, fallback_phrase, is_placeholder in (
        (WAKE_WORD_MODEL_FILENAME, WAKE_WORD_PHRASE, False),
        (WAKE_WORD_PLACEHOLDER_FILENAME, WAKE_WORD_PLACEHOLDER_PHRASE, True),
    ):
        model_path = wake_words_dir / filename
        if model_path.is_file():
            return model_path, fallback_phrase, is_placeholder
    return None


def _read_manifest(model_path: Path) -> dict[str, Any] | None:
    """Parse the model's ``<stem>.json`` microWakeWord manifest sidecar.

    Returns ``None`` when the sidecar is absent or unparseable (the caller
    falls back to conventional tuning) — a broken sidecar must degrade, not
    crash setup.
    """
    manifest_path = model_path.with_suffix(".json")
    try:
        raw: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        _LOGGER.warning(
            "Wake-word manifest %s exists but could not be parsed (%s) — "
            "falling back to conventional microWakeWord tuning",
            manifest_path,
            err,
        )
        return None
    if not isinstance(raw, dict):
        _LOGGER.warning(
            "Wake-word manifest %s is not a JSON object — ignoring it", manifest_path
        )
        return None
    return raw


def _manifest_phrase(manifest: dict[str, Any] | None, fallback: str) -> str:
    """Advertised phrase: the manifest's trained ``wake_word``, else fallback.

    Manifests write lowercase phrases ("okay nabu" style) — title-case for
    the pipeline picker. The manifest wins over our constants because it
    records what the model actually detects; advertising anything else would
    be fake.
    """
    raw = (manifest or {}).get("wake_word")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().title()
    return fallback


def _synthesize_manifest(
    model_path: Path, phrase: str, manifest: dict[str, Any] | None
) -> Path:
    """Write a temp microWakeWord JSON manifest pointing at ``model_path``.

    ``MicroWakeWord.from_config`` is the only public loader that auto-locates
    the wheel's bundled ``tensorflowlite_c`` library, and it only accepts a
    JSON path — so a bare ``.tflite`` (or one whose sidecar's ``"model"`` key
    references a different filename, the realistic trainer-output rename
    trap) gets a synthesized manifest. Any parseable tuning from the real
    sidecar is merged in so a trained cutoff/window survives; conventional
    defaults fill the gaps. The ``"model"`` key is written absolute, which
    ``from_config``'s ``config_dir / model`` join resolves to itself.

    The temp file must outlive setup (``load()`` re-reads it per stream);
    the entity unlinks it on removal, and on HA OS ``/tmp`` is tmpfs anyway.
    """
    micro_raw = (manifest or {}).get("micro")
    micro: dict[str, Any] = micro_raw if isinstance(micro_raw, dict) else {}
    cutoff = micro.get("probability_cutoff")
    window = micro.get("sliding_window_size")
    synthesized = {
        "type": "micro",
        "wake_word": phrase.lower(),
        "model": str(model_path.resolve()),
        "version": 2,
        "micro": {
            "probability_cutoff": (
                cutoff if isinstance(cutoff, (int, float)) else _DEFAULT_PROBABILITY_CUTOFF
            ),
            "sliding_window_size": (
                window if isinstance(window, int) else _DEFAULT_SLIDING_WINDOW_SIZE
            ),
            "trained_languages": ["en"],
        },
    }
    fd, raw_path = tempfile.mkstemp(prefix="bramwell_wake_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(synthesized, fh)
    return Path(raw_path)


def _prepare(wake_words_dir: Path) -> _PreparedRuntime | None:
    """Select the bundled model and prove it actually runs.

    Sync and executor-only (file stats, JSON I/O, numpy/ctypes imports, a
    tflite interpreter construction). Every degraded outcome returns ``None``
    after logging its exact reason — a wake-word problem must never take the
    config-entry setup down with it (conversation/TTS/sensors keep working),
    and an entity that cannot detect must never be registered (it would sit
    selectable-but-inert in the pipeline picker).
    """
    selected = _select_model(wake_words_dir)
    if selected is None:
        _LOGGER.info(
            "No wake-word model is bundled yet (looked for %s then %s in %s); "
            "the HA-side wake-word entity was not registered. On-device wake "
            "(Voice PE / ESPHome micro_wake_word) does not use this platform "
            "and is unaffected.",
            WAKE_WORD_MODEL_FILENAME,
            WAKE_WORD_PLACEHOLDER_FILENAME,
            wake_words_dir,
        )
        return None
    model_path, fallback_phrase, is_placeholder = selected

    try:
        micro_wake_word_cls, features_cls = _import_runtime()
    except ImportError:
        _LOGGER.warning(
            "Wake-word model %s is bundled, but the optional "
            "'pymicro-wakeword' runtime is not installed, so the HA-side "
            "wake-word entity was not registered. It is not a manifest "
            "requirement because its wheels do not cover HA OS/Container "
            "(Alpine musl) and a failed pip install there would break the "
            "whole integration. On glibc installs (HA Core venv/Supervised): "
            "pip install pymicro-wakeword, then reload the integration. "
            "Voice PE on-device wake is unaffected either way.",
            model_path.name,
        )
        return None

    manifest = _read_manifest(model_path)
    phrase = _manifest_phrase(manifest, fallback_phrase)

    # Use the real sidecar directly only when its "model" key points at the
    # file we selected; otherwise synthesize (merging its tuning) so the
    # locked "the filename that exists is what runs" promise holds even when
    # trainer output was renamed without editing the sidecar.
    manifest_path = model_path.with_suffix(".json")
    synthesized: Path | None = None
    if manifest is not None:
        sidecar_model = manifest.get("model")
        points_at_selected = isinstance(sidecar_model, str) and (
            (manifest_path.parent / sidecar_model).resolve() == model_path.resolve()
        )
        if not points_at_selected:
            _LOGGER.info(
                "Wake-word manifest %s does not reference %s — synthesizing "
                "a corrected manifest (its tuning values are kept). Align "
                "the sidecar's \"model\" key to silence this.",
                manifest_path.name,
                model_path.name,
            )
            synthesized = _synthesize_manifest(model_path, phrase, manifest)
    elif manifest_path.is_file():
        # _read_manifest already warned about WHY this sidecar is unusable;
        # claiming "no manifest sidecar" here would contradict that warning.
        _LOGGER.info(
            "Wake-word manifest %s exists but could not be used — "
            "synthesizing a manifest with conventional microWakeWord tuning "
            "(cutoff=%s, window=%s). Fix the sidecar to restore its trained "
            "values.",
            manifest_path.name,
            _DEFAULT_PROBABILITY_CUTOFF,
            _DEFAULT_SLIDING_WINDOW_SIZE,
        )
        synthesized = _synthesize_manifest(model_path, phrase, None)
    else:
        _LOGGER.info(
            "Wake-word model %s has no %s manifest sidecar — using "
            "conventional microWakeWord tuning (cutoff=%s, window=%s). "
            "Bundling the trainer's manifest next to the model is preferred.",
            model_path.name,
            manifest_path.name,
            _DEFAULT_PROBABILITY_CUTOFF,
            _DEFAULT_SLIDING_WINDOW_SIZE,
        )
        synthesized = _synthesize_manifest(model_path, phrase, None)

    config_path = synthesized if synthesized is not None else manifest_path

    def load() -> tuple[Any, Any]:
        return micro_wake_word_cls.from_config(config_path), features_cls()

    # Validation load: proves file + runtime + model architecture together
    # BEFORE anything is registered. pymicro-wakeword raises ValueError for
    # non-microWakeWord tflites (e.g. the float32 openWakeWord placeholder:
    # "Unsupported quantized tensor type"), so the descope file is rejected
    # deterministically here rather than failing every pipeline run.
    try:
        detector, _ = load()
    except Exception as err:  # noqa: BLE001 — any load failure means "don't register"
        _LOGGER.warning(
            "Wake-word model %s could not be loaded by the microWakeWord "
            "runtime (%s); the HA-side wake-word entity was not registered. "
            "Note: an openWakeWord-format placeholder is a different model "
            "architecture and can never run on this platform — pair it with "
            "the openWakeWord add-on instead, or bundle a microWakeWord "
            "model (.tflite + .json manifest).",
            model_path.name,
            err,
        )
        if synthesized is not None:
            with contextlib.suppress(OSError):
                synthesized.unlink()
        return None
    _close_quietly(detector)

    _LOGGER.info(
        "Wake-word model %s loaded (phrase: %r%s); registering the HA-side "
        "wake-word entity for streaming satellites. Voice PE pucks run wake "
        "detection on-device and need the model flashed there separately.",
        model_path.name,
        phrase,
        " — descope placeholder" if is_placeholder else "",
    )
    return _PreparedRuntime(
        model_path=model_path,
        wake_word_id=model_path.stem,
        phrase=phrase,
        is_placeholder=is_placeholder,
        load=load,
        synthesized_manifest=synthesized,
    )


def _close_quietly(detector: Any) -> None:
    """Release the tflite interpreter promptly instead of waiting on GC."""
    close = getattr(detector, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _detect_in_chunk(detector: Any, featurizer: Any, chunk: bytes) -> bool:
    """Sync per-chunk step: featurize, then score each feature window.

    ``MicroWakeWordFeatures`` buffers internally until it has full 10 ms
    frames, so arbitrary chunk sizes are fine; ``process_streaming`` returns
    ``Optional[bool]`` and both ``None`` and ``False`` mean "keep listening".
    """
    for features in featurizer.process_streaming(chunk):
        if detector.process_streaming(features):
            return True
    return False


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the Alfred wake-word entity when a runnable model is bundled.

    Forwarded unconditionally from ``__init__.py``; every degraded outcome
    (no model file, runtime not installed, model won't load) logs its exact
    reason inside ``_prepare`` and registers nothing. The probe runs in the
    import executor — it imports numpy/ctypes-backed modules and touches
    disk, neither of which belongs on the event loop.
    """
    prepared = await hass.async_add_import_executor_job(_prepare, _WAKE_WORDS_DIR)
    if prepared is None:
        return
    async_add_entities([BramwellWakeWord(entry, prepared)])


class BramwellWakeWord(WakeWordDetectionEntity):
    """HA wake_word entity running microWakeWord inference for Alfred.

    Only ever constructed after ``_prepare`` proved the bundled model loads
    under the runtime — if this entity exists, it can genuinely detect.
    """

    _attr_has_entity_name = True
    _attr_name = "Alfred wake word"

    def __init__(self, entry: ConfigEntry, prepared: _PreparedRuntime) -> None:
        self._prepared = prepared
        # Same unique-id scheme as the TTS/sensor entities: key off the
        # brain-URL-derived entry unique_id so delete + re-add reclaims the
        # entity instead of leaving a stale `unavailable` ghost behind.
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_alfred_wake_word"

    async def get_supported_wake_words(self) -> list[WakeWord]:
        """Advertise the single bundled wake word to the pipeline picker."""
        prepared = self._prepared
        return [
            WakeWord(
                id=prepared.wake_word_id,
                name=prepared.phrase,
                phrase=prepared.phrase,
            )
        ]

    async def _async_process_audio_stream(
        self, stream: AsyncIterable[tuple[bytes, int]], wake_word_id: str | None
    ) -> DetectionResult | None:
        """Run streaming detection over 16 kHz 16-bit mono PCM audio.

        A fresh detector/featurizer pair is loaded per stream (the model is
        30–40 KB; interpreter setup is milliseconds) so concurrent pipeline
        runs from different satellites never share rolling state. All
        inference happens in the executor; the loop only shuttles chunks.
        """
        prepared = self._prepared
        if wake_word_id is not None and wake_word_id != prepared.wake_word_id:
            # HA hands back ids from get_supported_wake_words, so this is
            # defensive only — the single bundled model is all we can run.
            _LOGGER.debug(
                "Requested wake word %s; running the only bundled model %s",
                wake_word_id,
                prepared.wake_word_id,
            )

        try:
            detector, featurizer = await self.hass.async_add_executor_job(
                prepared.load
            )
        except Exception:  # noqa: BLE001 — must not crash the pipeline run
            _LOGGER.exception(
                "Wake-word model %s failed to load for a new stream",
                prepared.model_path.name,
            )
            return None

        try:
            async for chunk, timestamp in stream:
                detected = await self.hass.async_add_executor_job(
                    _detect_in_chunk, detector, featurizer, chunk
                )
                if detected:
                    return DetectionResult(
                        wake_word_id=prepared.wake_word_id,
                        wake_word_phrase=prepared.phrase,
                        timestamp=timestamp,
                        # Detection is synchronous with the stream — nothing
                        # queues up while waiting on a remote service (unlike
                        # the Wyoming provider), so there is no audio to
                        # hand back to the pipeline.
                        queued_audio=None,
                    )
        except Exception:  # noqa: BLE001 — CancelledError still propagates
            _LOGGER.exception(
                "Wake-word detection failed mid-stream; abandoning this run"
            )
            return None
        finally:
            _close_quietly(detector)
        return None

    async def async_will_remove_from_hass(self) -> None:
        """Best-effort cleanup of a synthesized manifest temp file."""
        synthesized = self._prepared.synthesized_manifest
        if synthesized is not None:
            await self.hass.async_add_executor_job(_unlink_quietly, synthesized)
