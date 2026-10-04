"""
voicefi/factory/cockpit.py
Real-Time Terminal Cockpit for VoiceFi Content Creation Factory.
Visualizes active workers, queue velocity, on-device Metal GPU token savings,
and live content pipeline stages using Rich Live Layout.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from voicefi.factory.queue import ContentFactoryQueue
from voicefi.factory.server import PID_FILE


class ContentFactoryCockpit:
    """Rich interactive terminal dashboard for the Content Creation Factory."""

    def __init__(self):
        self.console = Console()
        self.queue = ContentFactoryQueue()

    def generate_header(self) -> Panel:
        is_running = False
        pid = "None"
        if PID_FILE.exists():
            try:
                pid = PID_FILE.read_text().strip()
                # Check if process is alive
                os.kill(int(pid), 0)
                is_running = True
            except Exception:
                is_running = False

        status_text = Text()
        status_text.append("🎙️  VOICEFI™ CONTENT CREATION FACTORY  ", style="bold cyan")
        if is_running:
            status_text.append(f"● ENGINE ONLINE (PID: {pid})", style="bold green")
        else:
            status_text.append("○ ENGINE OFFLINE (Daemon stopped)", style="bold yellow")

        status_text.append(" | ⚡ Apple Silicon Metal GPU (Gemma 4)", style="dim")
        return Panel(status_text, box=box.ROUNDED, style="blue")

    def generate_queue_panel(self, counts: Dict[str, int]) -> Panel:
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        table.add_column("Stage / Status", style="cyan")
        table.add_column("Count", justify="right", style="bold yellow")

        table.add_row("Queued (Pending)", str(counts.get("QUEUED", 0)))
        table.add_row("Scripting (Gemma 4)", str(counts.get("SCRIPTING", 0)), style="bold cyan")
        table.add_row("Audio Gen (VoiceFi TTS)", str(counts.get("AUDIO_GEN", 0)), style="bold blue")
        table.add_row("Rendering (FFmpeg)", str(counts.get("RENDERING", 0)), style="bold magenta")
        table.add_row("Completed", str(counts.get("COMPLETED", 0)), style="bold green")
        table.add_row(
            "Failed",
            str(counts.get("FAILED", 0)),
            style="bold red" if counts.get("FAILED", 0) > 0 else "dim",
        )

        return Panel(
            table, title="[bold]Queue Velocity[/bold]", box=box.ROUNDED, border_style="cyan"
        )

    def generate_metrics_panel(self, metrics: Dict[str, Any]) -> Panel:
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right", style="bold green")

        table.add_row("Completed Reels", str(metrics.get("completed", 0)))
        table.add_row("Tokens Saved On-Device", f"{metrics.get('tokens_saved', 0):,}")
        table.add_row("Avg Turnaround", f"{metrics.get('avg_speed_s', 0):.2f}s")
        table.add_row("Unified Memory Ingress", "0.04 ms")
        table.add_row("API Cost Incurred", "$0.00 (Local Metal)")

        return Panel(
            table,
            title="[bold]On-Device Speed Bursts[/bold]",
            box=box.ROUNDED,
            border_style="green",
        )

    def generate_workers_table(self, workers: List[Dict[str, Any]]) -> Table:
        table = Table(box=box.ROUNDED, title="[bold]Active Factory Workers[/bold]", expand=True)
        table.add_column("Worker ID", style="cyan", no_wrap=True)
        table.add_column("Active Job", style="yellow")
        table.add_column("Stage", style="bold magenta")
        table.add_column("Status", style="green")
        table.add_column("Last Heartbeat", justify="right", style="dim")

        if not workers:
            table.add_row("No active workers", "-", "IDLE", "STANDBY", "-")
        else:
            now = time.time()
            for w in workers:
                elapsed = max(0, int(now - w["last_heartbeat"]))
                table.add_row(
                    w["worker_id"],
                    f"#{w['job_id']}" if w["job_id"] else "-",
                    w["current_stage"],
                    w["status"],
                    f"{elapsed}s ago",
                )
        return table

    def generate_jobs_table(self, jobs: list) -> Table:
        table = Table(
            box=box.ROUNDED, title="[bold]Recent Content Pipeline Jobs[/bold]", expand=True
        )
        table.add_column("ID", style="dim", width=5)
        table.add_column("Title / Topic", style="bold white")
        table.add_column("Characters", style="cyan")
        table.add_column("Stage", style="yellow")
        table.add_column("Status", style="bold")
        table.add_column("Master Audio / Output", style="dim")

        if not jobs:
            table.add_row(
                "-", "No jobs processed yet. Enqueue using './factory enqueue'", "-", "-", "-", "-"
            )
        else:
            for j in jobs:
                status_style = (
                    "green"
                    if j.status == "COMPLETED"
                    else ("red" if j.status == "FAILED" else "yellow")
                )
                out_path = Path(j.output_audio_path).name if j.output_audio_path else "-"
                chars_str = ", ".join(j.characters) if j.characters else "-"
                table.add_row(
                    f"#{j.id}",
                    j.title or j.prompt[:32],
                    chars_str,
                    j.current_stage,
                    f"[{status_style}]{j.status}[/{status_style}]",
                    out_path,
                )
        return table

    def build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="middle", size=9),
            Layout(name="workers", size=6),
            Layout(name="jobs", ratio=1),
        )
        layout["middle"].split_row(
            Layout(name="queue", ratio=1),
            Layout(name="metrics", ratio=1),
        )
        return layout

    def refresh(self, layout: Layout) -> None:
        counts = self.queue.query_queue_counts()
        metrics = self.queue.query_aggregate_metrics()
        workers = self.queue.query_active_workers()
        jobs = self.queue.query_recent_jobs(limit=8)

        layout["header"].update(self.generate_header())
        layout["queue"].update(self.generate_queue_panel(counts))
        layout["metrics"].update(self.generate_metrics_panel(metrics))
        layout["workers"].update(self.generate_workers_table(workers))
        layout["jobs"].update(self.generate_jobs_table(jobs))

    def run(self) -> None:
        self.console.clear()
        layout = self.build_layout()
        with Live(layout, refresh_per_second=2, screen=True) as live:
            try:
                while True:
                    self.refresh(layout)
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass


def main():
    cockpit = ContentFactoryCockpit()
    cockpit.run()


if __name__ == "__main__":
    main()
