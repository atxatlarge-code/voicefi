"""
Companion route handlers for VoiceFi Studio (audio recording, presets, trimming, DSP effects, transcription, and social reels).
"""

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

from aiohttp import web

from voicefi.companion.handlers.audio import _resolve_stt_engine

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
RECORDINGS_DIR = Path.home() / ".voicefi" / "recordings"


class StudioHandlersMixin:
    """Mixin containing VoiceFi Studio recording, FX DSP processing, and reel generation endpoints."""

    async def handle_studio_presets(self, request: web.Request) -> web.Response:
        """Return list of available voice FX presets, formats, and SFX cues."""
        from voicefi.audio.effects import VoiceFXEngine
        from voicefi.video.reel_builder import FORMAT_PRESETS, TYPOGRAPHY_PRESETS
        from voicefi.audio.sfx import list_available_sfx

        return web.json_response(
            {
                "presets": VoiceFXEngine.list_presets(),
                "formats": list(FORMAT_PRESETS.keys()),
                "format_details": FORMAT_PRESETS,
                "typography": list(TYPOGRAPHY_PRESETS.keys()),
                "available_sfx": list_available_sfx(),
            }
        )

    async def handle_studio_recordings(self, request: web.Request) -> web.Response:
        """List all recordings, uploaded audio files, voice memos, and master samples."""
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        from voicefi.audio.effects import VoiceFXEngine

        items = []
        # 1. Scan ~/.voicefi/recordings/
        for p in sorted(RECORDINGS_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix.lower() in (
                ".wav",
                ".mp3",
                ".m4a",
                ".ogg",
                ".webm",
                ".flac",
                ".aac",
            ):
                try:
                    info = VoiceFXEngine.get_audio_info(p)
                    items.append(
                        {
                            "id": p.name,
                            "filename": p.name,
                            "path": str(p),
                            "duration": info["duration"],
                            "size_formatted": info["size_formatted"],
                            "size_bytes": info["size_bytes"],
                            "sample_rate": info["sample_rate"],
                            "peaks": info["peaks"],
                            "url": f"/api/studio/recording/{p.name}",
                            "created_at": time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)
                            ),
                            "is_fx_master": "_fx_" in p.name or "_master" in p.name,
                            "source": "recording",
                        }
                    )
                except Exception:
                    pass

        # 2. Check static/downloads for sample audio tracks
        downloads_dir = STATIC_DIR / "downloads"
        if downloads_dir.is_dir():
            for p in sorted(
                downloads_dir.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True
            ):
                if p.is_file():
                    try:
                        info = VoiceFXEngine.get_audio_info(p)
                        items.append(
                            {
                                "id": f"download_{p.name}",
                                "filename": p.name,
                                "path": str(p),
                                "duration": info["duration"],
                                "size_formatted": info["size_formatted"],
                                "size_bytes": info["size_bytes"],
                                "sample_rate": info["sample_rate"],
                                "peaks": info["peaks"],
                                "url": f"/downloads/{p.name}",
                                "created_at": time.strftime(
                                    "%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)
                                ),
                                "is_fx_master": True,
                                "source": "downloads_sample",
                            }
                        )
                    except Exception:
                        pass

        return web.json_response(
            {
                "recordings": items,
                "count": len(items),
            }
        )

    async def handle_studio_recording_stream(self, request: web.Request) -> web.Response:
        """Stream an audio recording with HTTP range request support for waveform and browser playback."""
        rec_id = request.match_info.get("rec_id", "")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        target = RECORDINGS_DIR / rec_id
        if not target.is_file() or not target.resolve().is_relative_to(RECORDINGS_DIR.resolve()):
            return web.Response(status=404, text="Recording not found")

        ext = target.suffix.lower()
        content_type = "audio/wav"
        if ext == ".mp3":
            content_type = "audio/mpeg"
        elif ext in (".m4a", ".aac"):
            content_type = "audio/mp4"
        elif ext == ".ogg":
            content_type = "audio/ogg"
        elif ext == ".webm":
            content_type = "audio/webm"

        return web.FileResponse(
            target,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Type": content_type,
                "Access-Control-Allow-Origin": "*",
            },
        )

    async def handle_studio_upload(self, request: web.Request) -> web.Response:
        """Handle audio file upload from companion app or desktop."""
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        from voicefi.audio.effects import VoiceFXEngine

        raw_bytes = None
        filename = None

        try:
            if request.content_type.startswith("multipart/"):
                post_data = await request.post()
                field = post_data.get("file") or post_data.get("audio")
                if field is not None:
                    filename = (
                        getattr(field, "filename", None) or f"upload_{int(time.time() * 1000)}.wav"
                    )
                    if hasattr(field, "file"):
                        raw_bytes = field.file.read()
                    elif isinstance(field, (bytes, bytearray)):
                        raw_bytes = bytes(field)
            else:
                try:
                    data = await request.json()
                except Exception:
                    data = {}
                b64 = data.get("audio_base64") or data.get("audio") or ""
                filename = data.get("filename") or f"upload_{int(time.time() * 1000)}.wav"
                if b64:
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                    import base64

                    raw_bytes = base64.b64decode(b64)

            if not raw_bytes:
                return web.json_response(
                    {"error": "No audio data received", "status": "error"}, status=400
                )

            p_raw = Path(filename)
            stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", p_raw.stem)
            ext = p_raw.suffix.lower() if p_raw.suffix else ".wav"
            if ext not in (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".aac"):
                ext = ".wav"

            target_filename = f"{stem}_{int(time.time() * 1000)}{ext}"
            target_path = RECORDINGS_DIR / target_filename
            target_path.write_bytes(raw_bytes)

            # Convert webm to wav if needed for uniform processing
            if ext == ".webm":
                wav_path = target_path.with_suffix(".wav")
                try:
                    from voicefi.audio.effects import _get_bin

                    subprocess.run(
                        [_get_bin("ffmpeg"), "-y", "-i", str(target_path), str(wav_path)],
                        check=True,
                        capture_output=True,
                    )
                    if wav_path.is_file():
                        target_path.unlink(missing_ok=True)
                        target_path = wav_path
                        target_filename = target_path.name
                except Exception:
                    pass

            info = VoiceFXEngine.get_audio_info(target_path)
            return web.json_response(
                {
                    "success": True,
                    "id": target_filename,
                    "filename": target_filename,
                    "url": f"/api/studio/recording/{target_filename}",
                    "info": info,
                }
            )
        except Exception as e:
            logger.exception(f"Studio upload error: {e}")
            return web.json_response({"error": str(e), "success": False}, status=500)

    async def handle_studio_record(self, request: web.Request) -> web.Response:
        """Handle direct voice recording blob from browser MediaRecorder."""
        return await self.handle_studio_upload(request)

    async def handle_studio_trim(self, request: web.Request) -> web.Response:
        """Trim audio file between start_sec and end_sec."""
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        from voicefi.audio.effects import VoiceFXEngine

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON payload"}, status=400)

        rec_id = data.get("recording_id")
        if not rec_id:
            return web.json_response({"error": "Missing recording_id"}, status=400)

        in_file = RECORDINGS_DIR / rec_id
        if not in_file.is_file() and rec_id.startswith("download_"):
            in_file = STATIC_DIR / "downloads" / rec_id.replace("download_", "")
        if not in_file.is_file():
            in_file = STATIC_DIR / "downloads" / rec_id
        if not in_file.is_file():
            return web.json_response({"error": f"Audio file not found: {rec_id}"}, status=404)

        start_sec = float(data.get("start_sec", 0.0))
        end_sec = data.get("end_sec")
        if end_sec is not None and str(end_sec).strip():
            end_sec = float(end_sec)
        else:
            end_sec = None

        stem = in_file.stem
        stem = re.sub(r"_trimmed_\d+", "", stem)
        out_filename = f"{stem}_trimmed_{int(time.time() * 1000)}.mp3"
        out_file = RECORDINGS_DIR / out_filename

        try:
            VoiceFXEngine.trim_audio(
                input_audio=in_file, output_audio=out_file, start_sec=start_sec, end_sec=end_sec
            )
            info = VoiceFXEngine.get_audio_info(out_file)
            return web.json_response(
                {
                    "success": True,
                    "trimmed_id": out_filename,
                    "filename": out_filename,
                    "url": f"/api/studio/recording/{out_filename}",
                    "duration": info["duration"],
                    "info": info,
                }
            )
        except Exception as e:
            logger.exception(f"Studio trim error: {e}")
            return web.json_response(
                {"error": f"Trim failed: {str(e)}", "success": False}, status=500
            )

    async def handle_studio_apply_fx(self, request: web.Request) -> web.Response:
        """Apply selected voice FX preset (or custom DSP sliders) and SFX overlays."""
        data = await request.json()
        rec_id = data.get("recording_id") or data.get("id") or ""
        preset = data.get("preset", "radio_announcer")
        custom_params = data.get("custom_params")
        sfx_cues = data.get("sfx_cues", [])
        bg_music = data.get("bg_music")
        bg_volume = float(data.get("bg_volume", 0.15))
        out_ext = data.get("format", "mp3").lower().lstrip(".")
        if out_ext not in ("mp3", "wav", "m4a"):
            out_ext = "mp3"

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        in_path = RECORDINGS_DIR / rec_id
        if not in_path.is_file() and rec_id.startswith("download_"):
            in_path = STATIC_DIR / "downloads" / rec_id.replace("download_", "")

        if not in_path.is_file():
            return web.json_response(
                {"error": f"Recording not found: {rec_id}", "status": "error"}, status=404
            )

        from voicefi.audio.effects import VoiceFXEngine

        stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", in_path.stem)
        fx_slug = preset if preset else "custom"
        ts = int(time.time() * 1000)
        out_filename = f"{stem}_fx_{fx_slug}_{ts}.{out_ext}"
        out_path = RECORDINGS_DIR / out_filename

        VoiceFXEngine.apply_effect(
            input_audio=in_path,
            output_audio=out_path,
            preset=preset,
            custom_params=custom_params,
            sfx_cues=sfx_cues,
            bg_music_path=bg_music,
            bg_music_volume=bg_volume,
            normalize_loudness=True,
        )

        info = VoiceFXEngine.get_audio_info(out_path)
        return web.json_response(
            {
                "success": True,
                "master_id": out_filename,
                "filename": out_filename,
                "url": f"/api/studio/recording/{out_filename}",
                "preset": preset,
                "info": info,
            }
        )

    async def handle_studio_transcribe(self, request: web.Request) -> web.Response:
        """Transcribe an audio recording and auto-generate suggested slide cards."""
        data = await request.json()
        rec_id = data.get("recording_id") or data.get("id") or ""
        speaker = data.get("speaker", "Radio Host")

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        in_path = RECORDINGS_DIR / rec_id
        if not in_path.is_file() and rec_id.startswith("download_"):
            in_path = STATIC_DIR / "downloads" / rec_id.replace("download_", "")

        if not in_path.is_file():
            return web.json_response(
                {"error": f"Audio file not found: {rec_id}", "status": "error"}, status=404
            )

        from voicefi.audio.effects import VoiceFXEngine
        from voicefi.video.reel_builder import ReelBuilder

        info = VoiceFXEngine.get_audio_info(in_path)
        stt = _resolve_stt_engine(self.config)
        transcript = stt.transcribe(in_path)
        try:
            from voicefi.tts.normalizer import collapse_repetitive_artifacts

            transcript = collapse_repetitive_artifacts(transcript)
        except Exception:
            pass

        suggested_slides = ReelBuilder.auto_generate_slides_from_text(
            transcript=transcript, total_duration=info["duration"], speaker=speaker
        )

        return web.json_response(
            {
                "transcript": transcript,
                "duration": info["duration"],
                "suggested_slides": suggested_slides,
            }
        )

    async def handle_studio_generate_reel(self, request: web.Request) -> web.Response:
        """Compile a multi-format social video reel from transformed master audio and slides."""
        data = await request.json()
        rec_id = data.get("recording_id") or data.get("id") or ""
        slides = data.get("slides")
        transcript = data.get("transcript")
        format_type = data.get("format", "9:16")
        preset_name = data.get("preset", "classic_ai")
        font_multiplier = float(data.get("font_scale", 1.0))
        speaker = data.get("speaker", "Radio Host")
        title = data.get("title", "VoiceFi Studio Reel")

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        in_path = RECORDINGS_DIR / rec_id
        if not in_path.is_file() and rec_id.startswith("download_"):
            in_path = STATIC_DIR / "downloads" / rec_id.replace("download_", "")

        if not in_path.is_file():
            return web.json_response(
                {"error": f"Audio file not found: {rec_id}", "status": "error"}, status=404
            )

        from voicefi.video.reel_builder import ReelBuilder

        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", in_path.stem)
        fmt_clean = format_type.replace(":", "_")
        ts = int(time.time() * 1000)
        reel_filename = f"{slug}_{fmt_clean}_{ts}.mp4"

        downloads_dir = STATIC_DIR / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = downloads_dir / reel_filename

        ReelBuilder.compile_reel(
            output_mp4=out_mp4,
            audio_file=in_path,
            slides=slides,
            transcript=transcript,
            format_type=format_type,
            preset_name=preset_name,
            font_multiplier=font_multiplier,
            speaker_name=speaker,
        )

        return web.json_response(
            {
                "success": True,
                "title": title,
                "reel_filename": reel_filename,
                "download_url": f"/downloads/{reel_filename}",
                "format": format_type,
                "size_mb": round(out_mp4.stat().st_size / (1024 * 1024), 2),
            }
        )
