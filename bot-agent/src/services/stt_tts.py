"""Convert text to speech and speech to text with automatic language detection."""

import json
import site

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlretrieve

if TYPE_CHECKING:
    import numpy as np
    from faster_whisper import WhisperModel
    from piper import PiperVoice


FALLBACK_LANGUAGE = "en"

# Sampling rate assumed only when a voice produces no audio at all.
# Every Piper "medium" voice (i.e. all the defaults below) is 22050 Hz.
FALLBACK_SAMPLE_RATE = 22050

# Hugging Face repository hosting the official Piper voice models.
# We resolve from the "main" branch rather than the "v1.0.0" tag because
# some voices (e.g. Korean) were added after that tag was cut.
VOICES_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Where downloaded voice models are cached.
VOICES_CACHE_DIR = Path.home() / ".cache" / "piper-voices"

# Default Piper voice for each supported language (ISO 639-1 code).
DEFAULT_VOICES = {
    "en": "en_US-lessac-medium",
    "it": "it_IT-paola-medium",
    "es": "es_ES-davefx-medium",
    "fr": "fr_FR-siwis-medium",
    "de": "de_DE-thorsten-medium",
    "pt": "pt_BR-faber-medium",
    "ru": "ru_RU-dmitri-medium",
    "ko": "ko_KR-kss-medium",
    "th": "th_TH-tsync2-medium",
}


def ensure_voice_model(voice_name: str) -> Path:
    """Return the local path of the Piper model for `voice_name`.

    The .onnx model and its .onnx.json config are downloaded from Hugging
    Face on first use and cached in VOICES_CACHE_DIR.
    """
    parts = voice_name.split("-")
    if len(parts) != 3:
        raise ValueError(
            f"invalid Piper voice name: {voice_name!r} "
            "(expected <locale>-<speaker>-<quality>, e.g. it_IT-paola-medium)"
        )
    locale, speaker, quality = parts
    language = locale.split("_")[0]
    base_url = f"{VOICES_BASE_URL}/{language}/{locale}/{speaker}/{quality}/{voice_name}"
    VOICES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_path = VOICES_CACHE_DIR / f"{voice_name}.onnx"
    for suffix in (".onnx", ".onnx.json"):
        path = VOICES_CACHE_DIR / f"{voice_name}{suffix}"
        if path.exists():
            continue
        url = f"{base_url}{suffix}"
        print(f"Downloading {url}...")
        # Download to a temporary file so a failed or interrupted download
        # doesn't leave a corrupt file in the cache.
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            urlretrieve(url, tmp_path)
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"could not download {url}: {e}\n"
                "Check the voice name in the list at "
                "https://huggingface.co/rhasspy/piper-voices"
            ) from e
        tmp_path.rename(path)
    return model_path


@lru_cache(maxsize=8)
def load_voice(model_path: Path) -> "PiperVoice":
    """Load a Piper voice, falling back to espeak phonemization if needed.

    Some voices (e.g. Thai) use a phoneme_type that only exists in piper
    versions newer than the latest release. Since those voices also ship an
    espeak voice in their config, we patch the cached config to use espeak
    instead of failing. Returns the loaded voice.

    Results are cached: the .onnx model is large, and both the CLI and the
    LiveKit worker synthesise many phrases against the same voice.
    """
    from piper import PiperVoice

    try:
        return PiperVoice.load(model_path)
    except ValueError as e:
        if "PhonemeType" not in str(e):
            raise
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    print(
        f"Phoneme type {config['phoneme_type']!r} not supported by this "
        "piper version; falling back to espeak."
    )
    config["phoneme_type"] = "espeak"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return PiperVoice.load(model_path)


def get_voice(language: str, voice: str | None = None) -> "PiperVoice":
    """Return the Piper voice to use for `language`.

    If `voice` (a Piper voice name like "it_IT-paola-medium") is given, it
    overrides the default voice for the language. The model is downloaded on
    first use and cached, so repeated calls are cheap.
    """
    voice_name = voice or DEFAULT_VOICES.get(language, DEFAULT_VOICES[FALLBACK_LANGUAGE])
    return load_voice(ensure_voice_model(voice_name))


def synthesize_pcm(
    text: str,
    language: str,
    voice: str | None = None,
    speed: float = 0.7,
) -> "tuple[np.ndarray, int]":
    """Synthesise `text` and return the raw audio instead of playing it.

    Returns a ``(samples, sample_rate)`` pair: `samples` is a NumPy ``int16``
    array (mono, or shaped ``(n, channels)`` for multi-channel voices) and
    `sample_rate` is the rate the voice was rendered at. Use this when the
    audio has to be forwarded somewhere (a LiveKit room, a socket, a file)
    rather than played through the local speakers. See text_to_speech() for
    playback, and note the two share the same voice selection and caching.
    """
    # Imported lazily: piper and numpy are heavy and only needed here.
    import numpy as np
    from piper.config import SynthesisConfig

    if speed <= 0:
        raise ValueError("speed must be a positive number")

    piper_voice = get_voice(language, voice)
    # Piper controls speed via length_scale: > 1 is slower, < 1 is faster.
    syn_config = SynthesisConfig(length_scale=1.0 / speed)

    chunks = []
    sample_rate = None
    channels = 1
    for chunk in piper_voice.synthesize(text, syn_config=syn_config):
        if sample_rate is None:
            sample_rate = chunk.sample_rate
            channels = chunk.sample_channels
        chunks.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))

    if not chunks or sample_rate is None:
        return np.zeros(0, dtype=np.int16), FALLBACK_SAMPLE_RATE

    audio = np.concatenate(chunks)
    if channels > 1:
        audio = audio.reshape(-1, channels)
    return audio, sample_rate


def text_to_speech(
    text: str,
    language: str,
    voice: str | None = None,
    speed: float = 0.7,
) -> str:
    """Speak `text` through the default audio output and return the language used.

    If `language` (an ISO 639-1 code like "it") is given, it is used as-is;
    otherwise it is auto-detected from the text. If `voice` (a Piper voice
    name like "it_IT-paola-medium") is given, it overrides the default voice
    for the language. `speed` is a playback speed multiplier: 1.0 is normal,
    2.0 is twice as fast, 0.5 is half speed. The whole utterance is played
    back through the speakers; no file is saved.
    """
    # Imported lazily: sounddevice is only needed for local playback.
    import sounddevice as sd

    audio, sample_rate = synthesize_pcm(text, language, voice=voice, speed=speed)
    if audio.size == 0:
        return language
    # Play the whole utterance in a single blocking call. sd.wait() only
    # returns once every sample has been played, so short phrases are not
    # truncated; closing an output stream right after the last write used to
    # drop the trailing audio still sitting in the PortAudio buffer.
    sd.play(audio, samplerate=sample_rate)
    sd.wait()
    return language


# Guards preload_nvidia_libraries() so the CUDA libraries are dlopen()ed at
# most once per process, however many transcriptions run.
_nvidia_libraries_preloaded = False


def preload_nvidia_libraries() -> None:
    """Preload the CUDA libraries bundled with the nvidia pip packages.

    CTranslate2 loads libcublas/libcudnn with dlopen, which doesn't search
    the venv's site-packages where the nvidia-*-cu12 wheels install them.
    (Setting LD_LIBRARY_PATH after process start has no effect, so we can't
    just fix the search path.) Loading them explicitly with RTLD_GLOBAL
    makes them findable. Must be called before the first CTranslate2 model
    is created.
    """
    global _nvidia_libraries_preloaded
    if _nvidia_libraries_preloaded:
        return

    import ctypes

    lib_dirs = []
    for site_packages in site.getsitepackages():
        nvidia_dir = Path(site_packages) / "nvidia"
        if nvidia_dir.is_dir():
            lib_dirs.extend(nvidia_dir.glob("*/lib"))
    for lib_dir in lib_dirs:
        libs = sorted(lib_dir.glob("lib*.so*"))
        # Two passes: the first loads the base libraries, the second those
        # that depend on them (e.g. libcudnn_ops depends on libcudnn).
        for _ in range(2):
            for lib_path in libs:
                try:
                    ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass
    _nvidia_libraries_preloaded = True


def detect_whisper_device() -> tuple[str, str]:
    """Return the (device, compute_type) Whisper should run with.

    Uses the GPU with float16 when a CUDA device is available, otherwise
    falls back to the CPU with int8 quantization.
    """
    import ctranslate2

    if ctranslate2.get_cuda_device_count() > 0:
        return "cuda", "float16"
    return "cpu", "int8"


@lru_cache(maxsize=4)
def _load_whisper_model(
    model_size: str, device: str, compute_type: str
) -> "WhisperModel":
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device=device, compute_type=compute_type)


def get_whisper_model(model_size: str = "base", device: str | None = None) -> "WhisperModel":
    """Return a cached WhisperModel, loading it only on first use.

    Building the model reads hundreds of MB of weights, so it is kept alive
    for the whole process instead of being rebuilt on every transcription.
    `device` is "cpu" or "cuda"; if None, CUDA is used when available.
    """
    if device is None:
        device, compute_type = detect_whisper_device()
    else:
        compute_type = "float16" if device == "cuda" else "int8"
    if device == "cuda":
        preload_nvidia_libraries()
    return _load_whisper_model(model_size, device, compute_type)


def speech_to_text(
    audio: "np.ndarray",
    language: str,
    model_size: str = "base",
    device: str | None = None,
) -> str:
    """Analyzes the language spoken in `audio` and return its transcription.
    `audio` is a mono float32 np.ndarray at 16 kHz, as returned by
    record_from_microphone(). `device` is "cpu" or "cuda"; if None, CUDA is used when available.
    """
    model = get_whisper_model(model_size, device)
    segments, _info = model.transcribe(audio, language=language)
    return " ".join(segment.text.strip() for segment in segments)
