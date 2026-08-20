"""Text-to-Speech provider factory and exports."""

from talk2me.config import Talk2MeConfig
from talk2me.tts.base import BaseTTS, stop_all_speech
from talk2me.tts.mac_say import MacSayTTS
from talk2me.tts.edge_tts import EdgeTTS
from talk2me.tts.elevenlabs import ElevenLabsTTS


def get_tts_engine(config: Talk2MeConfig) -> BaseTTS:
    """Instantiate the configured TTS engine."""
    provider = config.tts.provider.lower()
    
    if provider == "edge_tts":
        return EdgeTTS(voice=config.tts.voice, rate=config.tts.rate)
    elif provider == "elevenlabs":
        return ElevenLabsTTS(
            api_key=config.tts.elevenlabs_api_key or "",
            voice_id=config.tts.elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM",
        )
    else:
        # Default to native macOS say
        return MacSayTTS(voice=config.tts.voice, rate=config.tts.rate)


__all__ = ["BaseTTS", "MacSayTTS", "EdgeTTS", "ElevenLabsTTS", "get_tts_engine", "stop_all_speech"]
