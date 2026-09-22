"""
Tests for VoiceFi Smart Segment-Isolated Video Rendering Engine.
Validates SHA-256 fingerprinting, cache hit/miss behavior, parameter and file invalidation,
single-segment isolation, and lossless concat demuxing.
"""

import json
import subprocess
import time
from pathlib import Path
import pytest

from voicefi.video.segment_pipeline import SegmentCache, SegmentPipeline, SegmentDefinition


@pytest.fixture
def test_cache_dir(tmp_path):
    cache_d = tmp_path / "reel_cache"
    cache_d.mkdir(parents=True, exist_ok=True)
    return cache_d


def test_fingerprint_determinism(test_cache_dir, tmp_path):
    cache = SegmentCache(test_cache_dir)
    f1 = tmp_path / "take1.mp4"
    f1.write_text("dummy video content 1")
    f2 = tmp_path / "voice.wav"
    f2.write_text("dummy audio content 2")

    params1 = {"duration": 8.5, "x": 400, "y": 300, "grade": "curves=all='0/0 1/1'"}
    params2 = {"grade": "curves=all='0/0 1/1'", "y": 300, "x": 400, "duration": 8.5}

    fp1 = cache.compute_fingerprint("seg1", [f1, f2], params1)
    fp2 = cache.compute_fingerprint("seg1", [f2, f1], params2)

    assert fp1 == fp2, "Fingerprint must be deterministic regardless of param or input order"


def test_fingerprint_invalidation_on_param_change(test_cache_dir, tmp_path):
    cache = SegmentCache(test_cache_dir)
    f1 = tmp_path / "take1.mp4"
    f1.write_text("dummy video content")

    fp_base = cache.compute_fingerprint("seg1", [f1], {"delay": 1000})
    fp_changed = cache.compute_fingerprint("seg1", [f1], {"delay": 1050})

    assert fp_base != fp_changed, "Modifying a parameter must invalidate the fingerprint"


def test_fingerprint_invalidation_on_file_change(test_cache_dir, tmp_path):
    cache = SegmentCache(test_cache_dir)
    f1 = tmp_path / "take1.mp4"
    f1.write_text("original content")

    fp_initial = cache.compute_fingerprint("seg1", [f1], {"x": 10})

    # Modify file content and size
    time.sleep(0.01)
    f1.write_text("modified content with different length")

    fp_updated = cache.compute_fingerprint("seg1", [f1], {"x": 10})
    assert fp_initial != fp_updated, "Modifying input file must invalidate the fingerprint"


def test_cache_hit_and_miss_lifecycle(test_cache_dir, tmp_path):
    pipeline = SegmentPipeline("test_reel", cache_dir=test_cache_dir)
    dummy_input = tmp_path / "input.mp4"
    dummy_input.write_text("sample input")

    call_count = 0

    def mock_render(out_p: Path):
        nonlocal call_count
        call_count += 1
        # Create valid non-empty file (> 1024 bytes)
        out_p.write_bytes(b"A" * 2048)

    pipeline.register(
        segment_id="seg_test",
        description="Test Segment",
        inputs=[dummy_input],
        params={"vol": 1.0},
        render_fn=mock_render,
        expected_duration=4.0,
    )

    # 1. First run: Cache miss -> render_fn executes
    out1, was_hit1, t1 = pipeline.run_segment("seg_test")
    assert was_hit1 is False
    assert call_count == 1
    assert out1.is_file()
    assert out1.stat().st_size == 2048

    # Sidecar meta should exist
    meta_file = test_cache_dir / "seg_test.meta.json"
    assert meta_file.is_file()
    with open(meta_file) as f:
        meta = json.load(f)
        assert meta["segment_id"] == "seg_test"
        assert meta["params"]["vol"] == 1.0

    # 2. Second run: Cache hit -> render_fn skipped, 0ms overhead
    out2, was_hit2, t2 = pipeline.run_segment("seg_test")
    assert was_hit2 is True
    assert t2 == 0.0
    assert call_count == 1
    assert out1 == out2

    # 3. Third run with force: Bypasses cache -> render_fn executes again
    out3, was_hit3, t3 = pipeline.run_segment("seg_test", force=True)
    assert was_hit3 is False
    assert call_count == 2


def test_clean_purges_cache(test_cache_dir):
    pipeline = SegmentPipeline("test_reel", cache_dir=test_cache_dir)
    seg_mp4 = test_cache_dir / "seg1.mp4"
    seg_meta = test_cache_dir / "seg1.meta.json"
    seg_mp4.write_text("data")
    seg_meta.write_text("{}")

    assert seg_mp4.exists()
    pipeline.cache.clean("seg1")
    assert not seg_mp4.exists()
    assert not seg_meta.exists()


def test_selective_single_segment_rendering(test_cache_dir, tmp_path):
    pipeline = SegmentPipeline("test_reel", cache_dir=test_cache_dir)
    executed = []

    def make_renderer(name):
        def _render(out_p: Path):
            executed.append(name)
            out_p.write_bytes(b"V" * 2048)
        return _render

    pipeline.register("segA", "Segment A", [], {}, make_renderer("segA"))
    pipeline.register("segB", "Segment B", [], {}, make_renderer("segB"))
    pipeline.register("segC", "Segment C", [], {}, make_renderer("segC"))

    cli_args = pipeline.parse_args(["--only", "segB"])
    res = pipeline.assemble(
        output_path=tmp_path / "master.mp4",
        cli_args=cli_args,
    )

    assert executed == ["segB"], "Only targeted segment should have been executed"
    assert res == test_cache_dir / "segB.mp4"


def test_full_assembly_concat_with_ffmpeg(test_cache_dir, tmp_path):
    """Generates two short synthetic clips via FFmpeg and tests seamless lossless concatenation."""
    pipeline = SegmentPipeline("test_real_concat", cache_dir=test_cache_dir)

    def render_clip1(out_p: Path):
        # 1-second synthetic 1080x1920 test pattern
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=1.0:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1.0",
            "-c:a", "aac", "-b:a", "128k",
            str(out_p)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    def render_clip2(out_p: Path):
        # 1-second synthetic 1080x1920 test pattern
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=1.0:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1.0",
            "-c:a", "aac", "-b:a", "128k",
            str(out_p)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    pipeline.register("c1", "Red Clip", [], {}, render_clip1, expected_duration=1.0)
    pipeline.register("c2", "Blue Clip", [], {}, render_clip2, expected_duration=1.0)

    master_mp4 = tmp_path / "master_reel.mp4"

    # Pass 1: Fresh render
    res1 = pipeline.assemble(output_path=master_mp4)
    assert res1.is_file()
    assert res1.stat().st_size > 1024

    # Verify duration is ~2.0s
    probe_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(res1)
    ]
    dur = float(subprocess.run(probe_cmd, capture_output=True, text=True, check=True).stdout.strip())
    assert 1.9 <= dur <= 2.1

    # Pass 2: Instant cached concat (0 renders, pure stream copy)
    t0 = time.time()
    res2 = pipeline.assemble(output_path=master_mp4)
    elapsed = time.time() - t0
    assert elapsed < 0.8, f"Cached concat should complete in under 0.8s, got {elapsed:.2f}s"
    assert res2 == res1


def test_code_recipe_invalidation(test_cache_dir, tmp_path):
    """Editing the Python code of render_fn must invalidate cache even with identical parameters."""
    p1 = SegmentPipeline("test_recipe", cache_dir=test_cache_dir)
    p1.register("s1", "Recipe 1", [], {"x": 1}, lambda o: o.write_bytes(b"A" * 2048))
    p1.run_segment("s1")

    # Second pipeline with identical params but different code
    p2 = SegmentPipeline("test_recipe", cache_dir=test_cache_dir)
    p2.register("s1", "Recipe 2", [], {"x": 1}, lambda o: o.write_bytes(b"B" * 2048))
    _, was_hit, _ = p2.run_segment("s1")
    assert was_hit is False, "Modified recipe code must invalidate cache"


def test_targeted_force_single_segment(test_cache_dir, tmp_path):
    """--force <seg_id> must ONLY re-render the targeted segment, leaving other segments cached."""
    pipeline = SegmentPipeline("test_targeted_force", cache_dir=test_cache_dir)
    ran = []

    def make_fn(sid):
        def _render(out_p: Path):
            ran.append(sid)
            # Create synthetic 1s clip
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=green:s=320x240:d=0.5:r=30",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.5",
                "-c:a", "aac", str(out_p)
            ]
            subprocess.run(cmd, check=True)
        return _render

    for sid in ["s1", "s2", "s3"]:
        pipeline.register(sid, f"Segment {sid}", [], {}, make_fn(sid))

    master = tmp_path / "master.mp4"
    pipeline.assemble(master)
    assert set(ran) == {"s1", "s2", "s3"}

    # Run with --force s2
    ran.clear()
    args = pipeline.parse_args(["--force", "s2"])
    pipeline.assemble(master, cli_args=args)
    assert ran == ["s2"], f"Only s2 should be re-rendered, got: {ran}"


def test_apostrophe_in_cache_path(tmp_path):
    """Paths containing single quotes / apostrophes must not break FFmpeg concat demuxer."""
    cache_d = tmp_path / "Jake's cache"
    pipeline = SegmentPipeline("test_apostrophe", cache_dir=cache_d)

    def render_clip(out_p: Path):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=320x240:d=0.5:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.5",
            "-c:a", "aac", str(out_p)
        ]
        subprocess.run(cmd, check=True)

    pipeline.register("s1", "Clip 1", [], {}, render_clip)
    pipeline.register("s2", "Clip 2", [], {}, render_clip)

    out = pipeline.assemble(tmp_path / "out.mp4")
    assert out.is_file()
    assert out.stat().st_size > 1024


def test_mismatched_resolution_fails_loudly(test_cache_dir, tmp_path):
    """Mismatched video dimensions must fail loudly before running -c copy concat."""
    pipeline = SegmentPipeline("test_mismatch", cache_dir=test_cache_dir)

    def render_small(out_p: Path):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=320x240:d=0.5:r=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.5",
            "-an", str(out_p)
        ]
        subprocess.run(cmd, check=True)

    def render_large(out_p: Path):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=640x480:d=0.5:r=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.5",
            "-an", str(out_p)
        ]
        subprocess.run(cmd, check=True)

    pipeline.register("s1", "Small Clip", [], {}, render_small)
    pipeline.register("s2", "Large Clip", [], {}, render_large)

    with pytest.raises(RuntimeError, match="Lossless stream-copy concat requires identical dimensions"):
        pipeline.assemble(tmp_path / "bad.mp4")


def test_invalid_segment_id_raises(test_cache_dir):
    """Segment IDs with invalid characters or directory traversal attempts must raise ValueError."""
    pipeline = SegmentPipeline("test_ids", cache_dir=test_cache_dir)
    with pytest.raises(ValueError, match="Invalid segment_id"):
        pipeline.register("bad/id", "Bad", [], {}, lambda o: None)
    with pytest.raises(ValueError, match="Invalid segment_id"):
        pipeline.register("../escape", "Escape", [], {}, lambda o: None)


def test_merkle_dag_cascade(test_cache_dir, tmp_path):
    """Modifying an upstream parent input file must cascade and invalidate dependent child segments."""
    pipeline = SegmentPipeline("test_dag", cache_dir=test_cache_dir)
    raw_take = tmp_path / "take.mp4"
    raw_take.write_text("initial raw take bytes")

    run_counts = {"parent": 0, "child": 0}

    def render_parent(out_p: Path):
        run_counts["parent"] += 1
        out_p.write_bytes(b"PARENT" * 500)

    def render_child(out_p: Path):
        run_counts["child"] += 1
        out_p.write_bytes(b"CHILD" * 500)

    pipeline.register(
        "seg_parent", "Parent Clip", inputs=[raw_take], params={"speed": 1.0}, render_fn=render_parent
    )
    pipeline.register(
        "seg_child", "Child Montage", inputs=[], params={"montage": True},
        dependencies=["seg_parent"], render_fn=render_child
    )

    # Initial run: both render
    pipeline.run_segment("seg_parent")
    pipeline.run_segment("seg_child")
    assert run_counts["parent"] == 1
    assert run_counts["child"] == 1

    # Second run: both cached
    pipeline.run_segment("seg_parent")
    pipeline.run_segment("seg_child")
    assert run_counts["parent"] == 1
    assert run_counts["child"] == 1

    # Invalidate parent input file
    time.sleep(0.01)
    raw_take.write_text("updated take bytes with different content and length")

    # Check that child is dirty because parent's fingerprint changed
    fp_child_new = pipeline.cache.compute_fingerprint(
        "seg_child", [], {"montage": True}, dependencies=["seg_parent"], pipeline=pipeline
    )
    assert not pipeline.cache.is_cached("seg_child", fp_child_new)

    # Running child re-renders child
    out_c, was_hit_c, _ = pipeline.run_segment("seg_child")
    assert was_hit_c is False
    assert run_counts["child"] == 2

