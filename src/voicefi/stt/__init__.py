"""Speech-to-Text provider factory and exports."""

import threading
from typing import Dict, Tuple, Any

from voicefi.config import VoiceFiConfig
from voicefi.stt.base import BaseSTT, BaseStreamingSTT
from voicefi.stt.whisper_local import WhisperLocalSTT, clear_whisper_model_cache
from voicefi.stt.streaming_local import StreamingLocalSTT
from voicefi.stt.groq_cloud import GroqSTT
from voicefi.stt.apple_speech import AppleSpeechSTT


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
    "StreamingLocalSTT",
    "GroqSTT",
    "AppleSpeechSTT",
    "ProjectContextExtractor",
    "PhoneticNormalizer",
    "get_stt_engine",
    "clear_stt_engine_cache",
]
