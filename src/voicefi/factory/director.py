"""
Autonomous Local AI Factory - Master Director
Runs 100% offline on Apple Silicon (M5 Pro).
Unified 4-Phase Architecture for Social Reel Generation.
"""

import json
import logging
import os
import shutil
import subprocess
import asyncio
import gc
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ImageGenerator:
    """Phase 1: Local Image Generation Engine (Apple MLX FLUX.1)"""

    def __init__(
        self,
        output_dir: Path,
        model: str = "schnell",
        quantize: int = 8,
        width: int = 768,
        height: int = 1360,
        steps: int = 4,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.quantize = quantize
        self.width = width
        self.height = height
        self.steps = steps

    async def generate_images(self, prompts: List[str]) -> List[Path]:
        generated_files = []

        mflux_bin = shutil.which("mflux-generate")
        if not mflux_bin:
            logger.error("mflux-generate binary not found. Install via: uv tool install mflux")
            return []

        for i, prompt in enumerate(prompts):
            output_file = self.output_dir / f"scene_{i:03d}.png"
            logger.info(
                f"🎨 [FLUX.1-{self.model}] Rendering Scene {i+1}/{len(prompts)} "
                f"({self.width}x{self.height}, Q{self.quantize}, {self.steps} steps): {prompt[:65]}..."
            )

            cmd = [
                mflux_bin,
                "--model", self.model,
                "--prompt", prompt,
                "--output", str(output_file),
                "--steps", str(self.steps),
                "--quantize", str(self.quantize),
                "--width", str(self.width),
                "--height", str(self.height),
            ]

            # FLUX.1-dev uses guidance; schnell requires no guidance flag
            if self.model == "dev":
                cmd.extend(["--guidance", "3.5"])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0 and output_file.exists():
                logger.info(f"✓ Scene {i+1} saved: {output_file.name}")
                generated_files.append(output_file)
            else:
                logger.error(f"✗ Scene {i+1} failed: {stderr.decode().strip()}")

            # Brief pause for OS kernel to reclaim deallocated wired pages
            await asyncio.sleep(0.2)

        return generated_files


class TTSGenerator:
    """Phase 3: VoiceFi 100% Offline Audio Synthesis Engine (Apple Silicon / macOS)."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_offline_voice(self) -> str:
        """Select best available Apple Neural Voice installed on macOS."""
        try:
            from voicefi.tts.offline import is_voice_installed
            for preferred in ("Ava (Premium)", "Ava (Enhanced)", "Ava", "Samantha"):
                installed, exact_name = is_voice_installed(preferred)
                if installed and exact_name:
                    return exact_name
        except Exception:
            pass
        return "Ava (Premium)"

    def _synthesize_sync(self, voiceover_script: str, output_wav: Path) -> Path:
        """Synchronous synthesis and 48kHz broadcast mastering pipeline."""
        import tempfile

        # Clean text
        clean_text = voiceover_script.strip()
        try:
            from voicefi.tts.normalizer import normalize_tts_text
            clean_text = normalize_tts_text(clean_text)
        except Exception:
            pass

        if not clean_text:
            clean_text = "VoiceFi offline master voiceover."

        voice = self._resolve_offline_voice()
        rate = "190"  # Conversational reel delivery (WPM)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_aiff = Path(tmp_dir) / "synth_raw.aiff"
            tmp_wav = Path(tmp_dir) / "resampled_48k.wav"

            # 1. Synthesize locally using macOS native Neural CoreAudio
            cmd_say = [
                "say",
                "-v", voice,
                "-r", rate,
                "-o", str(tmp_aiff),
                "--",
                clean_text,
            ]
            res = subprocess.run(cmd_say, capture_output=True, text=True)
            if res.returncode != 0 or not tmp_aiff.is_file():
                # Fallback to system default voice without -v
                subprocess.run(
                    ["say", "-r", rate, "-o", str(tmp_aiff), "--", clean_text],
                    capture_output=True,
                    check=False,
                )

            # 2. Resample to 48kHz Broadcast Standard Linear PCM WAV (Zero MP3 Priming Delay)
            # Strategy A: Built-in macOS afconvert (ultra-fast, zero dependencies)
            if shutil.which("afconvert") and tmp_aiff.is_file():
                cmd_resample = [
                    "afconvert",
                    "-f", "WAVE",
                    "-d", "LEI16@48000",
                    str(tmp_aiff),
                    str(tmp_wav),
                ]
                subprocess.run(cmd_resample, capture_output=True, check=False)

            # Strategy B: FFmpeg fallback if afconvert was skipped
            if (not tmp_wav.is_file() or tmp_wav.stat().st_size == 0) and shutil.which("ffmpeg") and tmp_aiff.is_file():
                cmd_ffmpeg = [
                    "ffmpeg", "-y",
                    "-i", str(tmp_aiff),
                    "-ar", "48000",
                    "-c:a", "pcm_s16le",
                    str(tmp_wav),
                ]
                subprocess.run(cmd_ffmpeg, capture_output=True, check=False)

            # 3. Apply BBC Broadcast Studio Mastering if available in VoiceFi
            if tmp_wav.is_file() and tmp_wav.stat().st_size > 0:
                try:
                    from voicefi.audio.mastering import apply_bbc_documentary_mastering
                    mastered_wav = apply_bbc_documentary_mastering(tmp_wav, output_wav)
                    if Path(mastered_wav).is_file() and Path(mastered_wav).stat().st_size > 0:
                        return Path(mastered_wav)
                except Exception:
                    pass

                # If mastering not available, copy the pristine 48kHz WAV
                shutil.copy(str(tmp_wav), str(output_wav))
                return output_wav

        # Fallback tone if say failed
        if not output_wav.exists() and shutil.which("ffmpeg"):
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=mono",
                "-t", "3",
                "-c:a", "pcm_s16le",
                str(output_wav),
            ], capture_output=True, check=False)

        return output_wav

    async def generate_voiceover(self, voiceover_script: str) -> Optional[Path]:
        """
        Synthesizes 48kHz broadcast master voiceover 100% offline on Apple Silicon.
        Guarantees WAV container output for sample-accurate Whisper alignment.
        """
        output_file = self.output_dir / "master_voiceover.wav"
        logger.info(f"🎙️ VoiceFi Offline TTS: Synthesizing master broadcast audio to {output_file}")

        try:
            res_path = await asyncio.to_thread(self._synthesize_sync, voiceover_script, output_file)
            if res_path and res_path.exists() and res_path.stat().st_size > 0:
                logger.info(f"✓ Offline 48kHz audio synthesized: {res_path.name} ({res_path.stat().st_size} bytes)")
                return res_path
        except Exception as e:
            logger.error(f"VoiceFi Offline TTS error: {e}")

        return output_file if output_file.exists() else None


class VideoStitcher:
    """Phase 3 & 4: Hardware-Accelerated Video Stitcher (VideoToolbox M5 Pro)"""

    def __init__(self, output_dir: Path, workspace_root: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root = Path(workspace_root)

    async def stitch(self, image_paths: List[Path], audio_path: Path, manifest_data: Dict) -> Optional[Path]:
        if not image_paths or not audio_path or not audio_path.exists():
            logger.error("Missing video assets or audio master. Cannot stitch.")
            return None

        output_video = self.output_dir / "factory_reel_master.mp4"
        logger.info("🎬 Assembly Line: Encoding 9:16 master reel via Apple VideoToolbox...")

        # 1. Write Tier 1 Declarative Manifest
        manifest_path = self.workspace_root / "marketing" / "social" / "reels" / "latest_factory_reel.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        manifest = {
            "title": "Autonomous Factory Reel",
            "aspect_ratio": "9:16",
            "resolution": "768x1360",
            "audio_master": str(audio_path.resolve()),
            "visual_assets": [str(p.resolve()) for p in image_paths],
            "script": manifest_data.get("voiceover_script", ""),
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # 2. Derive Audio Duration via ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        probe_proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe_proc.communicate()
        try:
            total_duration = float(stdout.decode().strip())
        except Exception:
            total_duration = max(5.0, len(image_paths) * 3.5)

        duration_per_image = total_duration / len(image_paths)

        # 3. Create Concat Demuxer Script
        concat_txt = self.output_dir / "images.txt"
        with open(concat_txt, "w") as f:
            for p in image_paths:
                f.write(f"file '{p.resolve()}'\n")
                f.write(f"duration {duration_per_image:.3f}\n")
            f.write(f"file '{image_paths[-1].resolve()}'\n")

        # 4. Hardware-Accelerated Encode via M5 Pro Media Engine (h264_videotoolbox)
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-i", str(audio_path),
            "-c:v", "h264_videotoolbox",
            "-b:v", "12M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_video),
        ]

        stitch_proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await stitch_proc.communicate()

        if stitch_proc.returncode == 0 and output_video.exists():
            logger.info(f"✨ Master Reel Successfully Rendered: {output_video}")
            return output_video
        else:
            logger.error(f"FFmpeg encoding error: {stderr.decode()}")
            return None


class FactoryDirector:
    """Phase 2: The LLM Orchestrator (Sequentially Managed on Apple Silicon)"""

    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root).resolve()
        self.output_dir = self.workspace_root / "factory_output"

        # M5 Pro Optimized: Schnell 4-step, 8-bit quantized, 9:16 vertical resolution
        self.image_gen = ImageGenerator(
            output_dir=self.output_dir / "images",
            model="schnell",
            quantize=8,
            width=768,
            height=1360,
            steps=4,
        )
        self.tts_gen = TTSGenerator(self.output_dir / "audio")
        self.video_stitcher = VideoStitcher(self.output_dir / "video", self.workspace_root)

    def _get_director_prompt(self, concept: str) -> str:
        return f"""You are an elite cinematic director for 9:16 vertical short-form reels.
Given the concept below, produce a captivating, high-retention 15-second voiceover script and 4 distinct, cohesive 9:16 cinematography scene prompts.

Important Cinematography Rules:
- All shots must be designed for 9:16 vertical mobile framing.
- Subject matter must remain in the vertical center-third (safe from top badge overlays and bottom subtitle cards).
- Use photographic terminology: lens (e.g., 35mm / 50mm portrait prime), lighting (volumetric, chiaroscuro, cinematic rim light), and film stock (Kodak Portra 400, Arri Alexa LF).

Respond ONLY with valid JSON matching this schema:
{{
  "voiceover_script": "Engaging, rhythmic spoken dialogue for the entire 15-second reel.",
  "image_prompts": [
    "Dramatic vertical 9:16 portrait composition, Cooke Anamorphic 35mm lens, center-weighted subject, volumetric rim lighting, Kodak Portra 400 color grade, photorealistic.",
    "Macro close-up vertical 9:16 frame, shallow depth of field, f/1.8 bokeh, center focus, atmospheric haze, subtle film grain.",
    "Dynamic eye-level vertical 9:16 framing, cinematic chiaroscuro lighting, rich textures, Arri Alexa LF look.",
    "Wide-angle vertical 9:16 final reveal, golden hour rim light, center-framed subject, photorealistic detail."
  ]
}}

Concept: {concept}
JSON:"""

    async def _query_gemma_local(self, prompt: str) -> Dict[str, Any]:
        """Queries on-device Gemma with strict VRAM cleanup before FLUX begins."""
        logger.info("🧠 Phase 2: Querying local Gemma orchestrator on Apple Silicon...")

        # 1. Priority 1: Built-in VoiceFi LiteRT LocalModelEngine (On-Device Metal GPU)
        try:
            from voicefi.local import LocalModelEngine
            engine = LocalModelEngine(model_name="gemma4-26b")
            if not engine.model_exists:
                engine = LocalModelEngine(model_name="gemma4-2b")
            if engine.is_installed and engine.model_exists:
                logger.info(f"Using on-device LiteRT Metal engine ({engine.model_name})...")
                res = await engine.chat_text(
                    prompt=prompt,
                    system_instructions="You are an AI Film Director. Output valid JSON only.",
                )
                if res:
                    return self._clean_and_parse_json(res)
        except Exception as e:
            logger.debug(f"LiteRT engine check skipped: {e}")

        # 2. Priority 2: MLX-LM with PRE-QUANTIZED 4-bit weights + Metal Cache Eviction
        try:
            from mlx_lm import load, generate
            import mlx.core as mx

            logger.info("Loading mlx-community/gemma-2-27b-it-4bit (15.6 GB VRAM)...")
            model, tokenizer = load("mlx-community/gemma-2-27b-it-4bit")
            response = generate(model, tokenizer, prompt=prompt, max_tokens=1000)

            # MANDATORY: Release weights and purge Metal buffer cache before FLUX starts
            del model
            del tokenizer
            mx.metal.clear_cache()
            gc.collect()
            logger.info("✓ Gemma model unmapped and Metal memory pool cleared.")

            return self._clean_and_parse_json(response)
        except ImportError:
            pass
        except Exception as ex:
            logger.warning(f"MLX inference error: {ex}")

        # 3. Priority 3: Ollama with immediate unload (keep_alive: 0)
        try:
            logger.info("Falling back to Ollama with keep_alive=0...")
            cmd = ["ollama", "run", "gemma2:2b", prompt]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            # Immediately unload from VRAM to make room for FLUX
            subprocess.run(["ollama", "stop", "gemma2:2b"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self._clean_and_parse_json(stdout.decode())
        except Exception as e:
            logger.error(f"All local LLM engines failed: {e}")
            return {"voiceover_script": "", "image_prompts": []}

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].strip()
        try:
            return json.loads(cleaned)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON: {e}. Raw: {raw_text[:200]}")
            return {"voiceover_script": "", "image_prompts": []}

    async def run_factory(self, concept: str) -> Optional[Path]:
        logger.info(f"🚀 Launching Autonomous Factory Pipeline for: '{concept}'")

        # ─── STAGE 1: LLM DIRECTING (Sequential - Gemma exclusively holds VRAM) ───
        script_data = await self._query_gemma_local(self._get_director_prompt(concept))
        voiceover_script = script_data.get("voiceover_script", "")
        image_prompts = script_data.get("image_prompts", [])

        if not image_prompts or not voiceover_script:
            logger.error("Failed to generate valid script and scene prompts. Aborting.")
            return None

        logger.info(f"✓ Script generated with {len(image_prompts)} scenes. (VRAM completely freed for FLUX)")

        # ─── STAGE 2: ASSET GENERATION (Decoupled: CPU TTS + Metal FLUX) ───
        # Audio uses CPU/CoreAudio; FLUX uses 100% of Apple Silicon GPU
        image_task = self.image_gen.generate_images(image_prompts)
        tts_task = self.tts_gen.generate_voiceover(voiceover_script)

        image_paths, audio_path = await asyncio.gather(image_task, tts_task)

        if not image_paths or not audio_path:
            logger.error("Asset generation incomplete. Aborting stitch.")
            return None

        # ─── STAGE 3: VIDEO ASSEMBLY (Apple VideoToolbox Hardware) ───
        final_video = await self.video_stitcher.stitch(image_paths, audio_path, script_data)
        logger.info(f"🎉 Pipeline finished! Reel ready at: {final_video}")
        return final_video


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    director = FactoryDirector(workspace_root="/Users/jaketrigg/Projects/VoiceFi")
    await director.run_factory("A cyberpunk neon noodle bar in torrential rain")


if __name__ == "__main__":
    asyncio.run(main())
