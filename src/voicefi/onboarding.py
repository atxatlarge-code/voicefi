import time
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
    tts = get_tts_engine(config, voice_override="Christopher")
    stt = get_stt_engine(config)
    
    user_name = getpass.getuser().capitalize()
    
    print("\n" + "="*50)
    print(" 🚀 VoiceFi First-Time User Experience")
    print("="*50 + "\n")
    
    # --- Question 1 ---
    prompt1 = f"Hey.... {user_name}? Can I call you {user_name}?"
    print(f"🎙️  [Christopher]: \"{prompt1}\"")
    tts.speak(prompt1)
    
    # Listen 1
    recorder = AudioRecorder(
        sample_rate=config.vad.sample_rate,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=3.0, # wait for 3.0s of silence
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
    print(f"🎙️  [Christopher]: \"{prompt2}\"")
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
    time.sleep(1)
    
    # --- Question 3 ---
    prompt3 = "Aha, copy that. So this confirms the offline feedback loop. Next up, would you like to send this to an agent or tool? Below is a list of the active connections. Would you like to let any of them know?"
    print(f"🎙️  [Christopher]: \"{prompt3}\"")
    tts.speak(prompt3)
    
    # Mock opening the HUD
    print("\n🖥️  [HUD Opens: Showing Active Connections]")
    print("   a. Antigravity")
    print("   b. Claude")
    print("   c. Cursor")
    print("   etc")
    
    # Listen 3
    print("\n🔴 Listening... (speak your answer and pause)")
    audio_data3, temp_wav3 = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️  Speech detected..."),
    )
    print("⏳ Transcribing...")
    text3 = stt.transcribe(temp_wav3)
    temp_wav3.unlink(missing_ok=True)
    
    print(f"📝 You said: \"{text3}\"\n")
    
    # Simple check for a tool
    text3_lower = text3.lower() if text3 else ""
    if "antigravity" in text3_lower:
        print("🚀 Dispatching to Antigravity...\n")
        print("📦 [Background Handoff Payload]")
        print(f"   -> Name: {extracted_name}")
        print(f"   -> Event: VoiceFi Initial Setup Complete")
        print(f"   -> User's Reason for Voice: \"{text2}\"")
        print(f"   -> Request: \"{text3}\"\n")
        
        try:
            from voicefi.integrations.injector import send_message_to_antigravity
            payload = f"VoiceFi Setup Complete for {extracted_name}.\nReason they installed VoiceFi: {text2}\nIntent: {text3}\n\nPlease respond naturally to their reason and ask what they want to build first!"
            success = send_message_to_antigravity(text=payload, sender_name="VoiceFi Setup")
            if success:
                print("✅ Payload successfully delivered to Antigravity via IPC.")
                print("✨ Antigravity will now respond directly in your IDE (and VoiceFi will speak its reply when it finishes!).")
            else:
                print("⚠️ Failed to deliver to Antigravity. Is the IDE active?")
        except ImportError:
            print("⚠️ Could not import injector.")
            
    elif "claude" in text3_lower or "cursor" in text3_lower:
        print(f"🚀 Dispatching to {text3_lower.strip()} (Mock)...")
        time.sleep(2)
        print("✅ Tool processed handoff.\n")
    else:
        print("ℹ️  No specific active connections mentioned. Directing to connection setup guide...")
        
    print("\n" + "="*50)
    print(" 🎉 Onboarding flow complete!")
    print("="*50 + "\n")

    try:
        from voicefi.telemetry import capture_event
        capture_event("onboarding_completed", {
            "target_agent": "antigravity" if "antigravity" in text3_lower else ("claude" if "claude" in text3_lower else ("cursor" if "cursor" in text3_lower else "none")),
            "preferred_name_customized": bool(extracted_name and extracted_name != user_name),
        })
    except Exception:
        pass

