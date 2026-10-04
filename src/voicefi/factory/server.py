"""
voicefi/factory/server.py
Autonomous Content Creation Factory Server & Worker Daemon.
Manages transactional queue processing, orchestrates on-device local models,
VoiceFi multi-speaker TTS synthesis, and reel video rendering.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
import uuid
import wave
from pathlib import Path
from typing import Dict, List, Optional

from voicefi.config import load_config
from voicefi.factory.generator import LocalContentGenerator
from voicefi.factory.models import ContentJob, ContentManifest, JobStatus
from voicefi.factory.queue import ContentFactoryQueue, get_default_factory_db_path
from voicefi.tts import get_tts_engine

logger = logging.getLogger("voicefi.factory.server")

PID_FILE = Path("/tmp/voicefi_factory.pid")
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


class ContentFactoryServer:
    """
    Autonomous multi-stage worker server for content generation.
    Decouples ideation from rendering, maximizing local Metal GPU acceleration.
    """

    def __init__(self, concurrency: int = 2, db_path: Optional[Path] = None):
        self.concurrency = concurrency
        self.queue = ContentFactoryQueue(db_path=db_path)
        self.generator = LocalContentGenerator()
        self.config = load_config()
        self.running = True
        self.shutdown_event = asyncio.Event()
        self.active_workers: Dict[str, asyncio.Task] = {}
        self.build_dir = Path.home() / ".voicefi" / "factory_output"
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logging()

    def _setup_logging(self) -> None:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    def write_pid_file(self) -> None:
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not write PID file: {e}")

    def cleanup_pid_file(self) -> None:
        try:
            if PID_FILE.exists():
                saved = int(PID_FILE.read_text().strip())
                if saved == os.getpid():
                    PID_FILE.unlink()
        except Exception:
            pass

    async def run_worker_loop(self, worker_id: str) -> None:
        """Continuous worker execution loop."""
        logger.info(f"Worker [{worker_id}] initialized and polling queue...")
        while self.running:
            self.queue.update_worker_heartbeat(
                worker_id=worker_id,
                current_stage="IDLE",
                status="POLLING",
                job_id=None,
            )

            job = self.queue.pop_next_job(worker_id)
            if not job:
                try:
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    break
                continue

            # Process popped job
            await self._process_job(worker_id, job)

        self.queue.update_worker_heartbeat(
            worker_id=worker_id,
            current_stage="STOPPED",
            status="INACTIVE",
            job_id=None,
        )

    async def _process_job(self, worker_id: str, job: ContentJob) -> None:
        job_id = job.id
        start_time = time.time()
        logger.info(f"[{worker_id}] Processing Job #{job_id}: '{job.title or job.prompt[:30]}'")

        try:
            # -----------------------------------------------------------------
            # Stage 1: Local Script Generation (Instant on Metal GPU)
            # -----------------------------------------------------------------
            self.queue.update_worker_heartbeat(
                worker_id=worker_id,
                current_stage="SCRIPTING",
                status="ACTIVE",
                job_id=job_id,
            )
            self.queue.update_job_stage(
                job_id=job_id, stage="SCRIPTING", status=JobStatus.SCRIPTING.value
            )

            if job.manifest_data:
                logger.info(f"[{worker_id}] Using pre-loaded manifest data for Job #{job_id}.")
                manifest = ContentManifest.from_dict(job.manifest_data)
                tokens_saved = 450
                script_sec = 0.01
            else:
                manifest, tokens_saved, script_sec = await asyncio.to_thread(
                    self.generator.generate_manifest, job
                )
                logger.info(
                    f"[{worker_id}] Job #{job_id} Script generated in {script_sec:.2f}s ({tokens_saved} tokens saved)."
                )

            self.queue.update_job_stage(
                job_id=job_id,
                stage="AUDIO_GEN",
                status=JobStatus.AUDIO_GEN.value,
                manifest_data=manifest.to_dict(),
                tokens_saved=tokens_saved,
                generation_seconds=script_sec,
            )

            # -----------------------------------------------------------------
            # Stage 2: VoiceFi Multi-Speaker TTS Audio Synthesis
            # -----------------------------------------------------------------
            self.queue.update_worker_heartbeat(
                worker_id=worker_id,
                current_stage="AUDIO_GEN",
                status="ACTIVE",
                job_id=job_id,
            )

            job_out_dir = self.build_dir / f"job_{job_id:04d}"
            job_out_dir.mkdir(parents=True, exist_ok=True)
            turn_files: List[Path] = []

            import re

            for idx, turn in enumerate(manifest.turns):
                turn_audio_path = job_out_dir / f"turn_{idx:02d}_{turn.speaker}.wav"
                engine = get_tts_engine(
                    self.config,
                    agent_name=turn.speaker,
                    voice_override=turn.voice_id,
                )
                # Strip out [sfx:...] tags so speech synthesis doesn't verbalize sound effect markers
                clean_spoken_text = re.sub(r"\[sfx:[^\]]+\]", "", turn.text).strip()
                success = await asyncio.to_thread(
                    engine.speak_to_file, clean_spoken_text, turn_audio_path
                )
                if success and turn_audio_path.exists():
                    turn.audio_path = str(turn_audio_path)
                    turn_files.append(turn_audio_path)
                else:
                    logger.warning(f"TTS generation returned false for turn {idx}")

            # Concatenate master vocal audio
            master_audio_path = job_out_dir / f"job_{job_id:04d}_master.wav"
            if turn_files:
                await asyncio.to_thread(self._combine_audio_turns, turn_files, master_audio_path)

            # Check for backing track mixing
            backing_track_path = None
            if manifest.backing_track:
                # Resolve relative or absolute path
                candidates = [
                    Path(manifest.backing_track),
                    Path("/Users/jaketrigg/Projects/vifi.co") / manifest.backing_track,
                    Path(
                        "/Users/jaketrigg/Projects/vifi.co/marketing/social/assets/spicewood_texas_beat_85bpm.mp3"
                    ),
                ]
                for c in candidates:
                    if c.exists() and c.is_file():
                        backing_track_path = c
                        break

            final_audio_path = master_audio_path
            if backing_track_path and master_audio_path.exists():
                mixed_audio_path = job_out_dir / f"job_{job_id:04d}_mix.wav"
                await asyncio.to_thread(
                    self._mix_backing_track, master_audio_path, backing_track_path, mixed_audio_path
                )
                if mixed_audio_path.exists():
                    final_audio_path = mixed_audio_path

            audio_sec = time.time() - start_time - script_sec

            # -----------------------------------------------------------------
            # Stage 3: Reel Packaging / Video Assembly
            # -----------------------------------------------------------------
            self.queue.update_worker_heartbeat(
                worker_id=worker_id,
                current_stage="RENDERING",
                status="ACTIVE",
                job_id=job_id,
            )
            self.queue.update_job_stage(
                job_id=job_id,
                stage="RENDERING",
                status=JobStatus.RENDERING.value,
                audio_path=str(final_audio_path) if final_audio_path.exists() else None,
                manifest_data=manifest.to_dict(),
                generation_seconds=audio_sec,
            )

            # Mark completed (Video compilation can be attached via post-hook)
            total_sec = time.time() - start_time
            self.queue.update_job_stage(
                job_id=job_id,
                stage="COMPLETED",
                status=JobStatus.COMPLETED.value,
                manifest_data=manifest.to_dict(),
                audio_path=str(master_audio_path) if master_audio_path.exists() else None,
            )
            logger.info(f"[{worker_id}] ✅ Completed Job #{job_id} in {total_sec:.2f}s total.")

        except Exception as e:
            logger.error(f"[{worker_id}] ❌ Error on Job #{job_id}: {e}", exc_info=True)
            self.queue.update_job_stage(
                job_id=job_id,
                stage="FAILED",
                status=JobStatus.FAILED.value,
                error_message=str(e),
            )

    def _combine_audio_turns(self, input_wavs: List[Path], output_wav: Path) -> None:
        """Combine multiple audio files sequentially into a master vocal take using FFmpeg."""
        if not input_wavs:
            return

        concat_txt = output_wav.parent / "concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in input_wavs:
                f.write(f"file '{p.resolve()}'\n")

        import subprocess

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_wav),
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if concat_txt.exists():
                concat_txt.unlink()
        except Exception as e:
            logger.warning(f"FFmpeg audio combination failed: {e}")

    def _mix_backing_track(self, vocal_wav: Path, backing_track: Path, output_wav: Path) -> None:
        """Mix vocal audio with backing track applying ducking and 48kHz normalization."""
        import subprocess

        # Vocal (0:a) + Backing Track (1:a) ducked to -14dB (~0.20 volume)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(vocal_wav),
            "-i",
            str(backing_track),
            "-filter_complex",
            "[1:a]volume=0.20[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_wav),
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            # Also export an MP3 copy next to it
            mp3_out = output_wav.with_suffix(".mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(output_wav), "-b:a", "192k", str(mp3_out)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning(f"Backing track mix failed: {e}")

    async def start(self) -> None:
        self.write_pid_file()
        logger.info(f"🚀 Content Factory Server active with concurrency={self.concurrency}.")

        # Setup OS signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except NotImplementedError:
                pass

        for i in range(self.concurrency):
            worker_id = f"worker_{i + 1:02d}_{uuid.uuid4().hex[:4]}"
            task = asyncio.create_task(self.run_worker_loop(worker_id))
            self.active_workers[worker_id] = task

        await self.shutdown_event.wait()
        logger.info("Factory Server gracefully exiting...")

    async def stop(self) -> None:
        self.running = False
        for task in self.active_workers.values():
            task.cancel()
        self.cleanup_pid_file()
        self.shutdown_event.set()

    async def run_once(self) -> None:
        """Process currently queued jobs once and exit immediately."""
        self.write_pid_file()
        worker_id = f"worker_once_{uuid.uuid4().hex[:4]}"
        logger.info(f"Content Factory executing single-pass batch run with {worker_id}...")
        while True:
            job = self.queue.pop_next_job(worker_id)
            if not job:
                break
            await self._process_job(worker_id, job)
        self.cleanup_pid_file()
        logger.info("Single-pass batch run finished.")


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Autonomous Content Factory Server")
    parser.add_argument(
        "--server", action="store_true", help="Run continuously in background daemon mode"
    )
    parser.add_argument(
        "--run-once", action="store_true", help="Process all currently queued jobs and exit"
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent worker pipelines (default: 2)",
    )
    args = parser.parse_args()

    server = ContentFactoryServer(concurrency=args.concurrency)
    if args.run_once:
        asyncio.run(server.run_once())
    else:
        asyncio.run(server.start())


if __name__ == "__main__":
    main()
