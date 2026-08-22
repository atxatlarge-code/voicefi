"""Speech-to-Text provider factory and exports."""

from voicegency.config import VoicegencyConfig
from voicegency.stt.base import BaseSTT, BaseStreamingSTT
from voicegency.stt.whisper_local import WhisperLocalSTT
from voicegency.stt.streaming_local import StreamingLocalSTT
from voicegency.stt.groq_cloud import GroqSTT
from voicegency.stt.apple_speech import AppleSpeechSTT


from voicegency.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


def get_stt_engine(config: VoicegencyConfig) -> BaseSTT:
    """Instantiate the configured STT engine."""
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
        # Local faster-whisper (streaming or batch)
        if getattr(config.stt, "streaming", False):
            return StreamingLocalSTT(
                model_size=config.stt.model_size,
                language=config.stt.language,
            )
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
