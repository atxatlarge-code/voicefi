"""
Audio hardware device detection and acoustic profiling.
Identifies built-in MacBook speakers vs. headphones/AirPods to prevent acoustic feedback loops.
"""

import os
import shutil
import subprocess
from typing import Dict, Any, Optional, Tuple, List


def get_default_audio_devices() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Retrieve default (input_device, output_device) metadata from sounddevice."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        in_idx, out_idx = sd.default.device

        in_dev = devices[in_idx] if (in_idx is not None and 0 <= in_idx < len(devices)) else None
        out_dev = (
            devices[out_idx] if (out_idx is not None and 0 <= out_idx < len(devices)) else None
        )
        if (in_dev is None and out_dev is None) and (
            os.getenv("VOICEFI_MOCK_AUDIO") == "1"
            or os.getenv("VOICEFI_HEADLESS") == "1"
            or os.getenv("VOICEFI_TESTING") == "1"
        ):
            return (
                {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0},
                {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
            )
        return in_dev, out_dev
    except Exception:
        if (
            os.getenv("VOICEFI_MOCK_AUDIO") == "1"
            or os.getenv("VOICEFI_HEADLESS") == "1"
            or os.getenv("VOICEFI_TESTING") == "1"
        ):
            return (
                {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0},
                {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
            )
        return None, None


def is_using_builtin_speakers() -> bool:
    """
    Check if the active audio output device is the Mac's built-in laptop speakers.
    When true, acoustic coupling into the built-in mic is high, requiring safe barge-in gating.
    """
    try:
        _, out_dev = get_default_audio_devices()
        if not out_dev:
            return False

        out_name = str(out_dev.get("name", "")).lower()

        # Check for headphone/external overrides first
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "external",
            "dongle",
            "dac",
        )
        if any(marker in out_name for marker in headphone_markers):
            return False

        # Check for built-in laptop speaker markers
        speaker_markers = ("speaker", "built-in output", "internal", "macbook", "imac", "mac mini")
        return any(marker in out_name for marker in speaker_markers)
    except Exception:
        return False


def is_headphone_or_headset_active() -> bool:
    """
    Check if headphones, AirPods, or an external headset are active.
    When true, there is zero acoustic bleed from speakers into mic, so active barge-in is 100% safe.
    """
    try:
        _, out_dev = get_default_audio_devices()
        if not out_dev:
            return False

        out_name = str(out_dev.get("name", "")).lower()
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "in-ear",
            "iem",
        )
        if any(marker in out_name for marker in headphone_markers):
            return True

        # Check for external speaker/monitor markers that are definitely NOT headphones
        external_speaker_markers = (
            "display",
            "monitor",
            "tv",
            "hdmi",
            "soundbar",
            "speaker",
            "studio display",
        )
        if any(marker in out_name for marker in external_speaker_markers):
            return False

        # If it's built-in laptop speakers, definitely not headphones
        if is_using_builtin_speakers():
            return False

        # Do not assume unknown external devices/monitors/DACs are headphones
        return False
    except Exception:
        return False


def is_bluetooth_input_active() -> bool:
    """
    Check if the current default audio input device is a Bluetooth headset or earbuds.
    When true, macOS CoreAudio switches the Bluetooth profile from high-fidelity A2DP stereo
    to low-fidelity SCO/HFP mono to service the microphone channel.
    """
    try:
        in_dev, _ = get_default_audio_devices()
        if not in_dev:
            return False

        in_name = str(in_dev.get("name", "")).lower()
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "in-ear",
            "iem",
        )
        return any(marker in in_name for marker in headphone_markers)
    except Exception:
        return False


def get_audio_device_profile() -> Dict[str, Any]:
    """Return a comprehensive hardware acoustic profile for diagnostics and telemetry."""
    in_dev, out_dev = get_default_audio_devices()
    builtin_spk = is_using_builtin_speakers()
    headphones = is_headphone_or_headset_active()
    bt_input = is_bluetooth_input_active()
    lock_recommended = headphones and bt_input
    try:
        from voicefi.audio.native_vpio import is_vpio_supported

        hardware_aec = is_vpio_supported()
    except Exception:
        hardware_aec = False

    return {
        "default_input": in_dev.get("name") if in_dev else "None",
        "default_output": out_dev.get("name") if out_dev else "None",
        "is_builtin_speakers": builtin_spk,
        "is_headphones_active": headphones,
        "is_bluetooth_input_active": bt_input,
        "audio_input_lock_recommended": lock_recommended,
        "audio_input_lock_tip": (
            "Keep input on MacBook Pro Microphone in System Settings → Sound → Input to lock earbuds in high-fidelity stereo."
            if lock_recommended
            else ""
        ),
        "hardware_aec_supported": hardware_aec,
        "hardware_aec_backend": "Apple AUVoiceProcessing (VoiceProcessingIO)"
        if hardware_aec
        else "None",
        "acoustic_safe_mode_recommended": builtin_spk and not headphones and not hardware_aec,
    }


def _find_audio_switcher_bin() -> Optional[str]:
    """Locate SwitchAudioSource binary on macOS."""
    candidates = [
        "SwitchAudioSource",
        "/opt/homebrew/bin/SwitchAudioSource",
        "/usr/local/bin/SwitchAudioSource",
    ]
    for cand in candidates:
        if shutil.which(cand) or os.path.exists(cand):
            return cand
    return None


def list_audio_input_devices() -> List[str]:
    """List all available audio input device names."""
    sw = _find_audio_switcher_bin()
    if sw:
        try:
            res = subprocess.run(
                [sw, "-a", "-t", "input"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        except Exception:
            pass

    # Fallback to sounddevice
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        names = []
        for d in devices:
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name")
                if name and name not in names:
                    names.append(name)
        return names
    except Exception:
        return []


def get_current_input_device_name() -> str:
    """Get the currently selected default audio input device name."""
    sw = _find_audio_switcher_bin()
    if sw:
        try:
            res = subprocess.run(
                [sw, "-c", "-t", "input"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    in_dev, _ = get_default_audio_devices()
    return in_dev.get("name", "Unknown") if in_dev else "Unknown"


def set_audio_input_device(device_name: str) -> bool:
    """Set the system audio input device by name via SwitchAudioSource."""
    sw = _find_audio_switcher_bin()
    if not sw:
        return False
    try:
        res = subprocess.run(
            [sw, "-s", device_name, "-t", "input"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return res.returncode == 0
    except Exception:
        return False


def find_builtin_microphone_name() -> Optional[str]:
    """Find the Mac built-in microphone device name if available."""
    inputs = list_audio_input_devices()
    builtin_markers = ("macbook", "built-in microphone", "internal microphone", "built-in mic")
    for name in inputs:
        low = name.lower()
        if any(marker in low for marker in builtin_markers):
            return name
    return None


def find_headset_microphone_name() -> Optional[str]:
    """Find connected Bluetooth headset/earbuds microphone name if available."""
    inputs = list_audio_input_devices()
    headphone_markers = (
        "buds",
        "airpod",
        "headphone",
        "headset",
        "bluetooth",
        "wireless",
        "in-ear",
        "iem",
    )
    for name in inputs:
        low = name.lower()
        if any(marker in low for marker in headphone_markers):
            return name
    return None


def pin_mac_microphone() -> Tuple[bool, str]:
    """
    Lock/switch input to the Mac built-in microphone.
    Preserves connected Bluetooth earbuds in high-fidelity A2DP stereo.
    """
    mac_mic = find_builtin_microphone_name()
    if not mac_mic:
        return False, "Built-in Mac microphone not found in input devices."

    current = get_current_input_device_name()
    if current.lower() == mac_mic.lower():
        return True, f"Already pinned to {mac_mic}."

    ok = set_audio_input_device(mac_mic)
    if ok:
        return True, f"Locked input to {mac_mic} (earbuds preserved in high-fidelity stereo)."
    return False, f"Failed to switch input to {mac_mic}."


def set_headset_microphone() -> Tuple[bool, str]:
    """Switch input to connected Bluetooth earbuds/headset for roaming."""
    headset_mic = find_headset_microphone_name()
    if not headset_mic:
        return False, "No Bluetooth headset or earbuds microphone detected."

    current = get_current_input_device_name()
    if current.lower() == headset_mic.lower():
        return True, f"Already set to {headset_mic}."

    ok = set_audio_input_device(headset_mic)
    if ok:
        return True, f"Switched input to {headset_mic} for roaming (earbuds in headset mode)."
    return False, f"Failed to switch input to {headset_mic}."


def toggle_microphone_source() -> Tuple[bool, str]:
    """Toggle input between Mac built-in microphone and Bluetooth headset."""
    current = get_current_input_device_name()
    mac_mic = find_builtin_microphone_name()
    headset_mic = find_headset_microphone_name()

    if mac_mic and current.lower() == mac_mic.lower():
        if headset_mic:
            return set_headset_microphone()
        return False, "No headset microphone available to switch to."
    else:
        if mac_mic:
            return pin_mac_microphone()
        return False, "Built-in Mac microphone not found."


def auto_pin_mac_microphone(force: bool = False) -> Tuple[bool, str]:
    """
    Automatically pin to Mac microphone if headphones/earbuds are active and
    macOS has hijacked input to the earbuds.
    """
    if not force:
        headphones = is_headphone_or_headset_active()
        bt_input = is_bluetooth_input_active()
        if not (headphones and bt_input):
            return False, "Auto-pin not needed (earbuds are not capturing input)."
    return pin_mac_microphone()

