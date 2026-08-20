"""Speech-to-Text provider factory and exports."""

from talk2me.config import Talk2MeConfig
from talk2me.stt.base import BaseSTT
from talk2me.stt.whisper_local import WhisperLocalSTT
from talk2me.stt.groq_cloud import GroqSTT
from talk2me.stt.apple_speech import AppleSpeechSTT


def get_stt_engine(config: Talk2MeConfig) -> BaseSTT:
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
        # Default to local faster-whisper
        return WhisperLocalSTT(
            model_size=config.stt.model_size,
            language=config.stt.language,
        )


__all__ = ["BaseSTT", "WhisperLocalSTT", "GroqSTT", "AppleSpeechSTT", "get_stt_engine"]
