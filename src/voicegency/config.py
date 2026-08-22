"""
Configuration manager for Voicegency.
Handles loading, validating, and saving YAML configuration files with defaults.
"""

from pathlib import Path
from typing import Literal, Optional
import os
import yaml
from pydantic import BaseModel, Field


class TTSConfig(BaseModel):
    provider: Literal["mac_say", "edge_tts", "elevenlabs"] = "mac_say"
    voice: str = "Samantha"
    rate: int = 200
    volume: float = 1.0
    streaming: bool = True
    elevenlabs_api_key: Optional[str] = ""
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"


class STTConfig(BaseModel):
    provider: Literal["whisper_local", "groq", "apple_speech"] = "whisper_local"
    model_size: str = "base.en"
    language: str = "en"
    streaming: bool = False
    groq_api_key: Optional[str] = ""
    groq_model: str = "whisper-large-v3-turbo"


class VADConfig(BaseModel):
    mode: Literal["auto", "ptt", "hybrid"] = "hybrid"
    silence_duration: float = 2.0
    energy_threshold: float = 0.004
    max_record_seconds: int = 45
    sample_rate: int = 16000
    ptt_release_delay_ms: int = 150
    barge_in: bool = True
    barge_in_sensitivity: float = 1.0


class AudioCuesConfig(BaseModel):
    enabled: bool = True
    start_chime: str = "/System/Library/Sounds/Tink.aiff"
    sent_chime: str = "/System/Applications/Mail.app/Contents/Resources/Mail Sent.aiff"
    done_chime: str = "/System/Applications/Mail.app/Contents/Resources/Mail Sent.aiff"
    error_chime: str = "/System/Library/Sounds/Basso.aiff"


class AntigravityConfig(BaseModel):
    auto_listen: bool = True
    read_summary_aloud: bool = True
    max_spoken_words: int = 25
    inject_to_active_window: bool = True
    unfocused_agent_voice: Optional[str] = None
    unfocused_voice_prefix: bool = True
    show_speech_popup: bool = True
    speech_popup_linger_seconds: float = 3.0
    speech_popup_position: Literal["top_center", "top_right", "bottom_right"] = "top_center"


class IntegrationsConfig(BaseModel):
    antigravity: bool = True
    claude_code: bool = True
    cursor: bool = True
    windsurf: bool = True
    system_dictation: bool = True


class GlobalHotkeyConfig(BaseModel):
    enabled: bool = True
    focus_and_talk_hotkey: str = "<ctrl>+r"
    jump_to_agent_hotkey: str = "<ctrl>+j"
    hub_hotkey: str = "<ctrl>+<shift>+j"
    dictate_hotkey: str = "<ctrl>+t"
    show_dictation_hud: bool = True
    preserve_clipboard: bool = True


class AgentVoiceProfile(BaseModel):
    provider: Optional[Literal["mac_say", "edge_tts", "elevenlabs"]] = None
    voice: str = "Samantha"
    rate: Optional[int] = None
    pitch: Optional[str] = "+0Hz"
    description: Optional[str] = ""


class MemoConfig(BaseModel):
    default_duration_seconds: float = 180.0
    auto_extend_seconds: float = 60.0
    auto_synthesize: bool = True
    export_to_clipboard: bool = False
    energy_threshold: float = 0.003


class AmbientConfig(BaseModel):
    enabled: bool = False
    auto_triage: bool = True
    source: Literal["mic", "loopback"] = "mic"
    energy_threshold: float = 0.005
    silence_duration: float = 1.2
    max_utterance_seconds: float = 15.0
    notify_hud: bool = True


class STTBiasingConfig(BaseModel):
    enabled: bool = True
    auto_scan_repo: bool = True
    custom_words: list[str] = Field(default_factory=list)


class VoicegencyConfig(BaseModel):
    version: int = 1
    tier: str = "community"
    license_key: str = ""
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    stt_biasing: STTBiasingConfig = Field(default_factory=STTBiasingConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    ambient: AmbientConfig = Field(default_factory=AmbientConfig)
    audio_cues: AudioCuesConfig = Field(default_factory=AudioCuesConfig)
    antigravity: AntigravityConfig = Field(default_factory=AntigravityConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    global_hotkey: GlobalHotkeyConfig = Field(default_factory=GlobalHotkeyConfig)
    memo: MemoConfig = Field(default_factory=MemoConfig)
    agents: dict[str, AgentVoiceProfile] = Field(default_factory=dict)
    subagents: dict[str, AgentVoiceProfile] = Field(default_factory=dict)

    def resolve_voice(
        self,
        agent_or_role: Optional[str] = None,
        is_focused: bool = True,
    ) -> tuple[str, str, int]:
        """
        Resolve (provider, voice, rate) for a specific agent or subagent role.
        If is_focused is False (unfocused/background agent), uses the configured unfocused voice
        or a distinctive contrasting acoustic persona so background updates sound distinct.
        """
        default_provider = self.tts.provider
        default_voice = self.tts.voice
        default_rate = self.tts.rate

        # 1. If this is an unfocused / background agent:
        if not is_focused:
            if self.antigravity.unfocused_agent_voice:
                return default_provider, self.antigravity.unfocused_agent_voice, default_rate

            if agent_or_role:
                key = agent_or_role.lower().strip()
                if key in self.subagents and self.subagents[key].voice:
                    prof = self.subagents[key]
                    return (
                        prof.provider or default_provider,
                        prof.voice,
                        prof.rate if prof.rate is not None else default_rate,
                    )
                if key in self.agents and self.agents[key].voice:
                    prof = self.agents[key]
                    return (
                        prof.provider or default_provider,
                        prof.voice,
                        prof.rate if prof.rate is not None else default_rate,
                    )

            # Dynamic contrasting acoustic persona for background agents
            if default_provider == "edge_tts":
                if "Christopher" in default_voice:
                    return default_provider, "en-US-AriaNeural", default_rate
                elif "Aria" in default_voice:
                    return default_provider, "en-US-ChristopherNeural", default_rate
                else:
                    return default_provider, "en-GB-SoniaNeural", default_rate
            elif default_provider == "mac_say":
                if "Samantha" in default_voice:
                    return default_provider, "Daniel", default_rate
                elif "Daniel" in default_voice:
                    return default_provider, "Samantha", default_rate
                else:
                    return default_provider, "Daniel", default_rate
            else:
                return default_provider, default_voice, default_rate

        if not agent_or_role:
            return default_provider, default_voice, default_rate

        key = agent_or_role.lower().strip()

        # Check in subagents first if prefixed or matched
        if key in self.subagents:
            profile = self.subagents[key]
            return (
                profile.provider or default_provider,
                profile.voice or default_voice,
                profile.rate if profile.rate is not None else default_rate,
            )

        # Check in agents
        if key in self.agents:
            profile = self.agents[key]
            return (
                profile.provider or default_provider,
                profile.voice or default_voice,
                profile.rate if profile.rate is not None else default_rate,
            )

        return default_provider, default_voice, default_rate


# Backwards compatibility alias
VoicegencyConfig = VoicegencyConfig


def get_default_config_path() -> Path:
    """Return the default configuration path (~/.voicegency/config.yaml)."""
    return Path.home() / ".voicegency" / "config.yaml"


def find_config_path(custom_path: Optional[str] = None) -> Optional[Path]:
    """Find the configuration file by checking candidate paths."""
    if custom_path and Path(custom_path).is_file():
        return Path(custom_path)

    env_path = os.getenv("VOICEGENCY_CONFIG")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    local_path = Path("config.yaml")
    if local_path.is_file():
        return local_path

    home_path = get_default_config_path()
    if home_path.is_file():
        return home_path

    return None


def load_config(custom_path: Optional[str] = None) -> VoicegencyConfig:
    """Load configuration from file, or return defaults if not found."""
    path = find_config_path(custom_path)
    if path and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return VoicegencyConfig(**data)
        except Exception as e:
            print(f"[Voicegency] Warning: Error parsing {path}: {e}. Using defaults.")
            return VoicegencyConfig()
    return VoicegencyConfig()


def save_config(config: VoicegencyConfig, target_path: Optional[Path] = None) -> Path:
    """Save configuration to the designated YAML file."""
    dest = target_path or get_default_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
    return dest
