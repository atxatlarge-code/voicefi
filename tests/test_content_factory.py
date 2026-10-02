"""
tests/test_content_factory.py
Unit tests for the VoiceFi Autonomous Content Creation Factory.
Verifies queue transactions, local generator manifests, and server pipeline execution.
"""

import tempfile
from pathlib import Path
import pytest

from voicefi.factory.models import ContentJob, ContentType, JobStatus
from voicefi.factory.queue import ContentFactoryQueue
from voicefi.factory.generator import LocalContentGenerator
from voicefi.factory.server import ContentFactoryServer


@pytest.fixture
def temp_queue(tmp_path):
    db_file = tmp_path / "test_factory.db"
    return ContentFactoryQueue(db_path=db_file)


def test_queue_enqueue_and_pop(temp_queue):
    job = ContentJob(
        title="Test Reel",
        prompt="Discussing async pipeline vs synchronous chat",
        characters=["Viv", "Stefan"],
        priority=10,
    )
    job_id = temp_queue.enqueue_job(job)
    assert job_id is not None
    assert job_id > 0

    counts = temp_queue.query_queue_counts()
    assert counts["QUEUED"] == 1

    popped = temp_queue.pop_next_job(worker_id="test_worker_1")
    assert popped is not None
    assert popped.id == job_id
    assert popped.status == JobStatus.SCRIPTING.value
    assert popped.worker_id == "test_worker_1"

    counts_after = temp_queue.query_queue_counts()
    assert counts_after["QUEUED"] == 0
    assert counts_after["SCRIPTING"] == 1


def test_local_generator_deterministic_fallback():
    generator = LocalContentGenerator(preferred_endpoint="http://127.0.0.1:99999/v1")  # intentionally dead port
    job = ContentJob(
        title="Fallback Reel Test",
        prompt="Testing on-device zero-latency generation",
        characters=["Viv", "Stefan"],
        target_duration_s=30.0,
    )
    manifest, tokens_saved, elapsed = generator.generate_manifest(job)
    assert manifest.title is not None
    assert len(manifest.turns) >= 2
    assert tokens_saved > 0
    assert elapsed >= 0.0
    assert manifest.calculated_duration_s > 0


def test_server_run_once_execution(tmp_path):
    db_file = tmp_path / "exec_factory.db"
    server = ContentFactoryServer(concurrency=1, db_path=db_file)
    server.build_dir = tmp_path / "factory_out"
    server.build_dir.mkdir(parents=True, exist_ok=True)

    job = ContentJob(
        title="Server Pipeline Reel",
        prompt="Autonomous video pipeline test",
        characters=["Viv", "Stefan"],
        priority=20,
    )
    server.queue.enqueue_job(job)

    import asyncio
    asyncio.run(server.run_once())

    completed_job = server.queue.get_job(1)
    assert completed_job is not None
    assert completed_job.status == JobStatus.COMPLETED.value
    assert completed_job.manifest_data is not None
