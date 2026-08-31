"""
Configuration manager for VoiceFi.
Handles loading, validating, and saving YAML configuration files with defaults.
"""

from pathlib import Path
from typing import Literal, Optional, Union
import os
import subprocess
import getpass
import re
import yaml
from pydantic import BaseModel, Field


def detect_system_user_name(prefer_first_name: bool = True) -> str:
    """
    Intelligently auto-detect the user's real human first name from macOS / developer environment.
    Sources queried in priority order:
    1. macOS User Account Full Name (`id -F`) -> e.g. "Jake Trigg" -> "Jake"
    2. Global Git Author Name (`git config --get user.name`)
    3. macOS Directory Service (`dscl . -read /Users/$USER RealName`)
    4. System login user (`$USER` / getpass) cleaned and capitalized
    """
    # 1. Try macOS `id -F` (Full human name in macOS System Settings)
    try:
        res = subprocess.run(["id", "-F"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
        if res.returncode == 0 and res.stdout.strip():
            name = res.stdout.strip()
            if name and not name.lower().startswith("uid"):
                return name.split()[0].title() if prefer_first_name else name
    except Exception:
        pass

    # 2. Try git config user.name
    try:
        res = subprocess.run(["git", "config", "--get", "user.name"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
        if res.returncode == 0 and res.stdout.strip():
            name = res.stdout.strip()
            if name and not name.endswith("-code") and not name.endswith("-bot"):
                return name.split()[0].title() if prefer_first_name else name
    except Exception:
        pass

    # 3. Try dscl Directory Service on macOS
    try:
        user = getpass.getuser()
        res = subprocess.run(["dscl", ".", "-read", f"/Users/{user}", "RealName"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
        if res.returncode == 0 and res.stdout.strip():
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith("RealName:")]
            if lines and lines[0]:
                name = lines[0]
                return name.split()[0].title() if prefer_first_name else name
    except Exception:
        pass

    # 4. Fallback to cleaned $USER username
    try:
        user = getpass.getuser()
        clean = re.sub(r'[\d._-]+', ' ', user).strip()
        if clean:
            return clean.split()[0].title()
    except Exception:
        pass

    return "Developer"


class TTSConfig(BaseModel):
    provider: Literal["mac_say", "edge_tts", "elevenlabs", "f5_tts", "local_clone", "gemini", "gemini_live"] = "edge_tts"
    voice: str = "en-US-AvaNeural"
    rate: Optional[int] = 200
    volume: float = 1.0
    streaming: bool = True
    elevenlabs_api_key: Optional[str] = ""
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"
    gemini_api_key: Optional[str] = ""
    f5_device: Literal["auto", "mps", "cpu", "cuda"] = "auto"
    f5_model_name: str = "F5-TTS"
    f5_ref_audio: Optional[str] = None
    f5_ref_text: Optional[str] = None



class STTConfig(BaseModel):
    provider: Literal["whisper_local", "groq", "apple_speech"] = "whisper_local"
    model_size: str = "base.en"
    language: str = "en"
    streaming: bool = False
    groq_api_key: Optional[str] = ""
    groq_model: str = "whisper-large-v3-turbo"


# Fibonacci Pause Delay presets (seconds)
FIBONACCI_PAUSE_DELAYS: list[float] = [1.0, 2.0, 3.0, 5.0, 8.0, 11.0]


class VADConfig(BaseModel):
    engine: Literal["silero", "energy", "auto"] = "auto"
    speech_threshold: float = 0.5
    mode: Literal["auto", "ptt", "hybrid"] = "hybrid"
    silence_duration: float = 1.4
    energy_threshold: float = 0.004
    max_record_seconds: int = 45
    sample_rate: int = 16000
    ptt_release_delay_ms: int = 150
    barge_in: Union[bool, Literal["auto"]] = "auto"
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
    max_spoken_words: int = 60
    inject_to_active_window: bool = True
    unfocused_agent_voice: Optional[str] = None
    unfocused_voice_prefix: bool = True
    show_speech_popup: bool = True
    speech_popup_linger_seconds: float = 3.0
    speech_popup_position: Literal["top_center", "top_right", "bottom_right"] = "top_right"
    auto_send: bool = True
    persistent_hud: bool = True
    mirror_native_mic: bool = False
    show_native_mic_shortcut: bool = False


class HUDConfig(BaseModel):
    enabled: bool = True
    persistent: bool = True
    auto_send: bool = True
    show_live_transcript: bool = True
    fullscreen_overlay: bool = True  # True = float above full-screen games/apps; False = allow full-screen overlap/hide behind
    position: Literal["top_center", "top_right", "bottom_right"] = "top_right"
    margin_x: float = 20.0
    margin_y: float = 96.0  # Vertical margin in points below menu bar (clearing Chrome's top tab strip & address bar)
    linger_seconds: float = 2.0
    always_on_vad: bool = True


class ClaudeConfig(BaseModel):
    auto_listen: bool = False
    read_summary_aloud: bool = False
    auto_submit: bool = False  # False = paste into terminal prompt for manual review; True = auto-press Enter
    max_spoken_words: int = 60
    inject_to_active_window: bool = True
    show_speech_popup: bool = True


class CodexConfig(BaseModel):
    auto_listen: bool = False
    read_summary_aloud: bool = False
    auto_submit: bool = False  # False = paste into prompt for manual review; True = auto-press Enter
    max_spoken_words: int = 60
    inject_to_active_window: bool = True
    show_speech_popup: bool = True


class HooksConfig(BaseModel):
    enabled: bool = True
    antigravity: bool = True
    claude: bool = True
    codex: bool = True


class IntegrationsConfig(BaseModel):
    antigravity: bool = True
    claude_code: bool = True
    chatgpt: bool = True
    codex: bool = True
    cursor: bool = True
    windsurf: bool = True
    system_dictation: bool = True


class GlobalHotkeyConfig(BaseModel):
    enabled: bool = True
    talk_to_agent_hotkey: str = "<alt>+v"
    focus_and_talk_hotkey: str = "<ctrl>+r"
    jump_to_agent_hotkey: str = "<ctrl>+j"
    hub_hotkey: str = "<ctrl>+<shift>+j"
    dictate_hotkey: str = "<ctrl>+t"
    new_conversation_hotkey: str = "<cmd>+<shift>+n"
    show_dictation_hud: bool = True
    preserve_clipboard: bool = True


class AgentVoiceProfile(BaseModel):
    provider: Optional[Literal["mac_say", "edge_tts", "elevenlabs", "f5_tts", "local_clone", "gemini", "gemini_live"]] = None
    voice: str = "en-US-AvaNeural"
    rate: Optional[int] = None
    pitch: Optional[str] = "+0Hz"
    description: Optional[str] = ""
    offline_voice: Optional[str] = None
    offline_provider: Optional[str] = "mac_say"
    f5_ref_audio: Optional[str] = None
    f5_ref_text: Optional[str] = None


class GeminiConfig(BaseModel):
    enabled: bool = True
    api_key: Optional[str] = ""
    model: str = "gemini-2.5-flash"
    live_model: str = "gemini-2.0-flash-exp"
    live_voice: str = "Aoede"  # Aoede, Puck, Charon, Kore, Fenrir
    temperature: float = 0.2
    max_tokens: int = 150
    enable_soundbite_distillation: bool = True
    enable_memo_structuring: bool = True
    enable_phonetic_resolver: bool = False


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


class WakeWordConfig(BaseModel):
    enabled: bool = True
    phrase: str = "Hey Viv"
    aliases: list[str] = Field(
        default_factory=lambda: ["hey viv", "viv", "hey vifi", "vifi", "hey antigravity", "antigravity"]
    )
    sensitivity: float = 0.6
    chime: bool = True
    target_engine: str = "antigravity"
    source: Literal["mic", "default"] = "mic"
    energy_threshold: float = 0.005
    silence_duration: float = 0.7


class STTBiasingConfig(BaseModel):
    enabled: bool = True
    auto_scan_repo: bool = True
    custom_words: list[str] = Field(default_factory=list)


class CompanionConfig(BaseModel):
    enabled: bool = True
    port: int = 5141
    host: str = "127.0.0.1"  # Default to loopback for security
    audio_routing: Literal["smart", "origin_only", "phone_only", "mac_only", "both"] = "smart"
    mute_mac_when_companion_active: bool = False
    auth_token: Optional[str] = None


class StudioConfig(BaseModel):
    auto_open_browser: bool = True
    energy_broadcast_hz: int = 10
    particle_theme: str = "google"


def default_agents_catalog() -> dict[str, AgentVoiceProfile]:
    return {
        "antigravity": AgentVoiceProfile(
            voice="en-US-AvaNeural",
            provider="edge_tts",
            offline_voice="Ava (Premium)",
            description="Antigravity Primary Agent",
        ),
        "claude": AgentVoiceProfile(
            voice="en-US-SteffanNeural",
            provider="edge_tts",
            offline_voice="Jamie (Premium)",
            description="Claude Code Pair Programmer",
        ),
        "gemini": AgentVoiceProfile(
            voice="Aoede",
            provider="gemini",
            description="Google Gemini Agent",
        ),
        "cursor": AgentVoiceProfile(
            voice="en-US-JennyNeural",
            provider="edge_tts",
            description="Cursor Composer Assistant",
        ),
        "openai": AgentVoiceProfile(
            voice="en-US-EmmaNeural",
            provider="edge_tts",
            description="OpenAI Agent (Emma)",
        ),
        "codex": AgentVoiceProfile(
            voice="en-US-EmmaNeural",
            provider="edge_tts",
            description="OpenAI Codex Agent (Emma)",
        ),
        "obsidian": AgentVoiceProfile(
            voice="en-US-EmmaNeural",
            provider="edge_tts",
            description="Obsidian Second Voice",
        ),
        "aria": AgentVoiceProfile(
            voice="en-US-EmmaNeural",
            provider="edge_tts",
            description="Aria (Second Voice / Obsidian)",
        ),
        "spark": AgentVoiceProfile(
            voice="en-US-AvaNeural",
            provider="edge_tts",
            offline_voice="Ava (Premium)",
            description="Gemini Spark Agent (Viv / Christopher)",
        ),
    }


class IPCConfig(BaseModel):
    enabled: bool = True
    socket_path: str = "/tmp/voicefi.sock"
    ws_port: int = 8765
    ws_host: str = "127.0.0.1"
    enable_ws_fallback: bool = True
    auto_reconnect: bool = True
    reconnect_interval_seconds: float = 1.5


class SparkConfig(BaseModel):
    enabled: bool = True
    persona: str = "Viv"  # Viv, Christopher, Ava, etc.
    agent_name: str = "Spark"
    enable_model_distillation: bool = True
    max_spoken_words: int = 30
    auto_submit_turn_complete: bool = True


class ProActiveFeedbackLoopConfig(BaseModel):
    enabled: bool = True
    chime_cue: bool = True
    barge_in: Union[bool, Literal["auto"]] = "auto"
    timeout_seconds: float = 12.0
    cancel_on_typing: bool = True


class ProActiveMeetingAssistantConfig(BaseModel):
    enabled: bool = False
    auto_notes: bool = True
    auto_dispatch_subagents: bool = True
    auto_execute_actions: bool = True
    sync_linear: bool = True
    post_slack: bool = False
    default_slack_channel: str = "#general"
    notes_dir: str = "~/.voicefi/meetings"
    granola_formatting: bool = True
    energy_threshold: float = 0.005
    silence_duration: float = 1.2
    max_utterance_seconds: float = 15.0


class ProActiveIntentRoutingConfig(BaseModel):
    enabled: bool = True
    route_to_claude: bool = True
    route_to_slack: bool = True
    route_to_linear: bool = True


class ProActiveConfig(BaseModel):
    feedback_loop: ProActiveFeedbackLoopConfig = Field(default_factory=ProActiveFeedbackLoopConfig)
    meeting_assistant: ProActiveMeetingAssistantConfig = Field(default_factory=ProActiveMeetingAssistantConfig)
    intent_routing: ProActiveIntentRoutingConfig = Field(default_factory=ProActiveIntentRoutingConfig)


class VoiceFiConfig(BaseModel):
    version: int = 1
    enabled: bool = True  # Global pause/resume kill-switch
    telemetry: bool = True  # Anonymous crash & diagnostic error reporting (opt-out with DO_NOT_TRACK=1)
    auto_update: bool = False  # Silent background auto-updater for Pro tier
    tier: str = "community"
    license_key: str = ""
    trial_started_at: Optional[float] = None  # Epoch timestamp when 14-day free trial started
    trial_seal: Optional[str] = None  # Cryptographic hardware-anchored HMAC seal against tampering
    trial_duration_days: int = 14  # 14-day trial duration
    posthog_api_key: str = ""
    user_name: str = Field(default_factory=detect_system_user_name)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    stt_biasing: STTBiasingConfig = Field(default_factory=STTBiasingConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    proactive: ProActiveConfig = Field(default_factory=ProActiveConfig)
    ambient: AmbientConfig = Field(default_factory=AmbientConfig)
    wakeword: WakeWordConfig = Field(default_factory=WakeWordConfig)
    audio_cues: AudioCuesConfig = Field(default_factory=AudioCuesConfig)
    antigravity: AntigravityConfig = Field(default_factory=AntigravityConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    codex: CodexConfig = Field(default_factory=CodexConfig)
    companion: CompanionConfig = Field(default_factory=CompanionConfig)
    studio: StudioConfig = Field(default_factory=StudioConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    global_hotkey: GlobalHotkeyConfig = Field(default_factory=GlobalHotkeyConfig)
    hud: HUDConfig = Field(default_factory=HUDConfig)
    memo: MemoConfig = Field(default_factory=MemoConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    ipc: IPCConfig = Field(default_factory=IPCConfig)
    spark: SparkConfig = Field(default_factory=SparkConfig)
    agents: dict[str, AgentVoiceProfile] = Field(default_factory=default_agents_catalog)
    subagents: dict[str, AgentVoiceProfile] = Field(default_factory=dict)

    def resolve_voice(
        self,
        agent_name: Optional[str] = None,
        is_focused: bool = True,
    ) -> tuple[str, str, int]:
        """
        Resolve (provider, voice_id, rate_wpm) for a given agent or subagent.
        """
        default_provider = self.tts.provider
        default_voice = self.tts.voice
        default_rate = self.tts.rate or 200

        # If not focused, check for unfocused voice override or dynamic contrast
        if not is_focused:
            if self.antigravity.unfocused_agent_voice:
                return default_provider, self.antigravity.unfocused_agent_voice, default_rate

            if default_provider == "edge_tts":
                if "Christopher" in default_voice:
                    return default_provider, "en-US-EmmaNeural", default_rate
                elif "Aria" in default_voice or "Emma" in default_voice:
                    return default_provider, "en-US-ChristopherNeural", default_rate
                elif "Ava" in default_voice or "Viv" in default_voice:
                    return default_provider, "en-US-GuyNeural", default_rate
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

        if not agent_name:
            return default_provider, default_voice, default_rate

        key = agent_name.lower().strip()

        # Check subagents map
        if key in self.subagents and self.subagents[key]:
            profile = self.subagents[key]
            return (
                profile.provider or default_provider,
                profile.voice or default_voice,
                profile.rate if profile.rate is not None else default_rate,
            )

        # Check agents map
        if key in self.agents and self.agents[key]:
            profile = self.agents[key]
            return (
                profile.provider or default_provider,
                profile.voice or default_voice,
                profile.rate if profile.rate is not None else default_rate,
            )

        # Built-in agent persona fallbacks
        if key in ("claude", "claude_code"):
            return "edge_tts", "en-US-SteffanNeural", default_rate
        elif key == "antigravity":
            return "edge_tts", "en-US-AvaNeural", default_rate
        elif key == "cursor":
            return "edge_tts", "en-US-JennyNeural", default_rate
        elif key in ("obsidian", "aria", "emma", "openai", "codex", "chatgpt", "debugger", "tester"):
            return "edge_tts", "en-US-AvaNeural", default_rate
        elif key in ("researcher", "architect"):
            return "edge_tts", "en-GB-SoniaNeural", default_rate

        return default_provider, default_voice, default_rate


# Backwards compatibility alias
VoiceFiConfig = VoiceFiConfig


def get_default_config_path() -> Path:
    """Return the default configuration path (~/.voicefi/config.yaml)."""
    return Path.home() / ".voicefi" / "config.yaml"


def find_config_path(custom_path: Optional[str] = None) -> Optional[Path]:
    """Find the configuration file by checking candidate paths."""
    if custom_path and Path(custom_path).is_file():
        return Path(custom_path)

    env_path = os.getenv("VOICEFI_CONFIG")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    home_path = get_default_config_path()
    if home_path.is_file():
        return home_path

    local_path = Path("config.yaml")
    if local_path.is_file():
        return local_path

    return None


def load_config(custom_path: Optional[str] = None) -> VoiceFiConfig:
    """Load configuration from file, or return defaults if not found."""
    path = find_config_path(custom_path)
    if path and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cfg = VoiceFiConfig(**data)
            if not cfg.user_name or cfg.user_name.strip().lower() in ("auto", "developer", ""):
                cfg.user_name = detect_system_user_name()

            # Bidirectional sync between legacy auto_listen and proactive.feedback_loop
            if "proactive" in data and "feedback_loop" in data.get("proactive", {}):
                fl_enabled = cfg.proactive.feedback_loop.enabled
                cfg.antigravity.auto_listen = fl_enabled
                cfg.claude.auto_listen = fl_enabled
            elif "antigravity" in data and "auto_listen" in data.get("antigravity", {}):
                ag_al = cfg.antigravity.auto_listen
                cfg.proactive.feedback_loop.enabled = ag_al

            return cfg
        except Exception as e:
            print(f"[VoiceFi] Warning: Error parsing {path}: {e}. Using defaults.")
            return VoiceFiConfig()
    return VoiceFiConfig()


def save_config(config: VoiceFiConfig, target_path: Optional[Union[Path, str]] = None) -> Path:
    """Save configuration to the designated YAML file."""
    dest = Path(target_path) if target_path else (find_config_path() or get_default_config_path())
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
    return dest
