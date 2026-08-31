"""Speech-to-Text provider factory and exports."""

from voicefi.config import VoiceFiConfig
from voicefi.stt.base import BaseSTT, BaseStreamingSTT
from voicefi.stt.whisper_local import WhisperLocalSTT
from voicefi.stt.streaming_local import StreamingLocalSTT
from voicefi.stt.groq_cloud import GroqSTT
from voicefi.stt.apple_speech import AppleSpeechSTT


from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


def get_stt_engine(config: VoiceFiConfig) -> BaseSTT:
    """Instantiate the configured STT engine."""
    from voicefi.license import FeatureGate

    provider = config.stt.provider.lower()

    if provider == "groq" and config.stt.groq_api_key:
        return GroqSTT(
            api_key=config.stt.groq_api_key,
            model=config.stt.groq_model,
            language=config.stt.language,
        )
    elif provider == "apple_speech":
        return AppleSpeechSTT(language=config.stt.language)
    else:
        # Local faster-whisper (streaming gated behind Pro/Org tier)
        if getattr(config.stt, "streaming", False) and FeatureGate.can_use_feature(
            "streaming_stt", config
        ):
            return StreamingLocalSTT(
                model_size=config.stt.model_size,
                language=config.stt.language,
            )
        # Default community (.org) tier: Clean, instant on-device Faster-Whisper batch
        return WhisperLocalSTT(
            model_size=config.stt.model_size,
            language=config.stt.language,
        )


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
]
