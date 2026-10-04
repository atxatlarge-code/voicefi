"""Text-to-Speech provider factory, voice catalog, and exports."""

from typing import Optional
from voicefi.config import VoiceFiConfig
from voicefi.tts.base import (
    BaseTTS,
    stop_all_speech,
    stop_active_playback,
    is_agent_speaking,
    set_agent_speaking,
    is_agent_audio_playing,
    set_agent_audio_playing,
    set_cross_process_hud_state,
    get_cross_process_hud_state,
    clear_cross_process_hud_state,
    escape_to_stop_speech,
    is_tab_key,
    is_option_tab_event,
    is_option_pressed,
    focus_speaking_window,
    get_recent_speaking_info,
    clear_speech_stopped_time,
)
from voicefi.tts.mac_say import MacSayTTS, normalize_mac_rate
from voicefi.tts.edge_tts import EdgeTTS, normalize_edge_rate
from voicefi.tts.elevenlabs import ElevenLabsTTS
from voicefi.tts.f5_tts import F5TTS
from voicefi.tts.kokoro_tts import KokoroTTS
from voicefi.tts.gemini_tts import GeminiTTS
from voicefi.tts.voice_acting import VoiceActingTTS, QwenTTS, QwenCloneTTS
from voicefi.tts.catalog import (
    VoicePersona,
    CURATED_PERSONAS,
    get_curated_personas,
    find_persona,
    list_system_mac_voices,
    list_all_available_voices,
)
from voicefi.tts.offline import (
    is_voice_installed,
    list_installed_neural_voices,
    open_spoken_content_settings,
    configure_offline_voice,
    run_download_ava_workflow,
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
    speed_override: Optional[any] = None,
    is_focused: bool = True,
    project_name: Optional[str] = None,
    workspace_path: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
) -> BaseTTS:
    """
    Instantiate the configured TTS engine.
    Supports agent-specific voice resolution, project-level overrides, custom cloned voices, dynamic overrides,
    speed talking multipliers, and distinct acoustic persona for unfocused/background agents.
    """
    # 1. Resolve base provider, voice, rate from agent profile, project profile, or global config
    provider, voice, rate = config.resolve_voice(
        agent_name,
        is_focused=is_focused,
        project_name=project_name,
        workspace_path=workspace_path,
    )

    # Package Turn-End Mode: standard (open-source) vs gemini_live (theatrical)
    turn_end_mode = getattr(getattr(config, "tts", None), "turn_end_mode", "standard")
    if not provider_override:
        if turn_end_mode == "gemini_live" and provider in ("edge_tts", "gemini"):
            provider = "gemini_live"
            if voice in ("en-US-AvaNeural", "Viv", "en-US-ChristopherNeural", "Christopher", ""):
                voice = getattr(getattr(config, "tts", None), "voice", "Puck") or "Puck"
        elif turn_end_mode == "standard" and provider in ("gemini_live", "gemini"):
            provider = "gemini"

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
    if speed_override is not None:
        from voicefi.audio.speed_talk import resolve_speed_multiplier, multiplier_to_wpm

        mult = resolve_speed_multiplier(speed_override)
        rate = multiplier_to_wpm(mult)
    elif rate_override is not None:
        from voicefi.audio.speed_talk import (
            resolve_speed_multiplier,
            multiplier_to_wpm,
            SPEED_PRESETS,
        )

        if isinstance(rate_override, str) and (
            rate_override.lower().strip() in SPEED_PRESETS
            or rate_override.lower().strip().endswith("x")
        ):
            mult = resolve_speed_multiplier(rate_override)
            rate = multiplier_to_wpm(mult)
        else:
            rate = rate_override

    # 3. Resolve cloned voice profiles
    clone_prof = None
    try:
        from voicefi.tts.cloning import VoiceCloneManager

        vcm = VoiceCloneManager()
        for cand in (
            voice_override,
            getattr(persona, "name", None) if "persona" in locals() else None,
            voice,
        ):
            if cand:
                clone_prof = vcm.get_cloned_voice(cand)
                if clone_prof:
                    break

        if clone_prof:
            if not provider_override:
                provider = clone_prof.provider
            if provider == "elevenlabs":
                voice = clone_prof.id
            elif provider in ("f5_tts", "local_clone", "kokoro", "luxtts"):
                voice = clone_prof.id
            else:
                voice = clone_prof.calibrated_voice or "en-GB-ThomasNeural"
            if rate_override is None and clone_prof.calibrated_rate:
                rate = clone_prof.calibrated_rate
    except Exception:
        pass

    provider = provider.lower()

    # If edge_tts provider is selected but voice is a mac_say voice, switch to Edge default (AvaNeural)
    if provider == "edge_tts" and (
        voice in ("Samantha", "Ava (Premium)", "Ava (Enhanced)", "Nathan (Enhanced)", "Alex")
        or not voice
    ):
        voice = "en-US-AvaNeural"
    elif provider == "mac_say" and ("Neural" in str(voice) or not voice):
        from voicefi.tts.offline import is_voice_installed

        target_offline = None
        if agent_name:
            key = agent_name.lower().strip()
            if key in config.agents and getattr(config.agents[key], "offline_voice", None):
                target_offline = config.agents[key].offline_voice
            elif key in config.subagents and getattr(config.subagents[key], "offline_voice", None):
                target_offline = config.subagents[key].offline_voice

        if target_offline:
            has_offline, exact_offline = is_voice_installed(target_offline)
            voice = exact_offline if (has_offline and exact_offline) else target_offline
        else:
            has_ava, ava_name = is_voice_installed("Ava")
            voice = ava_name if (has_ava and ava_name) else "Samantha"

    if provider in ("kokoro", "kokoro_onnx"):
        eng = KokoroTTS(
            voice=voice,
            speed=float(rate) / 200.0 if (rate and isinstance(rate, (int, float))) else 1.0,
        )
    elif provider in (
        "qwen",
        "qwen_tts",
        "qwen_clone",
        "mlx_clone",
        "f5_tts",
        "local_clone",
        "luxtts",
    ):
        agent_key = (agent_name or "").lower().strip()
        agent_prof = None
        if hasattr(config, "agents") and agent_key in config.agents:
            agent_prof = config.agents[agent_key]
        elif hasattr(config, "subagents") and agent_key in config.subagents:
            agent_prof = config.subagents[agent_key]

        ref_audio = getattr(agent_prof, "f5_ref_audio", None) if agent_prof else None
        ref_text = getattr(agent_prof, "f5_ref_text", None) if agent_prof else None

        if not ref_audio:
            ref_audio = getattr(config.tts, "f5_ref_audio", None)
            ref_text = getattr(config.tts, "f5_ref_text", None)

        if clone_prof:
            is_specific_clone = (
                clone_prof.id in ("walken_continental", "the_continental")
                or "continental" in getattr(clone_prof, "name", "").lower()
                or (voice and "continental" in str(voice).lower())
            )
            if not ref_audio or (
                is_specific_clone and not getattr(agent_prof, "f5_ref_audio", None)
            ):
                if clone_prof.sample_paths:
                    ref_audio = clone_prof.sample_paths[0]
                if clone_prof.labels and clone_prof.labels.get("ref_text"):
                    ref_text = clone_prof.labels.get("ref_text")

        cloning_engine = getattr(config.tts, "cloning_engine", "auto")
        use_qwen = (
            provider in ("qwen", "qwen_tts", "qwen_clone", "mlx_clone")
            or getattr(clone_prof, "provider", None) in ("qwen", "qwen_clone")
            or (cloning_engine == "qwen" and QwenTTS.is_available())
            or (
                cloning_engine == "auto"
                and provider != "f5_tts"
                and QwenTTS.is_available()
                and not F5TTS.is_available()
            )
        )

        target_speed = 1.0
        if speed_override is not None:
            from voicefi.audio.speed_talk import resolve_speed_multiplier

            target_speed = resolve_speed_multiplier(speed_override)
        elif clone_prof and getattr(clone_prof, "speed", None):
            target_speed = float(getattr(clone_prof, "speed"))
        elif ref_audio and "continental" in str(ref_audio).lower():
            target_speed = 0.92

        intro_sfx = getattr(agent_prof, "intro_sfx", None) if agent_prof else None
        intro_sfx_vol = getattr(agent_prof, "intro_sfx_volume", None) if agent_prof else None
        if not intro_sfx and clone_prof:
            intro_sfx = getattr(clone_prof, "intro_sfx", None)
            intro_sfx_vol = getattr(clone_prof, "intro_sfx_volume", None)
        if not intro_sfx:
            intro_sfx = getattr(config.tts, "intro_sfx", None)
            intro_sfx_vol = getattr(config.tts, "intro_sfx_volume", 0.25)
        if intro_sfx_vol is None:
            intro_sfx_vol = 0.25

        if use_qwen and QwenTTS.is_available() and ref_audio:
            eng = QwenTTS(
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed=target_speed,
                persona_name=clone_prof.name
                if clone_prof
                else getattr(config.tts, "voice", "Custom Clone"),
                apply_silk_mastering=True,
                intro_sfx=intro_sfx,
                intro_sfx_volume=intro_sfx_vol,
            )
        elif F5TTS.is_available() and ref_audio:
            nfe = getattr(config.tts, "f5_nfe_step", None) or 24
            if clone_prof and getattr(clone_prof, "nfe_step", None):
                nfe = int(getattr(clone_prof, "nfe_step"))

            eng = F5TTS(
                ref_audio=ref_audio,
                ref_text=ref_text,
                model_name=getattr(config.tts, "f5_model_name", "F5TTS_v1_Base"),
                device=getattr(config.tts, "f5_device", "auto"),
                nfe_step=nfe,
                speed=target_speed,
                persona_name=clone_prof.name
                if clone_prof
                else getattr(config.tts, "voice", "Custom Clone"),
            )
        elif QwenTTS.is_available() and ref_audio:
            eng = QwenTTS(
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed=target_speed,
                persona_name=clone_prof.name
                if clone_prof
                else getattr(config.tts, "voice", "Custom Clone"),
                apply_silk_mastering=True,
                intro_sfx=intro_sfx,
                intro_sfx_volume=intro_sfx_vol,
            )
        elif clone_prof and clone_prof.calibrated_voice:
            calibrated_v = clone_prof.calibrated_voice
            effective_rate = clone_prof.calibrated_rate or rate or 165
            if "Neural" in str(calibrated_v):
                eng = EdgeTTS(
                    voice=calibrated_v,
                    rate=f"{effective_rate}wpm"
                    if isinstance(effective_rate, int)
                    else effective_rate,
                    pitch=getattr(clone_prof, "calibrated_pitch", "+0Hz") or "+0Hz",
                    volume=getattr(config.tts, "volume", 1.0),
                    streaming=config.tts.streaming,
                    agent_name=agent_name or "VoiceFi",
                    offline_fallback_voice="Ava (Premium)",
                )
            else:
                eng = MacSayTTS(
                    voice=calibrated_v,
                    rate=effective_rate,
                    volume=getattr(config.tts, "volume", 1.0),
                )
        elif KokoroTTS.is_available():
            is_british = clone_prof and (
                "British" in getattr(clone_prof, "vocal_range", "")
                or "GB" in getattr(clone_prof, "calibrated_voice", "")
                or any(
                    k in getattr(clone_prof, "name", "").lower()
                    for k in ("documentary", "broadcaster", "attenborough")
                )
            )
            if is_british:
                kokoro_v = "bm_george"
                kokoro_speed = 0.88
            elif clone_prof and (
                "Bass" in getattr(clone_prof, "vocal_range", "")
                or "Baritone" in getattr(clone_prof, "vocal_range", "")
            ):
                kokoro_v = "am_michael"
                kokoro_speed = 1.0
            else:
                kokoro_v = "am_adam"
                kokoro_speed = 1.0

            eng = KokoroTTS(
                voice=kokoro_v,
                speed=float(rate) / 200.0
                if (rate and isinstance(rate, (int, float)))
                else kokoro_speed,
            )
        else:
            calibrated_v = (clone_prof.calibrated_voice if clone_prof else None) or (
                voice
                if ("Neural" in str(voice) or "Premium" in str(voice))
                else "en-GB-ThomasNeural"
            )
            if "Neural" in str(calibrated_v):
                eng = EdgeTTS(
                    voice=calibrated_v,
                    rate=f"{rate}wpm" if isinstance(rate, int) else rate,
                    volume=getattr(config.tts, "volume", 1.0),
                    streaming=config.tts.streaming,
                    agent_name=agent_name or "VoiceFi",
                    offline_fallback_voice="Ava (Premium)",
                )
            else:
                eng = MacSayTTS(
                    voice=calibrated_v,
                    rate=rate,
                    volume=getattr(config.tts, "volume", 1.0),
                )
    elif provider == "elevenlabs":
        # Check if voice is a known cloned voice or preset
        resolved_voice_id = voice
        persona = find_persona(voice)
        if persona and persona.provider == "elevenlabs":
            resolved_voice_id = persona.id
        elif not voice or voice == "Samantha":
            resolved_voice_id = config.tts.elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"

        eng = ElevenLabsTTS(
            api_key=config.tts.elevenlabs_api_key or "",
            voice_id=resolved_voice_id,
        )
    elif provider in (
        "gemini",
        "gemini_tts",
        "gemini_flash",
        "gemini_flash_tts",
        "gemini_lite",
        "gemini_flash_lite_tts",
        "gemini_live",
    ):
        from voicefi.config import resolve_gemini_api_key

        resolved_key = resolve_gemini_api_key(config)
        if provider == "gemini_live":
            chosen_model = (
                getattr(getattr(config, "gemini", None), "live_model", "gemini-3.8-live")
                if hasattr(config, "gemini")
                else "gemini-3.8-live"
            )
        elif provider in ("gemini_lite", "gemini_flash_lite_tts"):
            chosen_model = (
                getattr(
                    getattr(config, "gemini", None), "tts_lite_model", "gemini-3.8-flash-lite-tts"
                )
                if hasattr(config, "gemini")
                else "gemini-3.8-flash-lite-tts"
            )
        else:
            chosen_model = (
                getattr(getattr(config, "gemini", None), "tts_model", "gemini-3.8-flash-tts")
                if hasattr(config, "gemini")
                else "gemini-3.8-flash-tts"
            )
        eng = GeminiTTS(
            api_key=resolved_key,
            voice=voice,
            model=chosen_model,
        )
    elif provider in ("voice_acting", "local_actor", "actor", "mlx_actor", "fish_speech", "fish"):
        from voicefi.tts.voice_acting import VoiceActingTTS

        effective_speed = (
            float(rate) / 200.0
            if (rate and isinstance(rate, (int, float)) and rate != 200)
            else None
        )
        agent_key = (agent_name or "").lower().strip()
        agent_prof = config.agents.get(agent_key) if hasattr(config, "agents") else None
        intro_sfx = (
            getattr(agent_prof, "intro_sfx", None)
            if agent_prof
            else getattr(config.tts, "intro_sfx", None)
        )
        intro_sfx_vol = (
            getattr(agent_prof, "intro_sfx_volume", 0.25)
            if agent_prof
            else getattr(config.tts, "intro_sfx_volume", 0.25)
        )
        if intro_sfx_vol is None:
            intro_sfx_vol = 0.25

        ref_audio = (
            getattr(agent_prof, "f5_ref_audio", None)
            if agent_prof
            else getattr(config.tts, "f5_ref_audio", None)
        )
        ref_text = (
            getattr(agent_prof, "f5_ref_text", None)
            if agent_prof
            else getattr(config.tts, "f5_ref_text", None)
        )
        if not ref_audio and clone_prof:
            if clone_prof.sample_paths:
                ref_audio = clone_prof.sample_paths[0]
            if clone_prof.labels and clone_prof.labels.get("ref_text"):
                ref_text = clone_prof.labels.get("ref_text")

        eng = VoiceActingTTS(
            persona_name=voice or "drill_sergeant",
            ref_audio=ref_audio,
            ref_text=ref_text,
            speed=effective_speed,
            intro_sfx=intro_sfx,
            intro_sfx_volume=intro_sfx_vol,
        )
    elif provider == "edge_tts":
        offline_v = None
        if agent_name:
            key = agent_name.lower().strip()
            if key in config.agents and getattr(config.agents[key], "offline_voice", None):
                offline_v = config.agents[key].offline_voice
            elif key in config.subagents and getattr(config.subagents[key], "offline_voice", None):
                offline_v = config.subagents[key].offline_voice
        if not offline_v:
            offline_v = "Ava (Premium)"

        eng = EdgeTTS(
            voice=voice,
            rate=rate,
            volume=getattr(config.tts, "volume", 1.0),
            streaming=config.tts.streaming,
            agent_name=agent_name or "VoiceFi",
            offline_fallback_voice=offline_v,
        )
    else:
        # Default to native macOS say
        eng = MacSayTTS(voice=voice, rate=rate, volume=getattr(config.tts, "volume", 1.0))

    persona = find_persona(voice)
    eng.agent_name = agent_name or "VoiceFi"
    eng.persona_name = persona.name if persona else voice
    eng.app_name = app_name or "Antigravity"
    eng.conv_id = conv_id or ""
    eng.workspace_path = workspace_path or ""
    return eng


from voicefi.audio.speed_talk import (
    SPEED_PRESETS,
    resolve_speed_multiplier,
    multiplier_to_wpm,
    multiplier_to_edge_rate,
    calculate_time_saved,
    accelerate_audio,
    compress_speech_silence,
    dynamic_ramp_audio,
)

__all__ = [
    "BaseTTS",
    "MacSayTTS",
    "EdgeTTS",
    "ElevenLabsTTS",
    "F5TTS",
    "GeminiTTS",
    "normalize_edge_rate",
    "normalize_mac_rate",
    "VoicePersona",
    "CURATED_PERSONAS",
    "get_curated_personas",
    "find_persona",
    "list_system_mac_voices",
    "list_all_available_voices",
    "is_voice_installed",
    "list_installed_neural_voices",
    "open_spoken_content_settings",
    "configure_offline_voice",
    "run_download_ava_workflow",
    "get_tts_engine",
    "stop_all_speech",
    "is_agent_speaking",
    "set_agent_speaking",
    "is_agent_audio_playing",
    "set_agent_audio_playing",
    "set_cross_process_hud_state",
    "get_cross_process_hud_state",
    "clear_cross_process_hud_state",
    "escape_to_stop_speech",
    "is_tab_key",
    "is_option_tab_event",
    "is_option_pressed",
    "focus_speaking_window",
    "get_recent_speaking_info",
    "clear_speech_stopped_time",
    "ClonedVoiceProfile",
    "VoiceCloneManager",
    "estimate_pitch_f0",
    "analyze_audio_acoustics",
    "generate_persona_prompt",
    "TRAINING_PROMPTS",
    "SPEED_PRESETS",
    "resolve_speed_multiplier",
    "multiplier_to_wpm",
    "multiplier_to_edge_rate",
    "calculate_time_saved",
    "accelerate_audio",
    "compress_speech_silence",
    "dynamic_ramp_audio",
]
