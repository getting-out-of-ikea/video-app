"""LiveKit Agents adapters for the offline helpers in :mod:`services.stt_tts`.

`stt_tts` was written for single-process, interactive use: it plays the audio
through the machine's speakers and reloads the Whisper model on demand. Inside
a LiveKit worker neither is acceptable, so this module adds two thin plugins:

* :class:`PiperTTS` renders each reply to a PCM buffer and publishes it into
  the room, instead of playing it locally;
* :class:`WhisperSTT` transcribes one VAD-segmented utterance at a time and
  reuses the cached Whisper model.

Both are **non-streaming**. LiveKit's voice pipeline is happy with that: the
capabilities declared below make it fall back to batch processing, which is
what Piper and faster-whisper support natively. You pay a little latency (the
whole utterance has to be captured before it is transcribed, and the whole
reply before it is spoken) and gain a much simpler adapter.

Note: these adapters depend on the local `services.stt_tts` module being
importable. It currently lives at ``bot-agent/src/services/stt_tts.py``, i.e.
outside the ``bot_agent`` package, so it is *not* installed by ``uv_build``.
See the project notes if ``from services import stt_tts`` fails at startup.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from livekit import rtc
from livekit.agents import (
    APIConnectOptions,
    DEFAULT_API_CONNECT_OPTIONS,
    stt,
    tts,
    utils,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from services import stt_tts

logger = logging.getLogger("bot-agent.plugins")

# faster-whisper only accepts mono float32 audio at 16 kHz.
STT_SAMPLE_RATE = 16000

# Used only when the Piper voice doesn't expose its own sample rate. Every
# "medium" voice (the defaults in stt_tts.DEFAULT_VOICES) is 22050 Hz.
FALLBACK_TTS_SAMPLE_RATE = 22050


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resampling.

    A safety net: LiveKit normally hands the STT batch audio that is already
    at 16 kHz, in which case this is a no-op. Linear interpolation is not
    audiophile-grade, but for a speech recognizer it is more than enough and
    it avoids dragging in scipy/librosa.
    """
    if src_rate == dst_rate or audio.size == 0:
        return audio
    duration = audio.size / src_rate
    dst_length = max(1, int(round(duration * dst_rate)))
    dst_times = np.linspace(0.0, duration, dst_length, endpoint=False)
    src_times = np.arange(audio.size) / src_rate
    return np.interp(dst_times, src_times, audio).astype(np.float32)


def _buffer_to_mono_16k(buffer: utils.AudioBuffer) -> np.ndarray:
    """Flatten an AudioBuffer into the mono float32 / 16 kHz array Whisper wants."""
    frames = list(buffer)
    if not frames:
        return np.zeros(0, dtype=np.float32)

    channels = frames[0].num_channels
    pcm = np.concatenate([np.frombuffer(frame.data, dtype=np.int16) for frame in frames])
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)

    audio = pcm.astype(np.float32) / 32768.0
    return _resample(audio, frames[0].sample_rate, STT_SAMPLE_RATE)


class WhisperSTT(stt.STT):
    """Local faster-whisper transcription exposed as a LiveKit STT plugin.

    The model is not loaded here: `stt_tts.get_whisper_model` caches it, so
    the first utterance pays the loading cost and every later one is fast.
    """

    def __init__(
        self,
        *,
        language: str,
        model_size: str = "base",
        device: str | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._language = language
        self._model_size = model_size
        self._device = device

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        # The pipeline may pass a language along; fall back to the configured
        # one (our Whisper models are not asked to auto-detect).
        lang = language if isinstance(language, str) else self._language

        audio = _buffer_to_mono_16k(buffer)
        if audio.size == 0:
            text = ""
        else:
            # Blocking, CPU/GPU-bound work: keep it off the event loop.
            text = await asyncio.to_thread(
                stt_tts.speech_to_text, audio, lang, self._model_size, self._device
            )

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language=lang, text=text, confidence=1.0)],
        )


def _sample_rate_of(voice: object) -> int:
    """Best-effort read of a Piper voice's sample rate."""
    rate = getattr(getattr(voice, "config", None), "sample_rate", None)
    if isinstance(rate, int) and rate > 0:
        return rate
    logger.warning("cannot read the Piper sample rate, assuming %d Hz", FALLBACK_TTS_SAMPLE_RATE)
    return FALLBACK_TTS_SAMPLE_RATE


class PiperTTS(tts.TTS):
    """Local Piper synthesis exposed as a LiveKit TTS plugin.

    The voice is loaded (and, on first run, downloaded) in the constructor so
    the model is warm by the time the first reply is generated and so the
    real sample rate can be advertised to the framework.
    """

    def __init__(
        self,
        *,
        language: str,
        voice: str | None = None,
        speed: float = 0.7,
    ) -> None:
        self._language = language
        self._voice = voice
        self._speed = speed

        piper_voice = stt_tts.get_voice(language, voice)
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=_sample_rate_of(piper_voice),
            num_channels=1,
        )

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _PiperChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
            language=self._language,
            voice=self._voice,
            speed=self._speed,
        )


class _PiperChunkedStream(tts.ChunkedStream):
    """Renders one phrase with Piper and emits it as a single audio frame."""

    def __init__(
        self,
        *,
        tts: PiperTTS,
        input_text: str,
        conn_options: APIConnectOptions,
        language: str,
        voice: str | None,
        speed: float,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._language = language
        self._voice = voice
        self._speed = speed

    async def _run(self) -> None:
        audio, sample_rate = await asyncio.to_thread(
            stt_tts.synthesize_pcm,
            self._input_text,
            self._language,
            self._voice,
            self._speed,
        )
        if audio.size == 0:
            return

        # The pipeline publishes mono audio; collapse the rare multi-channel
        # voice so the frame layout stays predictable.
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype(np.int16)

        frame = rtc.AudioFrame(
            data=audio.tobytes(),
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=audio.shape[0],
        )
        self._event_ch.send_nowait(
            tts.SynthesizedAudio(request_id=self.request_id, frame=frame)
        )
