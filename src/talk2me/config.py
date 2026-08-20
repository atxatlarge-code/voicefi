"""
Configuration manager for Talk 2 Me.
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
    elevenlabs_api_key: Optional[str] = ""
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"


class STTConfig(BaseModel):
    provider: Literal["whisper_local", "groq", "apple_speech"] = "whisper_local"
    model_size: str = "base.en"
    language: str = "en"
    groq_api_key: Optional[str] = ""
    groq_model: str = "whisper-large-v3-turbo"


class VADConfig(BaseModel):
    silence_duration: float = 1.5
    energy_threshold: float = 0.015
    max_record_seconds: int = 45
    sample_rate: int = 16000


class AudioCuesConfig(BaseModel):
    enabled: bool = True
    start_chime: str = "/System/Library/Sounds/Tink.aiff"
    done_chime: str = "/System/Library/Sounds/Pop.aiff"
    error_chime: str = "/System/Library/Sounds/Basso.aiff"


class AntigravityConfig(BaseModel):
    auto_listen: bool = True
    read_summary_aloud: bool = True
    max_spoken_words: int = 25
    inject_to_active_window: bool = True


class GlobalHotkeyConfig(BaseModel):
    enabled: bool = True
    focus_and_talk_hotkey: str = "`"
    dictate_hotkey: str = "<alt>+t"


class Talk2MeConfig(BaseModel):
    version: int = 1
    tier: Literal["community", "pro"] = "community"
    license_key: Optional[str] = ""
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    audio_cues: AudioCuesConfig = Field(default_factory=AudioCuesConfig)
    antigravity: AntigravityConfig = Field(default_factory=AntigravityConfig)
    global_hotkey: GlobalHotkeyConfig = Field(default_factory=GlobalHotkeyConfig)


def get_default_config_path() -> Path:
    """Return the default configuration path (~/.talk2me/config.yaml)."""
    return Path.home() / ".talk2me" / "config.yaml"


def find_config_path(custom_path: Optional[str] = None) -> Optional[Path]:
    """Find the configuration file by checking candidate paths."""
    if custom_path and Path(custom_path).is_file():
        return Path(custom_path)

    env_path = os.getenv("TALK2ME_CONFIG")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    local_path = Path("config.yaml")
    if local_path.is_file():
        return local_path

    home_path = get_default_config_path()
    if home_path.is_file():
        return home_path

    return None


def load_config(custom_path: Optional[str] = None) -> Talk2MeConfig:
    """Load configuration from file, or return defaults if not found."""
    path = find_config_path(custom_path)
    if path and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return Talk2MeConfig(**data)
        except Exception as e:
            print(f"[Talk2Me] Warning: Error parsing {path}: {e}. Using defaults.")
            return Talk2MeConfig()
    return Talk2MeConfig()


def save_config(config: Talk2MeConfig, target_path: Optional[Path] = None) -> Path:
    """Save configuration to the designated YAML file."""
    dest = target_path or get_default_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
    return dest
