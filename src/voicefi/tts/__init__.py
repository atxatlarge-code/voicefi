"""Text-to-Speech provider factory, voice catalog, and exports."""

from typing import Optional
from voicefi.config import VoiceFiConfig
from voicefi.tts.base import BaseTTS, stop_all_speech, is_agent_speaking, set_agent_speaking
from voicefi.tts.mac_say import MacSayTTS, normalize_mac_rate
from voicefi.tts.edge_tts import EdgeTTS, normalize_edge_rate
from voicefi.tts.elevenlabs import ElevenLabsTTS
from voicefi.tts.catalog import (
    VoicePersona,
    CURATED_PERSONAS,
    get_curated_personas,
    find_persona,
    list_system_mac_voices,
    list_all_available_voices,
)


from voicefi.tts.cloning import (
    ClonedVoiceProfile,
    VoiceCloneManager,
    estimate_pitch_f0,
    analyze_audio_acoustics,
    generate_persona_prompt,
    TRAINING_PROMPTS,
)


def get_tts_engine(
    config: VoiceFiConfig,
    agent_name: Optional[str] = None,
    voice_override: Optional[str] = None,
    provider_override: Optional[str] = None,
    rate_override: Optional[any] = None,
    is_focused: bool = True,
) -> BaseTTS:
    """
    Instantiate the configured TTS engine.
    Supports agent-specific voice resolution, custom cloned voices, dynamic overrides,
    and distinct acoustic persona for unfocused/background agents.
    """
    # 1. Resolve base provider, voice, rate from agent profile or global config
    provider, voice, rate = config.resolve_voice(agent_name, is_focused=is_focused)

    # 2. Apply manual overrides if provided
    if provider_override:
        provider = provider_override
    if voice_override:
        voice = voice_override
        persona = find_persona(voice_override)
        if persona:
            voice = persona.id
            if not provider_override:
                provider = persona.provider
    if rate_override is not None:
        rate = rate_override

    # 3. Resolve cloned voice profiles
    try:
        from voicefi.tts.cloning import VoiceCloneManager
        clone_prof = VoiceCloneManager().get_cloned_voice(voice)
        if clone_prof:
            provider = clone_prof.provider
            if clone_prof.provider == "elevenlabs":
                voice = clone_prof.id
            else:
                voice = clone_prof.calibrated_voice or "en-US-GuyNeural"
            if rate_override is None and clone_prof.calibrated_rate:
                rate = clone_prof.calibrated_rate
    except Exception:
        pass

    provider = provider.lower()

    # If edge_tts provider is selected but voice is the mac_say default "Samantha", switch to Edge default
    if provider == "edge_tts" and voice == "Samantha":
        voice = "en-US-ChristopherNeural"

    if provider == "elevenlabs":
        # Check if voice is a known cloned voice or preset
        resolved_voice_id = voice
        persona = find_persona(voice)
        if persona and persona.provider == "elevenlabs":
            resolved_voice_id = persona.id
        elif not voice or voice == "Samantha":
            resolved_voice_id = config.tts.elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"

        return ElevenLabsTTS(
            api_key=config.tts.elevenlabs_api_key or "",
            voice_id=resolved_voice_id,
        )
    elif provider == "edge_tts":
        return EdgeTTS(voice=voice, rate=rate, streaming=config.tts.streaming)
    else:
        # Default to native macOS say
        return MacSayTTS(voice=voice, rate=rate)


__all__ = [
    "BaseTTS",
    "MacSayTTS",
    "EdgeTTS",
    "ElevenLabsTTS",
    "normalize_edge_rate",
    "normalize_mac_rate",
    "VoicePersona",
    "CURATED_PERSONAS",
    "get_curated_personas",
    "find_persona",
    "list_system_mac_voices",
    "list_all_available_voices",
    "get_tts_engine",
    "stop_all_speech",
    "is_agent_speaking",
    "set_agent_speaking",
    "ClonedVoiceProfile",
    "VoiceCloneManager",
    "estimate_pitch_f0",
    "analyze_audio_acoustics",
    "generate_persona_prompt",
    "TRAINING_PROMPTS",
]


