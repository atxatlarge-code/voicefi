"""Speech-to-Text provider factory and exports."""

import threading
from typing import Dict, Tuple, Any

from voicefi.config import VoiceFiConfig
from voicefi.stt.base import BaseSTT, BaseStreamingSTT
from voicefi.stt.whisper_local import WhisperLocalSTT, clear_whisper_model_cache
from voicefi.stt.streaming_local import StreamingLocalSTT
from voicefi.stt.groq_cloud import GroqSTT
from voicefi.stt.apple_speech import AppleSpeechSTT

try:
    from voicefi.stt.mlx_whisper import MLXWhisperSTT
except ImportError:
    MLXWhisperSTT = None


from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer

# Thread-safe global engine cache to prevent repeated wrapper allocations
_ENGINE_CACHE: Dict[Tuple[str, str, str, str, bool], BaseSTT] = {}
_ENGINE_LOCK = threading.Lock()


def clear_stt_engine_cache():
    """Clear all cached STT engines and their underlying model caches."""
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()
    clear_whisper_model_cache()


def get_stt_engine(config: VoiceFiConfig) -> BaseSTT:
    """Instantiate or return cached STT engine."""
    from voicefi.license import FeatureGate

    provider = config.stt.provider.lower()
    if provider == "auto":
        import platform
        import importlib.util

        if (
            platform.system() == "Darwin"
            and platform.machine() == "arm64"
            and importlib.util.find_spec("mlx_whisper") is not None
        ):
            provider = "mlx_whisper"
        else:
            provider = "whisper_local"

    model_size = getattr(config.stt, "model_size", "base.en")
    language = getattr(config.stt, "language", "en")
    api_key = getattr(config.stt, "groq_api_key", "")
    streaming = bool(getattr(config.stt, "streaming", False))

    cache_key = (provider, model_size, language, api_key, streaming)
    if cache_key in _ENGINE_CACHE:
        return _ENGINE_CACHE[cache_key]

    with _ENGINE_LOCK:
        if cache_key in _ENGINE_CACHE:
            return _ENGINE_CACHE[cache_key]

        if provider == "groq" and api_key:
            engine = GroqSTT(
                api_key=api_key,
                model=config.stt.groq_model,
                language=language,
            )
        elif provider == "apple_speech":
            engine = AppleSpeechSTT(language=language)
        elif provider in ("mlx_whisper", "mlx", "metal"):
            import importlib.util

            if importlib.util.find_spec("mlx_whisper") is not None:
                from voicefi.stt.mlx_whisper import MLXWhisperSTT

                model_name = getattr(config.stt, "mlx_model", None) or getattr(
                    config.stt, "model_size", "mlx-community/whisper-large-v3-turbo"
                )
                if not model_name.startswith("mlx-community/") and "/" not in model_name:
                    if "turbo" in model_name:
                        model_name = "mlx-community/whisper-large-v3-turbo"
                    elif "distil" in model_name:
                        model_name = "mlx-community/distil-whisper-large-v3"
                engine = MLXWhisperSTT(model_name=model_name, language=language)
            else:
                engine = WhisperLocalSTT(model_size=model_size, language=language)
        else:
            # Local faster-whisper (streaming gated behind Pro/Org tier)
            if streaming and FeatureGate.can_use_feature("streaming_stt", config):
                engine = StreamingLocalSTT(
                    model_size=model_size,
                    language=language,
                )
            else:
                # Default community (.org) tier: Clean, instant on-device Faster-Whisper batch
                engine = WhisperLocalSTT(
                    model_size=model_size,
                    language=language,
                )
        _ENGINE_CACHE[cache_key] = engine
        return engine


__all__ = [
    "BaseSTT",
    "BaseStreamingSTT",
    "WhisperLocalSTT",
    "MLXWhisperSTT",
    "StreamingLocalSTT",
    "GroqSTT",
    "AppleSpeechSTT",
    "ProjectContextExtractor",
    "PhoneticNormalizer",
    "get_stt_engine",
    "clear_stt_engine_cache",
]
