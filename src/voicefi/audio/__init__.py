from voicefi.audio.chimes import play_chime
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.echo_canceller import (
    is_acoustic_echo,
    record_agent_spoken,
    get_recent_spoken_texts,
    clear_agent_spoken_history,
)

from voicefi.audio.device import (
    is_using_builtin_speakers,
    is_headphone_or_headset_active,
    get_audio_device_profile,
)

from voicefi.audio.vad import (
    VoiceActivityDetector,
    SileroVAD,
    find_silero_vad_model,
)

from voicefi.audio.player import StreamingAudioPlayer
from voicefi.audio.output_lock import (
    exclusive_audio,
    is_audio_output_locked,
    force_release_audio_lock,
)

__all__ = [
    "play_chime",
    "AudioRecorder",
    "StreamingAudioPlayer",
    "exclusive_audio",
    "is_audio_output_locked",
    "force_release_audio_lock",
    "VoiceActivityDetector",
    "SileroVAD",
    "find_silero_vad_model",
    "is_acoustic_echo",
    "record_agent_spoken",
    "get_recent_spoken_texts",
    "clear_agent_spoken_history",
    "is_using_builtin_speakers",
    "is_headphone_or_headset_active",
    "get_audio_device_profile",
]

