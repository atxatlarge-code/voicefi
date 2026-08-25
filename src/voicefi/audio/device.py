"""
Audio hardware device detection and acoustic profiling.
Identifies built-in MacBook speakers vs. headphones/AirPods to prevent acoustic feedback loops.
"""

from typing import Dict, Any, Optional, Tuple


def get_default_audio_devices() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Retrieve default (input_device, output_device) metadata from sounddevice."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        in_idx, out_idx = sd.default.device
        
        in_dev = devices[in_idx] if (in_idx is not None and 0 <= in_idx < len(devices)) else None
        out_dev = devices[out_idx] if (out_idx is not None and 0 <= out_idx < len(devices)) else None
        return in_dev, out_dev
    except Exception:
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
            "headphone", "headset", "airpod", "buds", "ear",
            "bluetooth", "wireless", "external", "dongle", "dac"
        )
        if any(marker in out_name for marker in headphone_markers):
            return False

        # Check for built-in laptop speaker markers
        speaker_markers = (
            "speaker", "built-in output", "internal", "macbook", "imac", "mac mini"
        )
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
            "headphone", "headset", "airpod", "buds", "ear",
            "bluetooth", "wireless"
        )
        if any(marker in out_name for marker in headphone_markers):
            return True

        # If not built-in speaker and not empty, likely external audio device/headphones
        return not is_using_builtin_speakers()
    except Exception:
        return False


def get_audio_device_profile() -> Dict[str, Any]:
    """Return a comprehensive hardware acoustic profile for diagnostics and telemetry."""
    in_dev, out_dev = get_default_audio_devices()
    builtin_spk = is_using_builtin_speakers()
    headphones = is_headphone_or_headset_active()
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
        "hardware_aec_supported": hardware_aec,
        "hardware_aec_backend": "Apple AUVoiceProcessing (VoiceProcessingIO)" if hardware_aec else "None",
        "acoustic_safe_mode_recommended": builtin_spk and not headphones and not hardware_aec,
    }
