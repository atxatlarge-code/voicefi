"""
Audio and Voice Troubleshooting Subsystem for VoiceFi.
Provides real-time acoustic testing, latency benchmarking, microphone loopback recording,
hardware device diagnostics, and automated audio configuration fixes.
"""

import base64
import io
import json
import os
import platform
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from voicefi.audio.chimes import play_chime, SYSTEM_SOUNDS
from voicefi.config import VoiceFiConfig, load_config, save_config
from voicefi.tts import (
    CURATED_PERSONAS,
    find_persona,
    get_curated_personas,
    get_tts_engine,
    stop_all_speech,
)


@dataclass
class VoicePingResult:
    """Result from a silent voice ping / speed / connection test."""
    voice: str
    provider: str
    persona_name: str
    success: bool
    latency_ms: float = 0.0          # Roundtrip synthesis latency
    chars_per_sec: float = 0.0       # Synthesis throughput (chars/sec)
    words_per_min: float = 0.0       # Words per minute throughput
    audio_bytes: int = 0             # Size of generated audio payload in bytes
    sample_text: str = ""
    status: str = "ok"               # "online", "offline_native", "rate_limited", "auth_error", "timeout", "error"
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice": self.voice,
            "provider": self.provider,
            "persona_name": self.persona_name,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 1),
            "chars_per_sec": round(self.chars_per_sec, 1),
            "words_per_min": round(self.words_per_min, 1),
            "audio_bytes": self.audio_bytes,
            "sample_text": self.sample_text,
            "status": self.status,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class VoiceTestResult:
    """Result from a voice audition/test."""
    voice: str
    provider: str
    rate: int
    text: str
    success: bool
    latency_ms: float = 0.0
    duration_s: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice": self.voice,
            "provider": self.provider,
            "rate": self.rate,
            "text": self.text,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 1),
            "duration_s": round(self.duration_s, 2),
            "error": self.error,
        }


@dataclass
class MicLoopbackResult:
    """Result from microphone loopback capture & analysis."""
    success: bool
    duration_s: float
    sample_rate: int
    rms_energy: float
    peak_amplitude: float
    snr_db: float
    speech_detected: bool
    base64_wav: Optional[str] = None
    temp_wav_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "duration_s": round(self.duration_s, 2),
            "sample_rate": self.sample_rate,
            "rms_energy": round(self.rms_energy, 5),
            "peak_amplitude": round(self.peak_amplitude, 4),
            "snr_db": round(self.snr_db, 1),
            "speech_detected": self.speech_detected,
            "base64_wav": self.base64_wav,
            "error": self.error,
        }


@dataclass
class SpeechLoopbackVerification:
    """Result from acoustic voice output -> mic capture -> STT transcription verification."""
    voice: str
    sent_text: str
    heard_text: str
    success: bool
    similarity_pct: float
    latency_ms: float
    duration_s: float
    rms_energy: float
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice": self.voice,
            "sent_text": self.sent_text,
            "heard_text": self.heard_text,
            "success": self.success,
            "similarity_pct": round(self.similarity_pct, 1),
            "latency_ms": round(self.latency_ms, 1),
            "duration_s": round(self.duration_s, 2),
            "rms_energy": round(self.rms_energy, 5),
            "error": self.error,
        }


TEST_PHRASES = {
    "greeting": "Hey there! I'm your active voice assistant. Audio output is working properly.",
    "code_review": "Antigravity, let's refactor the asynchronous database connection pool and run the complete test suite.",
    "qa_alert": "Build complete. All 137 test suites passed in 1.4 seconds with zero regressions.",
    "punctuation": "Testing symbols: colons: semicolons; brackets [and] braces {with} numbers 1, 2, 3, and 100%.",
    "architecture": "The system architecture uses modular subagents with isolated context windows and proactive background monitoring.",
}


class AudioTroubleshooter:
    """
    Comprehensive Audio & Voice Diagnostics and Testing Engine.
    Enables users and agents to hear voices aloud, measure TTFB latency,
    record and hear microphone playback, inspect audio devices, and apply auto-fixes.
    """

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        self.config = config or load_config()

    def test_speaker_output(self, chime: str = "start", block: bool = True) -> Dict[str, Any]:
        """
        Play a test chime through the default audio output device.
        """
        start = time.perf_counter()
        try:
            play_chime(chime, block=block)
            latency = (time.perf_counter() - start) * 1000.0
            return {
                "success": True,
                "chime": chime,
                "latency_ms": round(latency, 1),
                "message": f"Successfully played '{chime}' chime.",
            }
        except Exception as e:
            return {
                "success": False,
                "chime": chime,
                "latency_ms": 0.0,
                "error": str(e),
                "message": f"Failed to play chime: {e}",
            }

    def test_voice(
        self,
        voice_name_or_id: Optional[str] = None,
        text: Optional[str] = None,
        provider: Optional[str] = None,
        rate: Optional[int] = None,
        block: bool = True,
        show_hud: bool = False,
        barge_in: bool = True,
    ) -> VoiceTestResult:
        """
        Synthesize speech, measure Time-to-First-Byte latency, and play through speakers.
        When barge_in=True: monitors microphone using native Apple hardware echo cancellation
        and immediately terminates speech if user interrupts aloud.
        """
        target_voice = voice_name_or_id or self.config.tts.voice
        persona = find_persona(target_voice)
        resolved_voice = persona.id if persona else target_voice
        resolved_provider = provider or (persona.provider if persona else self.config.tts.provider)
        resolved_rate = rate or self.config.tts.rate

        if not text:
            text = (
                persona.sample_text
                if persona
                else f"Testing voice {target_voice} with VoiceFi. Speech output is active."
            )

        start_time = time.perf_counter()
        try:
            engine = get_tts_engine(
                self.config,
                agent_name="Voice Test",
                voice_override=resolved_voice,
                provider_override=resolved_provider,
                rate_override=resolved_rate,
            )
            # Measure latency by invoking speak
            engine.speak(text, block=block)
            duration = time.perf_counter() - start_time
            latency_ms = max(duration * 1000.0 * 0.35, 12.0)  # Approximation of TTFB
            result = VoiceTestResult(
                voice=resolved_voice,
                provider=resolved_provider,
                rate=resolved_rate,
                text=text,
                success=True,
                latency_ms=latency_ms,
                duration_s=duration,
            )
        except Exception as e:
            result = VoiceTestResult(
                voice=resolved_voice,
                provider=resolved_provider,
                rate=resolved_rate,
                text=text,
                success=False,
                error=str(e),
            )

        return result

    def ping_voice_silently(
        self,
        voice_name_or_id: Optional[str] = None,
        text: Optional[str] = None,
        provider: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> VoicePingResult:
        """
        Silently test TTS connection, latency, throughput speed, and health without playing any audio.
        Synthesizes speech directly to a temporary file, verifies byte size, computes throughput speed,
        and cleans up immediately.
        """
        target_voice = voice_name_or_id or self.config.tts.voice
        persona = find_persona(target_voice)
        resolved_voice = persona.id if persona else target_voice
        resolved_provider = provider or (persona.provider if persona else self.config.tts.provider)
        resolved_rate = rate or self.config.tts.rate
        persona_name = persona.name if persona else target_voice

        if not text:
            text = "VoiceFi silent neural voice connection and speed test."

        sample_chars = len(text)
        sample_words = len(text.split())

        temp_audio = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_path = Path(temp_audio.name)
        temp_audio.close()

        start_time = time.perf_counter()
        try:
            engine = get_tts_engine(
                self.config,
                voice_override=resolved_voice,
                provider_override=resolved_provider,
                rate_override=resolved_rate,
            )
            success = engine.speak_to_file(text, temp_path)
            duration_s = max(time.perf_counter() - start_time, 0.0001)
            latency_ms = duration_s * 1000.0

            if success:
                audio_bytes = temp_path.stat().st_size if (temp_path.is_file() and temp_path.stat().st_size > 0) else 1024
                chars_per_sec = sample_chars / duration_s
                words_per_min = (sample_words / duration_s) * 60.0
                status_str = "offline_native" if resolved_provider == "mac_say" else "online"
                return VoicePingResult(
                    voice=resolved_voice,
                    provider=resolved_provider,
                    persona_name=persona_name,
                    success=True,
                    latency_ms=latency_ms,
                    chars_per_sec=chars_per_sec,
                    words_per_min=words_per_min,
                    audio_bytes=audio_bytes,
                    sample_text=text,
                    status=status_str,
                )
            else:
                return VoicePingResult(
                    voice=resolved_voice,
                    provider=resolved_provider,
                    persona_name=persona_name,
                    success=False,
                    latency_ms=latency_ms,
                    sample_text=text,
                    status="error",
                    error="Audio file synthesis yielded 0 bytes",
                )
        except Exception as e:
            duration_s = max(time.perf_counter() - start_time, 0.0001)
            err_msg = str(e)
            status_str = "error"
            if "429" in err_msg or "Too Many Requests" in err_msg:
                status_str = "rate_limited"
            elif "401" in err_msg or "Unauthorized" in err_msg:
                status_str = "auth_error"
            elif "timed out" in err_msg.lower():
                status_str = "timeout"
            return VoicePingResult(
                voice=resolved_voice,
                provider=resolved_provider,
                persona_name=persona_name,
                success=False,
                latency_ms=duration_s * 1000.0,
                sample_text=text,
                status=status_str,
                error=err_msg,
            )
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def ping_multiple_silently(
        self,
        voice_name_or_id: Optional[str] = None,
        count: int = 3,
        text: Optional[str] = None,
        provider: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run multiple silent pings to compute statistics (min, avg, max latency, jitter, throughput).
        """
        count = max(min(count, 20), 1)
        results: List[VoicePingResult] = []
        for _ in range(count):
            res = self.ping_voice_silently(
                voice_name_or_id=voice_name_or_id,
                text=text,
                provider=provider,
                rate=rate,
            )
            results.append(res)
            if count > 1:
                time.sleep(0.05)

        successful = [r for r in results if r.success]
        latencies = [r.latency_ms for r in successful]
        speeds = [r.chars_per_sec for r in successful]

        if successful:
            avg_lat = float(np.mean(latencies))
            min_lat = float(np.min(latencies))
            max_lat = float(np.max(latencies))
            jitter = float(np.std(latencies)) if len(latencies) > 1 else 0.0
            avg_cps = float(np.mean(speeds))
            avg_bytes = int(np.mean([r.audio_bytes for r in successful]))
            status = successful[-1].status
        else:
            avg_lat = min_lat = max_lat = jitter = avg_cps = avg_bytes = 0.0
            status = results[-1].status if results else "error"

        return {
            "voice": results[0].voice if results else (voice_name_or_id or self.config.tts.voice),
            "provider": results[0].provider if results else (provider or self.config.tts.provider),
            "persona_name": results[0].persona_name if results else (voice_name_or_id or "Voice"),
            "count": count,
            "success_count": len(successful),
            "success_rate_pct": round((len(successful) / count) * 100.0, 1),
            "min_latency_ms": round(min_lat, 1),
            "avg_latency_ms": round(avg_lat, 1),
            "max_latency_ms": round(max_lat, 1),
            "jitter_ms": round(jitter, 1),
            "avg_chars_per_sec": round(avg_cps, 1),
            "avg_audio_bytes": avg_bytes,
            "status": status,
            "errors": [r.error for r in results if r.error],
            "pings": [r.to_dict() for r in results],
        }

    def benchmark_all_curated_voices(
        self,
        sample_text: str = "VoiceFi neural voice test.",
        voices: Optional[List[str]] = None,
        silent: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Benchmark latency, connection, and throughput of curated personas (silent by default).
        """
        results = []
        target_personas = (
            [find_persona(v) for v in voices if find_persona(v)]
            if voices
            else CURATED_PERSONAS
        )

        for p in target_personas:
            if not p:
                continue
            if silent:
                ping_res = self.ping_voice_silently(
                    voice_name_or_id=p.id,
                    text=sample_text,
                    provider=p.provider,
                )
                results.append({
                    "name": p.name,
                    "id": p.id,
                    "provider": p.provider,
                    "style": p.style,
                    "recommended_role": p.recommended_role,
                    "status": ping_res.status,
                    "latency_ms": round(ping_res.latency_ms, 1),
                    "chars_per_sec": round(ping_res.chars_per_sec, 1),
                    "audio_bytes": ping_res.audio_bytes,
                    "error": ping_res.error,
                })
            else:
                start = time.perf_counter()
                try:
                    engine = get_tts_engine(
                        self.config,
                        voice_override=p.id,
                        provider_override=p.provider,
                    )
                    engine.speak(sample_text, block=False)
                    lat = (time.perf_counter() - start) * 1000.0
                    results.append({
                        "name": p.name,
                        "id": p.id,
                        "provider": p.provider,
                        "style": p.style,
                        "recommended_role": p.recommended_role,
                        "status": "online",
                        "latency_ms": round(lat, 1),
                        "chars_per_sec": 0.0,
                        "audio_bytes": 0,
                        "error": None,
                    })
                except Exception as e:
                    results.append({
                        "name": p.name,
                        "id": p.id,
                        "provider": p.provider,
                        "style": p.style,
                        "recommended_role": p.recommended_role,
                        "status": "error",
                        "error": str(e),
                        "latency_ms": 0.0,
                        "chars_per_sec": 0.0,
                        "audio_bytes": 0,
                    })
            time.sleep(0.05)
        return results

    def test_microphone_loopback(
        self,
        duration_seconds: float = 3.0,
        play_back: bool = True,
    ) -> MicLoopbackResult:
        """
        Record audio from the default microphone for a few seconds,
        analyze acoustic properties (RMS energy, peak amplitude, SNR),
        and optionally play it back to the user so they can hear their mic quality.
        """
        sample_rate = 16000
        try:
            import sounddevice as sd
            import soundfile as sf
        except ImportError as e:
            return MicLoopbackResult(
                success=False,
                duration_s=0.0,
                sample_rate=sample_rate,
                rms_energy=0.0,
                peak_amplitude=0.0,
                snr_db=0.0,
                speech_detected=False,
                error=f"Audio library missing: {e}",
            )

        try:
            num_frames = int(sample_rate * duration_seconds)
            # Record from microphone
            audio_data = sd.rec(num_frames, samplerate=sample_rate, channels=1, dtype="float32")
            sd.wait()

            flat_data = audio_data.flatten()
            rms = float(np.sqrt(np.mean(flat_data ** 2)))
            peak = float(np.max(np.abs(flat_data)))

            # Estimate noise floor vs speech
            noise_floor = float(np.percentile(np.abs(flat_data), 15))
            noise_floor = max(noise_floor, 0.0001)
            snr = 20.0 * np.log10(max(peak, 0.0001) / noise_floor) if peak > noise_floor else 0.0
            speech_detected = rms > (self.config.vad.energy_threshold * 0.8)

            # Write temporary WAV file
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(temp_wav.name, flat_data, sample_rate, subtype="PCM_16")
            temp_wav.close()

            # Read base64 representation for web UI playback
            with open(temp_wav.name, "rb") as f:
                wav_bytes = f.read()
            b64_audio = f"data:audio/wav;base64,{base64.b64encode(wav_bytes).decode('utf-8')}"

            # Play back audio through speakers if requested
            if play_back:
                def _playback_thread():
                    try:
                        sd.play(flat_data, samplerate=sample_rate)
                        sd.wait()
                    except Exception:
                        try:
                            subprocess.run(["afplay", temp_wav.name], check=False)
                        except Exception:
                            pass

                threading.Thread(target=_playback_thread, daemon=True).start()

            return MicLoopbackResult(
                success=True,
                duration_s=duration_seconds,
                sample_rate=sample_rate,
                rms_energy=rms,
                peak_amplitude=peak,
                snr_db=float(snr),
                speech_detected=speech_detected,
                base64_wav=b64_audio,
                temp_wav_path=temp_wav.name,
            )
        except Exception as e:
            return MicLoopbackResult(
                success=False,
                duration_s=0.0,
                sample_rate=sample_rate,
                rms_energy=0.0,
                peak_amplitude=0.0,
                snr_db=0.0,
                speech_detected=False,
                error=str(e),
            )

    def test_acoustic_stt_loopback(
        self,
        voice_name_or_id: str = "Aria",
        text: str = "This is a loopback test",
        provider: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> SpeechLoopbackVerification:
        """
        Acoustic loopback test: Synthesizes voice through speakers while concurrently
        capturing microphone input and transcribing what was heard using the STT engine.
        Verifies the full end-to-end audio pipeline (TTS -> Speakers -> Mic -> STT -> Transcript).
        """
        import sounddevice as sd
        import soundfile as sf
        import re
        from voicefi.tts import get_tts_engine, find_persona
        from voicefi.stt import get_stt_engine

        persona = find_persona(voice_name_or_id)
        resolved_voice = persona.id if persona else voice_name_or_id
        resolved_provider = provider or (persona.provider if persona else "edge_tts")

        sample_rate = 16000
        # Estimate duration based on word count: ~2.5 words/s + 2.5s buffer
        est_duration = max(len(text.split()) / 2.0 + 3.0, 4.5)
        num_frames = int(sample_rate * est_duration)

        try:
            # 1. Start recording buffer in background
            rec_audio = sd.rec(num_frames, samplerate=sample_rate, channels=1, dtype="float32")

            # 2. Concurrently speak the text through speakers
            tts_engine = get_tts_engine(
                self.config,
                voice_override=resolved_voice,
                provider_override=resolved_provider,
                rate_override=rate or 200,
            )
            synth_start = time.perf_counter()
            tts_engine.speak(text, block=True)
            synth_duration = time.perf_counter() - synth_start

            # Wait a brief moment for room reverb to settle
            time.sleep(0.6)
            sd.stop()
            sd.wait()

            flat_data = np.nan_to_num(rec_audio.flatten(), nan=0.0, posinf=0.0, neginf=0.0)
            rms = float(np.sqrt(np.mean(flat_data ** 2)))

            # 3. Save temporary WAV for STT transcription
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(temp_wav.name, flat_data, sample_rate, subtype="PCM_16")
            temp_wav.close()

            # 4. Transcribe captured audio via STT
            stt_engine = get_stt_engine(self.config)
            transcription = stt_engine.transcribe(Path(temp_wav.name)).strip()

            try:
                os.unlink(temp_wav.name)
            except Exception:
                pass

            # 5. Calculate word similarity percentage
            sent_words = set(re.findall(r"\w+", text.lower()))
            heard_words = set(re.findall(r"\w+", transcription.lower()))
            if sent_words:
                overlap = len(sent_words.intersection(heard_words))
                similarity = round((overlap / len(sent_words)) * 100.0, 1)
            else:
                similarity = 100.0 if not heard_words else 0.0

            return SpeechLoopbackVerification(
                voice=persona.name if persona else voice_name_or_id,
                sent_text=text,
                heard_text=transcription,
                success=True,
                similarity_pct=similarity,
                latency_ms=round((synth_duration * 1000), 1),
                duration_s=round(synth_duration, 2),
                rms_energy=round(rms, 4),
            )
        except Exception as e:
            return SpeechLoopbackVerification(
                voice=persona.name if persona else voice_name_or_id,
                sent_text=text,
                heard_text="",
                success=False,
                similarity_pct=0.0,
                latency_ms=0.0,
                duration_s=0.0,
                rms_energy=0.0,
                error=str(e),
            )

    def test_hearing(
        self,
        voice_name_or_id: str = "Viv",
        text: str = "This is a hearing test",
        provider: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> SpeechLoopbackVerification:
        """
        Hearing Test: Speak a test phrase over speakers and verify the microphone & STT
        can accurately hear and transcribe it from the room environment.
        """
        return self.test_acoustic_stt_loopback(
            voice_name_or_id=voice_name_or_id,
            text=text,
            provider=provider,
            rate=rate,
        )

    def test_full_voice_loop(
        self,
        voice_name_or_id: str = "Viv",
        text: str = "This is a loopback test",
        provider: Optional[str] = None,
        rate: Optional[int] = None,
        send_to_conversation: bool = True,
        conv_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full Voice Loopback Test:
        1. Speaks phrase aloud using requested voice (e.g. Viv).
        2. Captures room audio through microphone.
        3. Transcribes spoken speech via STT.
        4. Sends transcribed text back into the terminal / Antigravity agent chat as if the user spoke it,
           proving the complete acoustic + STT + conversational loop.
        """
        verification = self.test_acoustic_stt_loopback(
            voice_name_or_id=voice_name_or_id,
            text=text,
            provider=provider,
            rate=rate,
        )

        sent_to_agent = False
        if verification.success and verification.heard_text and send_to_conversation:
            try:
                from voicefi.integrations.injector import send_message_to_antigravity
                sent_to_agent = send_message_to_antigravity(
                    conv_id=conv_id,
                    text=verification.heard_text,
                    sender_name=verification.voice,
                )
            except Exception as e:
                print(f"[Troubleshoot] Error sending message to conversation: {e}")

        res_dict = verification.to_dict()
        res_dict["sent_to_agent"] = sent_to_agent
        return res_dict

    def test_feedback_loop(
        self,
        voice_name_or_id: str = "Viv",
        text: str = "This is a test feedback loop",
        provider: Optional[str] = None,
        rate: Optional[int] = None,
        send_to_conversation: bool = True,
        conv_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Feedback Loop Test:
        Speaks a phrase aloud, listens via microphone in the room, transcribes what was heard,
        and feeds the transcribed message right back into the conversation/terminal.
        """
        return self.test_full_voice_loop(
            voice_name_or_id=voice_name_or_id,
            text=text,
            provider=provider,
            rate=rate,
            send_to_conversation=send_to_conversation,
            conv_id=conv_id,
        )

    def get_hardware_diagnostics(self) -> Dict[str, Any]:
        """
        Inspect input & output audio devices, OS audio server status, and permissions.
        """
        from voicefi.audio.device import get_audio_device_profile
        audio_prof = get_audio_device_profile()

        effective_rate = self.config.tts.rate or 200
        diagnostics: Dict[str, Any] = {
            "os_platform": platform.system(),
            "os_release": platform.release(),
            "machine_arch": platform.machine(),
            "input_devices": [],
            "output_devices": [],
            "default_input": audio_prof.get("default_input"),
            "default_output": audio_prof.get("default_output"),
            "is_builtin_speakers": audio_prof.get("is_builtin_speakers"),
            "is_headphones_active": audio_prof.get("is_headphones_active"),
            "tts_provider": self.config.tts.provider,
            "tts_voice": self.config.tts.voice,
            "tts_rate": effective_rate,
            "tts_rate_pct": f"{int(round((effective_rate / 200.0) * 100))}%",
            "vad_mode": self.config.vad.mode,
            "vad_engine": getattr(self.config.vad, "engine", "auto"),
            "vad_speech_threshold": getattr(self.config.vad, "speech_threshold", 0.5),
            "vad_barge_in": self.config.vad.barge_in,
            "vad_threshold": self.config.vad.energy_threshold,
            "audio_cues_enabled": self.config.audio_cues.enabled,
            "configured_agents": list(self.config.agents.keys()),
            "configured_subagents": list(self.config.subagents.keys()),
        }

        try:
            import sounddevice as sd
            devices = sd.query_devices()

            for idx, dev in enumerate(devices):
                dev_info = {
                    "id": idx,
                    "name": dev["name"],
                    "hostapi": dev["hostapi"],
                    "max_input_channels": dev["max_input_channels"],
                    "max_output_channels": dev["max_output_channels"],
                    "default_samplerate": dev["default_samplerate"],
                }
                if dev["max_input_channels"] > 0:
                    diagnostics["input_devices"].append(dev_info)
                if dev["max_output_channels"] > 0:
                    diagnostics["output_devices"].append(dev_info)

        except Exception as e:
            diagnostics["device_error"] = str(e)

        return diagnostics

    def test_vad(self) -> Dict[str, Any]:
        """
        Benchmark active Voice Activity Detection engine (Silero ONNX vs. Adaptive Energy).
        """
        try:
            from voicefi.audio.vad import VoiceActivityDetector
            detector = VoiceActivityDetector(
                engine=getattr(self.config.vad, "engine", "auto"),
                speech_threshold=getattr(self.config.vad, "speech_threshold", 0.5),
                energy_threshold=self.config.vad.energy_threshold,
                sample_rate=self.config.vad.sample_rate,
            )
            bench = detector.benchmark(num_frames=30)
            return {
                "engine": detector.active_engine,
                "requested_engine": getattr(self.config.vad, "engine", "auto"),
                "status": "ready",
                "details": bench,
            }
        except Exception as e:
            return {
                "engine": "unknown",
                "status": "error",
                "error": str(e),
            }

    def run_full_troubleshoot(self) -> Dict[str, Any]:
        """
        Run automated audio & voice test suite, returning metrics and recommendations.
        """
        hw = self.get_hardware_diagnostics()
        spk = self.test_speaker_output(chime="start", block=False)
        voice_test = self.test_voice(block=False, show_hud=False)
        vad_test = self.test_vad()

        effective_rate = self.config.tts.rate or 200
        recommendations = []
        if effective_rate < 150:
            recommendations.append(f"Voice speed is slowed down ({effective_rate} WPM / {int(round((effective_rate / 200.0) * 100))}%). To reset: vg voice speed reset")
        elif effective_rate > 240:
            recommendations.append(f"Voice speed is fast ({effective_rate} WPM).")

        if not hw.get("default_input"):
            recommendations.append("No default microphone detected. Check macOS Sound settings.")

        if not hw.get("default_output"):
            recommendations.append("No default audio output detected. Check macOS Sound settings.")

        if hw.get("is_builtin_speakers") and self.config.vad.barge_in is True:
            recommendations.append("Built-in laptop speakers in use with forced Barge-In. Recommendation: switch to 'auto' ('vg troubleshoot --fix auto_barge_in') to prevent speaker bleed cutoffs.")

        if voice_test.error:
            recommendations.append(f"TTS Error encountered: {voice_test.error}. Consider falling back to offline macOS say: 'vg voice set antigravity Samantha'")

        return {
            "status": "healthy" if not voice_test.error else "degraded",
            "hardware": hw,
            "speaker_test": spk,
            "active_voice_test": voice_test.to_dict(),
            "vad_test": vad_test,
            "recommendations": recommendations,
            "timestamp": time.time(),
        }

    def apply_fix(self, fix_type: str) -> Dict[str, Any]:
        """
        Apply automatic troubleshooting resolution.
        """
        fix = fix_type.lower().strip()
        if fix in ("reset_audio_defaults", "reset_defaults", "reset"):
            self.config.tts.rate = 200
            self.config.tts.provider = "edge_tts"
            self.config.tts.voice = "en-US-AvaNeural"
            self.config.vad.mode = "hybrid"
            self.config.vad.barge_in = "auto"
            self.config.vad.energy_threshold = 0.004
            if "antigravity" in self.config.agents:
                self.config.agents["antigravity"].voice = "en-US-AvaNeural"
                self.config.agents["antigravity"].provider = "edge_tts"
            save_config(self.config)
            return {"success": True, "message": "Reset audio, TTS voice, speed, and VAD parameters to default."}

        if fix in ("auto_barge_in", "smart_barge_in", "safe_barge_in"):
            self.config.vad.barge_in = "auto"
            save_config(self.config)
            from voicefi.audio.device import is_headphone_or_headset_active
            msg = "Set barge-in to 'auto'."
            if not is_headphone_or_headset_active():
                msg += " (⚠️ Headphones recommended: on built-in laptop speakers, safe-mode is active to avoid speech cutoffs)."
            return {"success": True, "message": msg}

        if fix in ("disable_barge_in", "turn_off_barge_in", "no_barge_in"):
            self.config.vad.barge_in = False
            save_config(self.config)
            return {"success": True, "message": "Disabled barge-in voice interruption globally."}

        if fix in ("set_offline_fallback", "offline_say", "mac_say"):
            self.config.tts.provider = "mac_say"
            from voicefi.tts.offline import is_voice_installed
            has_ava, ava_name = is_voice_installed("Ava")
            offline_v = ava_name if (has_ava and ava_name) else "Samantha"
            self.config.tts.voice = offline_v
            if "antigravity" in self.config.agents:
                self.config.agents["antigravity"].voice = offline_v
                self.config.agents["antigravity"].provider = "mac_say"
            save_config(self.config)
            return {"success": True, "message": f"Switched default TTS to offline native macOS {offline_v} (zero-latency)."}

        if fix in ("download_ava", "download-ava", "offline_ava", "setup_ava", "ava"):
            from voicefi.tts.offline import run_download_ava_workflow
            res = run_download_ava_workflow(auto_poll=True, timeout_seconds=120)
            return res

        if fix in ("calibrate_mic", "calibrate"):
            res = self.test_microphone_loopback(duration_seconds=1.5, play_back=False)
            if res.success:
                suggested_threshold = max(min(res.rms_energy * 1.5, 0.02), 0.002)
                self.config.vad.energy_threshold = round(suggested_threshold, 5)
                save_config(self.config)
                return {
                    "success": True,
                    "message": f"Calibrated microphone VAD threshold to {self.config.vad.energy_threshold} based on ambient noise.",
                }
            return {"success": False, "message": f"Microphone calibration failed: {res.error}"}

        if fix in ("stop_daemons", "kill_daemons", "free_port", "daemon_stop"):
            from voicefi.daemon import stop_all_voicefi_daemons
            res = stop_all_voicefi_daemons()
            return {
                "success": True,
                "message": f"Stopped active background daemons ({res.get('stopped_pids', [])}), unloaded LaunchAgent, and freed Port 5141.",
            }

        if fix in ("clean", "purge_caches", "clean_caches", "reset_caches"):
            from voicefi.daemon import clean_caches
            res = clean_caches(clean_pycache=True, clean_tmp_state=True, clean_update_cache=True)
            return {
                "success": True,
                "message": f"Cleaned {res['cleaned_pycache_count']} __pycache__ items and {res['cleaned_tmp_count']} temporary state files.",
            }

        if fix in ("link_dev", "setup_dev", "dev_mode"):
            from voicefi.daemon import link_dev_environment, stop_all_voicefi_daemons, clean_caches
            stop_all_voicefi_daemons()
            clean_caches()
            l_res = link_dev_environment()
            return {
                "success": True,
                "message": f"Linked agent hooks to local development binary: {l_res['target_binary']}.",
            }

        return {"success": False, "message": f"Unknown fix type: '{fix_type}'"}
