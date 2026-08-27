import time
import threading
import getpass
from voicefi.config import load_config
from voicefi.tts import get_tts_engine
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder

def check_and_prompt_permissions() -> bool:
    """Check macOS Accessibility trust, prompt system dialog, and open settings if needed."""
    try:
        import ApplicationServices
        options = {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(options)
        if not trusted:
            print("🔐 [Permissions Notice]")
            print("   VoiceFi uses macOS Accessibility for the universal <Esc> stop key and <Ctrl>+T dictation.")
            print("   👉 Opening System Settings... Please toggle your terminal/IDE to ON.\n")
            from voicefi.integrations.injector import open_accessibility_settings
            open_accessibility_settings()
            time.sleep(1.0)
            return False
        return True
    except Exception:
        return False


def run_onboarding():
    config = load_config()
    try:
        from voicefi.telemetry import capture_event
        capture_event("onboarding_started")
    except Exception:
        pass

    check_and_prompt_permissions()
    
    # Pre-warm STT model in background while greeting plays
    import threading
    stt = get_stt_engine(config)
    threading.Thread(target=lambda: getattr(stt, "_get_model", lambda: None)(), daemon=True).start()

    _, resolved_voice, _ = config.resolve_voice("antigravity")
    tts = get_tts_engine(config, voice_override=resolved_voice)
    voice_label = getattr(tts, "voice", "Viv")
    if "Ava" in voice_label or "Viv" in voice_label:
        voice_label = "Viv"
    elif "-" in voice_label:
        voice_label = voice_label.split("-")[-1].replace("Neural", "")

    from voicefi.config import detect_system_user_name
    user_name = config.user_name or detect_system_user_name(prefer_first_name=True) or "Jake"

    print("\n" + "="*50)
    print(" 🚀 VoiceFi First-Time User Experience")
    print("="*50 + "\n")

    # Short DAC warmup pause to ensure CoreAudio / Bluetooth hardware is un-muted
    time.sleep(0.3)

    # --- Question 1 ---
    prompt1 = f"Hey... {user_name}? Can I call you {user_name}?"
    print(f"🎙️  [{voice_label}]: \"{prompt1}\"")
    tts.speak(prompt1)

    # Listen 1
    silence_cut = getattr(config.vad, "silence_duration", 1.0)
    recorder = AudioRecorder(
        sample_rate=config.vad.sample_rate,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=silence_cut,
        max_record_seconds=config.vad.max_record_seconds,
        barge_in=False,
    )
    print("\n🔴 Listening... (speak your answer and pause)")
    audio_data, temp_wav = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️  Speech detected..."),
    )
    print("⏳ Transcribing...")
    text1 = stt.transcribe(temp_wav)
    temp_wav.unlink(missing_ok=True)
    
    print(f"📝 You said: \"{text1}\"\n")
    time.sleep(1)
    
    # Very naive name extraction for the demo: grab the last word they said.
    extracted_name = user_name
    if text1.strip():
        cleaned = "".join(c for c in text1 if c.isalnum() or c.isspace())
        words = cleaned.split()
        if words:
            extracted_name = words[-1].capitalize()
    
    # --- Question 2 ---
    prompt2 = f"Awesome, {extracted_name}! I'm not quite used to the sound of my own voice yet. Um, well, thank you for installing VoiceFi! I'm curious, what made you want to talk with me?"
    print(f"🎙️  [{voice_label}]: \"{prompt2}\"")
    tts.speak(prompt2)

    # Listen 2
    print("\n🔴 Listening... (speak your answer and pause)")
    audio_data2, temp_wav2 = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️  Speech detected..."),
    )
    print("⏳ Transcribing...")
    text2 = stt.transcribe(temp_wav2)
    temp_wav2.unlink(missing_ok=True)

    print(f"📝 You said: \"{text2}\"\n")
    time.sleep(0.5)

    # --- Question 3 ---
    prompt3 = "Aha, copy that. So this confirms the test feedback loop. Next up, which of the connections would you like to use first? Here's a list:"
    print(f"🎙️  [{voice_label}]: \"{prompt3}\"")
    
    # Speak concurrently so active connections display while she speaks
    speech_thread = threading.Thread(target=lambda: tts.speak(prompt3, block=True), daemon=True)
    speech_thread.start()
    
    # Mock opening the HUD
    print("\n🖥️  [HUD Opens: Showing Active Connections]")
    print("   a. Antigravity")
    print("   b. Claude")
    print("   c. Cursor")
    print("   etc")
    
    # Wait for speech playback to finish before opening microphone
    speech_thread.join()
    
    # Listen 3
    print("\n🔴 Listening... (speak your answer and pause)")
    audio_data3, temp_wav3 = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️  Speech detected..."),
    )
    print("⏳ Transcribing...")
    text3 = stt.transcribe(temp_wav3)
    temp_wav3.unlink(missing_ok=True)
    
    print(f"📝 You said: \"{text3}\"\n")
    
def resolve_agent_target(text: str) -> str:
    """Robustly resolve spoken user intent to a supported agent target."""
    if not text:
        return "antigravity"
    t = text.lower().strip()
    
    # 1. Explicit agent names / keywords
    if any(k in t for k in ["antigravity", "gemini", "option a", "choice a", "letter a", "first", "number 1", "number one"]):
        return "antigravity"
    if any(k in t for k in ["claude", "anthropic", "option b", "choice b", "letter b", "second", "number 2", "number two"]):
        return "claude"
    if any(k in t for k in ["cursor", "windsurf", "vscode", "code", "option c", "choice c", "letter c", "third", "number 3", "number three"]):
        return "cursor"
        
    # 2. Single-letter / digit matches
    words = [w.strip(".,!?") for w in t.split()]
    if "a" in words or "1" in words:
        return "antigravity"
    if "b" in words or "2" in words:
        return "claude"
    if "c" in words or "3" in words:
        return "cursor"

    # 3. Affirmative defaults ("yes", "sure", "send it", "let them know", "please do", "all", "ready") -> Antigravity
    if any(k in t for k in ["yes", "sure", "send", "notify", "let them know", "yep", "yeah", "ok", "okay", "please", "all", "ready"]):
        return "antigravity"

    return "antigravity"


    # --- Question 3 Dispatch ---
    target_agent = resolve_agent_target(text3)
    
    if target_agent == "antigravity":
        print("🚀 Dispatching to Antigravity...\n")
        print("📦 [Background Handoff Payload]")
        print(f"   -> Name: {extracted_name}")
        print(f"   -> Event: VoiceFi Initial Setup Complete")
        print(f"   -> User's Reason for Voice: \"{text2}\"")
        print(f"   -> Request: \"{text3}\"\n")
        
        payload = f"VoiceFi Setup Complete for {extracted_name}.\nReason they installed VoiceFi: {text2}\nIntent: {text3}\n\nPlease respond naturally to their reason and ask what they want to build first!"
        try:
            from voicefi.integrations.injector import send_message_to_antigravity, focus_antigravity, create_new_antigravity_conversation
            delivered = send_message_to_antigravity(text=payload, sender_name="VoiceFi Setup")
            if not delivered:
                cid = create_new_antigravity_conversation(prompt=payload, title=f"VoiceFi Welcome: {extracted_name}")
                delivered = bool(cid)
            
            # Bring Antigravity window forward so user sees the active response
            focus_antigravity(focus_input=False)
            
            if delivered:
                print("✅ Payload successfully delivered to Antigravity via IPC.")
                print("✨ Antigravity will now respond directly in your IDE (and VoiceFi will speak its reply when it finishes!).")
            else:
                print("⚠️ Failed to deliver automatically. Ensure Antigravity is active.")
        except Exception as e:
            print(f"⚠️ Error dispatching to Antigravity: {e}")
            
    elif target_agent == "claude":
        print("🚀 Dispatching to Claude Code...\n")
        print("📦 [Background Handoff Payload]")
        print(f"   -> Name: {extracted_name}")
        print(f"   -> Event: VoiceFi Initial Setup Complete")
        print(f"   -> User's Reason for Voice: \"{text2}\"")
        print(f"   -> Request: \"{text3}\"\n")
        
        payload = f"VoiceFi setup complete for {extracted_name}. Reason: {text2}. Ready to pair program!"
        try:
            from voicefi.integrations.injector import inject_text_to_claude
            delivered = inject_text_to_claude(payload, submit_enter=True)
            if delivered:
                print("✅ Payload successfully injected into Claude Code terminal session.")
                print("✨ Claude Code will respond directly in your terminal (and VoiceFi will speak its reply!).")
            else:
                print("💡 Claude Code terminal window not detected. Start Claude with 'claude' in any terminal!")
        except Exception as e:
            print(f"⚠️ Error dispatching to Claude Code: {e}")
            
    elif target_agent == "cursor":
        print("🚀 Dispatching to Cursor / Editor...\n")
        payload = f"VoiceFi setup complete for {extracted_name}. Reason: {text2}. Ready to code!"
        try:
            from voicefi.integrations.injector import inject_text_to_active_app
            inject_text_to_active_app(payload, submit_enter=True)
            print("✅ Payload injected into active editor.")
        except Exception as e:
            print(f"⚠️ Error dispatching to editor: {e}")
            
    print("\n" + "="*50)
    print(" 🎉 Onboarding flow complete!")
    print("="*50 + "\n")

    try:
        from voicefi.telemetry import capture_event
        capture_event("onboarding_completed", {
            "target_agent": target_agent,
            "preferred_name_customized": bool(extracted_name and extracted_name != user_name),
        })
    except Exception:
        pass


