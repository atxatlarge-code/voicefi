"""
voicefi/factory/enqueuer.py
CLI and programmatic enqueuer for the VoiceFi Content Creation Factory.
Enqueues individual prompts, batch JSON files, and manifests directly into the queue.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from voicefi.factory.models import ContentJob, ContentType
from voicefi.factory.queue import ContentFactoryQueue


def enqueue_single_prompt(
    prompt: str,
    title: Optional[str] = None,
    characters: Optional[List[str]] = None,
    content_type: str = ContentType.REEL_9_16.value,
    target_duration: float = 30.0,
    priority: int = 10,
    batch_name: str = "ad_hoc",
) -> int:
    queue = ContentFactoryQueue()
    chars = characters or ["Viv", "Stefan"]
    job = ContentJob(
        batch_name=batch_name,
        title=title or prompt[:40],
        prompt=prompt,
        content_type=content_type,
        characters=chars,
        target_duration_s=target_duration,
        priority=priority,
    )
    job_id = queue.enqueue_job(job)
    return job_id


def enqueue_from_json_file(file_path: Path, batch_name: Optional[str] = None) -> int:
    if not file_path.exists():
        raise FileNotFoundError(f"Batch file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    b_name = batch_name or file_path.stem
    queue = ContentFactoryQueue()

    # Detect single manifest file (e.g. content_factory_reel_manifest.json)
    if isinstance(data, dict) and ("slides" in data or "turns" in data):
        chars = [c.get("character") for c in data.get("cast", []) if isinstance(c, dict)] or ["Viv", "Stefan"]
        job = ContentJob(
            batch_name=b_name,
            title=data.get("title", file_path.stem),
            prompt=data.get("description", data.get("title", "")),
            content_type=data.get("content_type", ContentType.REEL_9_16.value),
            characters=chars,
            target_duration_s=float(data.get("duration_seconds", 30.0)),
            manifest_data=data,
            priority=15,
        )
        queue.enqueue_job(job)
        return 1

    jobs = []
    items = data if isinstance(data, list) else data.get("jobs", [])

    for item in items:
        job = ContentJob(
            batch_name=b_name,
            title=item.get("title", ""),
            prompt=item.get("prompt", ""),
            content_type=item.get("content_type", ContentType.REEL_9_16.value),
            characters=item.get("characters", ["Viv", "Stefan"]),
            target_duration_s=float(item.get("target_duration_s", 30.0)),
            priority=int(item.get("priority", 10)),
            manifest_data=item.get("manifest_data"),
        )
        jobs.append(job)

    return queue.enqueue_batch(jobs, batch_name=b_name)


def main():
    console = Console()
    parser = argparse.ArgumentParser(description="Enqueue jobs into the VoiceFi Content Factory")
    parser.add_argument("prompt", nargs="?", help="Direct prompt or topic to enqueue")
    parser.add_argument("-t", "--title", help="Optional title for the job")
    parser.add_argument("-f", "--file", type=Path, help="Path to JSON file containing a batch of jobs")
    parser.add_argument("-c", "--chars", default="Viv,Stefan", help="Comma-separated characters (default: Viv,Stefan)")
    parser.add_argument("-p", "--priority", type=int, default=10, help="Priority (default: 10)")
    parser.add_argument("-b", "--batch", default="ad_hoc", help="Batch name")
    parser.add_argument("-d", "--duration", type=float, default=30.0, help="Target duration in seconds (default: 30.0)")

    args = parser.parse_args()

    if args.file:
        count = enqueue_from_json_file(args.file, batch_name=args.batch)
        console.print(f"[bold green]✓ Enqueued {count} jobs from {args.file} into batch '{args.batch}'.[/bold green]")
    elif args.prompt:
        chars = [c.strip() for c in args.chars.split(",") if c.strip()]
        job_id = enqueue_single_prompt(
            prompt=args.prompt,
            title=args.title,
            characters=chars,
            target_duration=args.duration,
            priority=args.priority,
            batch_name=args.batch,
        )
        console.print(f"[bold green]✓ Enqueued Job #{job_id}: '{args.title or args.prompt[:40]}'[/bold green]")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
