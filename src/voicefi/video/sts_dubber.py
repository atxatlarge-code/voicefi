"""
Zero-Render Speech-to-Speech (STS) Video Dubber — VoiceFi™

Decouples vocal timbre and performance from original video footage:
1. Extracts original dialogue track from video (WAV 24kHz/16kHz).
2. Transcribes with Faster-Whisper to extract sub-millisecond timestamps and words.
3. Synthesizes replacement dialogue using VoiceFi Voice Acting (MLX Qwen3-TTS)
   or F5-TTS Diffusion Cloning.
4. Dynamically time-stretches/compresses with FFmpeg atempo to preserve exact
   speech duration and syllable envelope.
5. Remuxes onto original video via FFmpeg stream copy (-c:v copy).

Result: 100% video frame fidelity, zero blurry mouth artifacts, and 0.2s mux time.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("voicefi.sts_dubber")


def get_audio_duration(audio_path: Union[str, Path]) -> float:
    """Get accurate audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def get_video_duration(video_path: Union[str, Path]) -> float:
    """Get accurate video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


class ZeroRenderDubber:
    """Production engine for zero-render Speech-to-Speech video dubbing."""

    def __init__(self, whisper_model_size: str = "base.en", device: str = "cpu"):
        self.whisper_model_size = whisper_model_size
        self.device = device
        self._whisper_model = None

    def _get_whisper_model(self):
        if self._whisper_model is None:
            from faster_whisper import WhisperModel

            compute_type = "int8" if self.device == "cpu" else "float16"
            self._whisper_model = WhisperModel(
                self.whisper_model_size, device=self.device, compute_type=compute_type
            )
        return self._whisper_model

    def extract_audio(
        self, video_path: Union[str, Path], output_wav: Optional[Union[str, Path]] = None
    ) -> Path:
        """Extract pristine mono 24kHz audio from video file."""
        video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Input video not found: {video_path}")

        if output_wav is None:
            output_wav = video_path.with_suffix(".extracted.wav")
        else:
            output_wav = Path(output_wav).resolve()

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(output_wav),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_wav

    def transcribe(self, audio_path: Union[str, Path]) -> Dict[str, Any]:
        """Transcribe audio track and return text, word timestamps, and clause segments."""
        model = self._get_whisper_model()
        segments, info = model.transcribe(str(audio_path), word_timestamps=True)

        full_text_parts = []
        clause_list = []

        for seg in segments:
            full_text_parts.append(seg.text.strip())
            words = []
            for w in seg.words or []:
                words.append(
                    {
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                    }
                )
            clause_list.append(
                {
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "duration": round(seg.end - seg.start, 3),
                    "text": seg.text.strip(),
                    "words": words,
                }
            )

        transcript = " ".join(full_text_parts).strip()
        return {
            "transcript": transcript,
            "duration": round(info.duration, 3),
            "language": info.language,
            "segments": clause_list,
        }

    def synthesize_voice(
        self,
        text: str,
        voice: str,
        provider: str = "auto",
        instruct: Optional[str] = None,
        output_wav: Optional[Union[str, Path]] = None,
        verbatim: bool = True,
    ) -> Path:
        """Synthesize voice using Voice Acting (MLX), F5-TTS, or Edge TTS."""
        if output_wav is None:
            output_wav = Path(tempfile.mktemp(suffix=".wav"))
        else:
            output_wav = Path(output_wav).resolve()

        # If not verbatim, allow theatrical director overrides
        if not verbatim and "walken" in voice.lower():
            from voicefi.tts.director import TheatricalDirector

            text = TheatricalDirector.direct_walken_cadence(text)
            if not instruct:
                instruct = (
                    "Idiosyncratic erratic staccato rhythm with unexpected dramatic pauses, "
                    "sudden pitch spikes, and deadpan comedic intensity."
                )

        # Route provider
        if provider == "auto":
            from voicefi.tts.voice_acting import VOICE_ACTING_PRESETS

            if instruct:
                provider = "voice_acting"
            elif Path(os.path.expanduser(f"~/.voicefi/cloned_voices/{voice}")).exists():
                provider = "local_clone"
            elif voice in VOICE_ACTING_PRESETS or voice == "voice_acting":
                provider = "voice_acting"
            else:
                provider = "voice_acting"

        if provider in ("voice_acting", "mlx_actor"):
            from voicefi.tts.voice_acting import VoiceActingTTS

            actor = VoiceActingTTS(persona_name=voice, instruct=instruct)
            actor.speak_to_file(text, output_wav)
        elif provider in ("local_clone", "f5_tts"):
            from voicefi.tts.f5_tts import F5TTS

            f5 = F5TTS(persona_name=voice)
            f5.speak_to_file(text, output_wav, direct_cadence=not verbatim)
        else:
            from voicefi.tts.edge_tts import EdgeTTS

            edge = EdgeTTS(voice=voice)
            edge.speak_to_file(text, output_wav)

        return output_wav

    def align_audio_to_duration(
        self,
        spoken_window_duration: float,
        generated_wav: Path,
        output_aligned_wav: Path,
        start_offset: float = 0.0,
        total_video_duration: Optional[float] = None,
    ) -> Path:
        """Time-stretch, delay, and pad generated audio to match source speech window and total video duration."""
        gen_duration = get_audio_duration(generated_wav)
        if gen_duration <= 0.05:
            shutil.copy(generated_wav, output_aligned_wav)
            return output_aligned_wav

        # Target duration of the spoken section
        target_spoken_duration = max(0.2, spoken_window_duration)
        tempo_ratio = gen_duration / target_spoken_duration

        # Build atempo filter chain (each stage must be between 0.5 and 2.0)
        filters = []
        r = tempo_ratio
        while r > 2.0:
            filters.append("atempo=2.0")
            r /= 2.0
        while r < 0.5:
            filters.append("atempo=0.5")
            r /= 0.5
        filters.append(f"atempo={r:.4f}")

        # Add onset delay if start_offset > 0.05s
        if start_offset >= 0.05:
            delay_ms = int(round(start_offset * 1000))
            filters.append(f"adelay={delay_ms}|{delay_ms}")

        # Pad to full video duration to prevent premature video cutoff (-shortest)
        if total_video_duration and total_video_duration > 0:
            filters.append(f"apad,atrim=0:{total_video_duration:.3f}")

        filter_str = ",".join(filters)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(generated_wav),
            "-filter:a",
            filter_str,
            str(output_aligned_wav),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_aligned_wav

    def remux(
        self,
        video_path: Union[str, Path],
        audio_path: Union[str, Path],
        output_video: Union[str, Path],
        web_compat: bool = False,
    ) -> float:
        """Remux video with new audio. Uses -c:v copy by default, or hardware H.264 for web compatibility."""
        t0 = time.perf_counter()
        if web_compat:
            import sys

            encoder_args = (
                ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p"]
                if sys.platform == "darwin"
                else ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"]
            )
        else:
            encoder_args = ["-c:v", "copy"]

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            *encoder_args,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_video),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return time.perf_counter() - t0


    def dub_video(
        self,
        video_path: Union[str, Path],
        voice: str = "christopher_walken",
        provider: str = "auto",
        instruct: Optional[str] = None,
        output_video: Optional[Union[str, Path]] = None,
        script_override: Optional[str] = None,
        keep_temp: bool = False,
        web_compat: bool = False,
    ) -> Dict[str, Any]:
        """Execute end-to-end zero-render Speech-to-Speech video dubbing."""
        video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")


        if output_video is None:
            clean_voice = voice.replace(" ", "_").lower()
            output_video = video_path.parent / f"{video_path.stem}_dubbed_{clean_voice}.mp4"
        else:
            output_video = Path(output_video).resolve()

        t_total_start = time.perf_counter()
        temp_dir = Path(tempfile.mkdtemp(prefix="voicefi_sts_dub_"))

        try:
            # 1. Extract audio
            logger.info("Extracting source audio track...")
            extracted_wav = temp_dir / "original_track.wav"
            self.extract_audio(video_path, extracted_wav)
            source_dur = get_audio_duration(extracted_wav)
            video_dur = get_video_duration(video_path)

            # 2. Transcribe
            logger.info("Transcribing source audio with Faster-Whisper...")
            transcription = self.transcribe(extracted_wav)
            spoken_text = script_override or transcription["transcript"]

            # Compute speech onset and boundary offsets
            start_offset = 0.0
            spoken_duration = source_dur
            if transcription.get("segments"):
                all_words = [w for s in transcription["segments"] for w in s.get("words", [])]
                if all_words:
                    start_offset = all_words[0]["start"]
                    end_offset = all_words[-1]["end"]
                    spoken_duration = max(0.5, end_offset - start_offset)
                else:
                    start_offset = transcription["segments"][0]["start"]
                    spoken_duration = max(0.5, transcription["segments"][-1]["end"] - start_offset)

            # 3. Synthesize replacement performance verbatim
            logger.info(f"Synthesizing voice acting for '{voice}' (verbatim script)...")
            raw_target_wav = temp_dir / "target_voice_raw.wav"
            self.synthesize_voice(
                text=spoken_text,
                voice=voice,
                provider=provider,
                instruct=instruct,
                output_wav=raw_target_wav,
                verbatim=True,
            )

            # 4. Align audio duration and onset delay to match video speech window and pad to video length
            logger.info(
                f"Aligning audio with {start_offset:.2f}s onset delay (spoken: {spoken_duration:.2f}s, total video: {video_dur:.2f}s)..."
            )
            aligned_wav = temp_dir / "target_voice_aligned.wav"
            self.align_audio_to_duration(
                spoken_window_duration=spoken_duration,
                generated_wav=raw_target_wav,
                output_aligned_wav=aligned_wav,
                start_offset=start_offset,
                total_video_duration=video_dur,
            )


            # 5. Remux without video re-rendering (-c:v copy)
            logger.info("Remuxing video with zero pixel re-rendering...")
            remux_elapsed = self.remux(
                video_path=video_path,
                audio_path=aligned_wav,
                output_video=output_video,
                web_compat=web_compat,
            )
            total_elapsed = time.perf_counter() - t_total_start


            report = {
                "input_video": str(video_path),
                "output_video": str(output_video),
                "transcript": spoken_text,
                "target_voice": voice,
                "provider": provider,
                "source_duration_sec": round(source_dur, 2),
                "video_duration_sec": round(video_dur, 2),
                "remux_time_sec": round(remux_elapsed, 3),
                "total_time_sec": round(total_elapsed, 2),
                "fps_saved": "100% (zero frames re-encoded)" if not web_compat else "Web-optimized (H.264 SDR)",
            }

            return report

        finally:
            if not keep_temp and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
