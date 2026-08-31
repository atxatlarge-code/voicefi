"""
Offline Neural Voice Management & Automation for macOS.
Enables zero-latency 0ms speech synthesis using Apple's local neural voices (e.g. Ava Premium, Nathan Enhanced, Lee Premium).
"""

import os
import re
import sys
import time
import subprocess
from typing import Optional, Tuple, List, Dict, Any

from voicefi.config import load_config, save_config, VoiceFiConfig


def is_voice_installed(target_name: str = "Ava") -> Tuple[bool, Optional[str]]:
    """
    Check if a specific macOS system voice is installed and available in `say -v ?`.

    Checks for exact matches as well as Premium / Enhanced variants.
    e.g. 'Ava' matches 'Ava (Premium)', 'Ava (Enhanced)', or 'Ava'.

    Returns:
        (is_installed, matched_voice_name)
    """
    target_clean = target_name.strip().lower()
    if target_clean == "viv":
        target_clean = "ava"
    try:
        output = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.DEVNULL)
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            # Match voice name at start of line
            m = re.match(r"^([^\t#]+?)\s+([a-z]{2}_[A-Za-z0-9]+)\s+#", line)
            v_name = m.group(1).strip() if m else line.split()[0]
            v_name_lower = v_name.lower()

            # 1. Exact match (e.g. 'Ava (Premium)')
            if v_name_lower == target_clean:
                return True, v_name

            # 2. Base name match (e.g. 'Ava' matches 'Ava (Premium)' or 'Ava (Enhanced)')
            # Ensure it matches as a distinct word prefix or base
            if v_name_lower.startswith(f"{target_clean} (") or v_name_lower == target_clean:
                return True, v_name

            # 3. Check if target is inside name (e.g. 'Ava' inside 'Ava (Premium)')
            if target_clean in v_name_lower.split():
                return True, v_name
    except Exception:
        pass
    return False, None


def list_installed_neural_voices() -> List[Dict[str, str]]:
    """Return all installed Apple Premium and Enhanced neural voices on this Mac."""
    neural_voices = []
    try:
        output = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.DEVNULL)
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            m = re.match(r"^([^\t#]+?)\s+([a-z]{2}_[A-Za-z0-9]+)\s+#\s*(.*)$", line)
            if m:
                v_name = m.group(1).strip()
                v_locale = m.group(2).strip()
                v_desc = m.group(3).strip()
            else:
                parts = line.split()
                v_name = parts[0]
                v_locale = parts[1] if len(parts) > 1 else ""
                v_desc = " ".join(parts[2:]) if len(parts) > 2 else ""

            if "(premium)" in v_name.lower() or "(enhanced)" in v_name.lower():
                neural_voices.append(
                    {
                        "id": v_name,
                        "name": v_name,
                        "locale": v_locale,
                        "description": v_desc,
                        "is_premium": "(premium)" in v_name.lower(),
                    }
                )
    except Exception:
        pass
    return neural_voices


def open_spoken_content_settings() -> bool:
    """
    Directly open macOS System Settings to Accessibility > Spoken Content.
    This is where users download Apple's Ava (Premium), Nathan, and other neural voices.
    """
    try:
        # Standard macOS URL scheme for Spoken Content
        subprocess.run(
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.universalaccess?SpokenContent",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )

        # Best-effort AppleScript to bring System Settings frontmost
        applescript = """
        tell application "System Settings"
            activate
        end tell
        """
        subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return True
    except Exception:
        try:
            # Fallback for older macOS versions
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.speech"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return True
        except Exception:
            return False


def configure_offline_voice(
    voice_name: str = "Ava (Premium)",
    config: Optional[VoiceFiConfig] = None,
    speak_confirmation: bool = True,
) -> Dict[str, Any]:
    """
    Configure VoiceFi to use the given offline macOS system voice as default.
    Updates global TTS provider to 'mac_say' and syncs agent profiles.
    """
    if config is None:
        config = load_config()

    config.tts.provider = "mac_say"
    config.tts.voice = voice_name

    # Also update primary agent profiles if present
    for agent_key in ("antigravity", "claude", "cursor"):
        if agent_key in config.agents:
            config.agents[agent_key].provider = "mac_say"
            config.agents[agent_key].voice = voice_name

    save_config(config)

    # Speak confirmation
    if speak_confirmation:
        try:
            from voicefi.tts.mac_say import MacSayTTS

            engine = MacSayTTS(voice=voice_name, rate=config.tts.rate)
            engine.speak(
                f"Hello! {voice_name} is active for instant zero-latency offline speech.",
                block=True,
            )
        except Exception:
            pass

    return {
        "success": True,
        "provider": "mac_say",
        "voice": voice_name,
        "message": f"Successfully configured VoiceFi with offline neural voice '{voice_name}' (0ms latency).",
    }


def run_download_ava_workflow(
    auto_poll: bool = True,
    timeout_seconds: int = 300,
    silent: bool = False,
    check_only: bool = False,
) -> Dict[str, Any]:
    """
    Run the interactive or automated workflow to detect or guide downloading Ava (Premium) on macOS.

    1. Checks if Ava is already installed.
    2. If yes -> immediately configures VoiceFi and speaks confirmation.
    3. If no -> opens System Settings to Spoken Content, displays clear guidance, and polls until complete.
    """
    # 1. Check if Ava is already installed
    installed, exact_voice = is_voice_installed("Ava")

    if check_only:
        return {
            "installed": installed,
            "voice": exact_voice,
            "message": f"Ava is installed as '{exact_voice}'."
            if installed
            else "Ava is not currently installed.",
        }

    if installed and exact_voice:
        if not silent:
            print("\n" + "=" * 65)
            print(f" ✨ Detected Apple Neural Voice: \033[1;32m{exact_voice}\033[0m")
            print("=" * 65)
            print(" 🚀 Configuring VoiceFi for instant 0ms offline speech...")

        result = configure_offline_voice(exact_voice, speak_confirmation=not silent)
        if not silent:
            print(
                f" ✅ VoiceFi default voice is now set to: \033[1;36m{exact_voice}\033[0m (mac_say)"
            )
            print(
                " ⚡ Latency: ~0ms (Zero network roundtrip, runs 100% offline on Apple Silicon)\n"
            )
        return result

    # 2. Not installed yet — display guidance and open settings
    if not silent:
        print("\n" + "╭" + "─" * 68 + "╮")
        print("│ 🎙️  \033[1mVoiceFi • Download Ava (Premium) for 0ms Offline Speech\033[0m        │")
        print("╰" + "─" * 68 + "╯")
        print(
            "\nApple includes the ultra-realistic \033[1mAva (Premium)\033[0m neural voice directly"
        )
        print("in macOS for zero-latency, 100% private offline speech synthesis.\n")
        print("⚡ \033[1;36mOpening macOS Spoken Content settings for you now...\033[0m\n")
        print("👉 \033[1mQuick Steps in System Settings:\033[0m")
        print('   1. Click the \033[1m"System voice"\033[0m dropdown')
        print('   2. Select \033[1m"Manage Voices..."\033[0m')
        print(
            '   3. Find or search \033[1m"Ava"\033[0m under \033[1mEnglish (United States)\033[0m'
        )
        print(
            "   4. Click the download icon \033[1;32m⬇️\033[0m next to \033[1mAva (Premium)\033[0m (or Ava Enhanced)"
        )
        print("   5. Click \033[1mOK\033[0m when the download finishes\n")

    opened = open_spoken_content_settings()
    if not opened and not silent:
        print("⚠️ Could not open System Settings automatically. Please open:")
        print("   System Settings ➔ Accessibility ➔ Spoken Content ➔ Manage Voices...\n")

    if not auto_poll:
        return {
            "success": False,
            "installed": False,
            "message": "Opened System Settings for Ava download. Polling skipped.",
        }

    # 3. Live polling loop
    if not silent:
        print(
            "⏳ \033[1mWaiting for Ava download to finish...\033[0m (auto-detecting, press Ctrl+C to cancel)"
        )

    start_time = time.time()
    spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0

    while time.time() - start_time < timeout_seconds:
        try:
            installed, exact_voice = is_voice_installed("Ava")
            if installed and exact_voice:
                if not silent:
                    print(f"\r\033[K🎉 \033[1;32m{exact_voice} detected and ready!\033[0m")
                    print("⚡ Applying configuration...")

                result = configure_offline_voice(exact_voice, speak_confirmation=not silent)
                if not silent:
                    print(
                        f"✅ VoiceFi is now configured for instant 0ms offline speech with \033[1;36m{exact_voice}\033[0m!\n"
                    )
                return result

            if not silent:
                elapsed = int(time.time() - start_time)
                spin = spinner_chars[idx % len(spinner_chars)]
                print(
                    f"\r\033[K{spin} Waiting for Ava download to complete... ({elapsed}s elapsed)",
                    end="",
                    flush=True,
                )
                idx += 1

            time.sleep(2.0)
        except KeyboardInterrupt:
            if not silent:
                print(
                    "\n\n💡 Polling paused. Once Ava finishes downloading, activate it anytime with:"
                )
                print(
                    '   \033[1;36mvifi voice download-ava\033[0m or \033[1;36mvifi voice set antigravity "Ava (Premium)"\033[0m\n'
                )
            return {
                "success": False,
                "installed": False,
                "message": "User cancelled Ava download waiting loop.",
            }

    if not silent:
        print("\n\n⏱️ Polling timeout reached (5 minutes).")
        print("Once the download finishes in System Settings, run:")
        print("   \033[1;36mvifi voice download-ava\033[0m\n")

    return {
        "success": False,
        "installed": False,
        "message": "Timeout reached waiting for Ava download.",
    }
