#!/usr/bin/env python3
"""
scripts/run_content_factory.py
VoiceFi Autonomous Content Factory Loop.

Pulls jobs continuously from ContentFactoryQueue, generates dynamic dialogue
using local Ollama models (Gemma 2 2B / Llama 3.2 1B) guarded by ThermalSupervisor,
and stages them for audio rendering without cloud API costs.
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voicefi.factory.generator import LocalContentGenerator
from voicefi.factory.models import ContentJob, JobStatus
from voicefi.factory.queue import ContentFactoryQueue
from voicefi.local.supervisor import default_supervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voicefi.factory.worker")

RUNNING = True


def handle_shutdown(signum, frame):
    global RUNNING
    logger.info(f"Received signal {signum}, initiating clean shutdown...")
    RUNNING = False


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Autonomous Content Factory Loop")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite queue database")
    parser.add_argument("--worker-id", type=str, default="worker_local_01", help="Worker ID")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument(
        "--max-jobs", type=int, default=0, help="Max jobs to process (0 = infinite)"
    )
    parser.add_argument(
        "--enqueue-samples", type=int, default=0, help="Enqueue N sample test jobs on start"
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    queue = ContentFactoryQueue(db_path=args.db)
    generator = LocalContentGenerator()

    if args.enqueue_samples > 0:
        logger.info(f"Enqueuing {args.enqueue_samples} sample content jobs...")
        samples = [
            (
                "Local AI vs Cloud API billing: why developers are switching to on-device models",
                ["Viv", "Jake"],
            ),
            (
                "The secret behind zero-latency full duplex voice barge-in on Apple Silicon",
                ["Christopher", "Stefan"],
            ),
            (
                "Why 100k context windows make agents lazy and local scouts make them sharp",
                ["Viv", "Christopher"],
            ),
        ]
        for i in range(args.enqueue_samples):
            prompt, chars = samples[i % len(samples)]
            new_job = ContentJob(
                title=f"Sample Short {i + 1}",
                prompt=f"{prompt} (Batch {i + 1})",
                characters=chars,
                target_duration_s=25,
            )
            job_id = queue.enqueue_job(new_job)
            logger.info(f"Enqueued job {job_id}")

    logger.info(f"Content Factory Worker '{args.worker_id}' active. Polling queue...")
    jobs_processed = 0
    total_tokens_saved = 0

    while RUNNING:
        # Check thermal supervisor before pulling work
        default_supervisor.wait_if_throttled(poll_interval=3.0, max_wait=30.0)

        job = queue.pop_next_job(worker_id=args.worker_id)
        if not job:
            if args.max_jobs > 0 and jobs_processed >= args.max_jobs:
                break
            time.sleep(args.poll_interval)
            continue

        logger.info(f"Processing Job {job.id}: '{job.prompt[:60]}...'")
        t0 = time.time()
        try:
            queue.update_job_stage(job.id, stage="SCRIPTING", status=JobStatus.SCRIPTING.value)
            manifest, tokens_saved, gen_sec = generator.generate_manifest(job)

            total_tokens_saved += tokens_saved
            jobs_processed += 1

            queue.update_job_stage(
                job.id,
                stage="COMPLETED",
                status=JobStatus.COMPLETED.value,
                tokens_saved=tokens_saved,
                generation_seconds=gen_sec,
                manifest_data=manifest.to_dict() if hasattr(manifest, "to_dict") else None,
            )

            logger.info(
                f"Job {job.id} completed in {gen_sec:.2f}s | Saved {tokens_saved} tokens (Total: {total_tokens_saved:,}) | Title: '{manifest.title}'"
            )

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}", exc_info=True)
            queue.update_job_stage(
                job.id, stage="FAILED", status=JobStatus.FAILED.value, error_message=str(e)
            )

        if args.max_jobs > 0 and jobs_processed >= args.max_jobs:
            logger.info(f"Hit max jobs limit ({args.max_jobs}). Exiting loop.")
            break

    logger.info(
        f"Worker {args.worker_id} finished. Processed {jobs_processed} jobs, saved {total_tokens_saved:,} on-device tokens."
    )


if __name__ == "__main__":
    main()
