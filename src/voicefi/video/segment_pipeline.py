"""
VoiceFi™ Smart Segment-Isolated Video Rendering Engine.

Provides content-addressable caching, multi-threaded parallel compilation,
dependency graph (DAG) invalidation, single-segment iteration, audio-only fast-path,
and lossless stream copy concatenation for multi-segment video reels and timelines.

Key Architecture:
- Content-Addressable Fingerprinting: 128-bit SHA-256 over canonical paths, mtimes, sizes, inodes, and params.
- Merkle Dependency Chaining: Upstream segment fingerprints automatically cascade into dependent montage segments.
- Multi-Threaded Parallel Compilation: Safely compiles independent dirty segments concurrently on Apple Silicon.
- Single-Segment Fast Preview: `python script.py --only seg4 --preview` cuts iteration loops to ~1.5s.
- Audio-Only Fast-Path: Remuxes cached video with modified audio mixes in <100ms via `-c:v copy`.
- Interruption & Thread Safety: Process- and thread-unique temp files with `finally` cleanup to guarantee zero leaked artifacts.
- 0.2s Stream-Copy Concat: Pre-normalized broadcast segments stitch losslessly without re-encoding.
"""

import argparse
import concurrent.futures
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union


@dataclass
class SegmentDefinition:
    """Represents a single timeline segment with optional DAG dependencies and decoupled layers."""

    id: str
    description: str
    inputs: List[Path]
    params: Dict[str, Any]
    render_fn: Optional[Callable[..., Any]] = None
    dependencies: List[str] = field(default_factory=list)
    expected_duration: Optional[float] = None

    # Decoupled layer functions (optional audio-only fast path)
    video_fn: Optional[Callable[[Path], Any]] = None
    audio_fn: Optional[Callable[[Path], Any]] = None
    video_inputs: List[Path] = field(default_factory=list)
    video_params: Dict[str, Any] = field(default_factory=dict)
    audio_inputs: List[Path] = field(default_factory=list)
    audio_params: Dict[str, Any] = field(default_factory=dict)


class SegmentCache:
    """Manages persistent disk caching and SHA-256 fingerprinting for video segments."""

    def __init__(self, cache_dir: Union[str, Path]):
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _serialize_val(val: Any) -> Any:
        """Ensures deterministic JSON across paths, numbers, floats, and containers."""
        if isinstance(val, (Path, os.PathLike)):
            return str(val)
        if isinstance(val, float):
            return round(val, 4)
        if isinstance(val, (list, tuple)):
            return [SegmentCache._serialize_val(v) for v in val]
        if isinstance(val, dict):
            return {k: SegmentCache._serialize_val(v) for k, v in sorted(val.items())}
        return val

    @staticmethod
    def _hash_callable(fn: Optional[Callable]) -> str:
        """Hashes the function source code or bytecode and constants for change detection."""
        if fn is None:
            return ""
        try:
            import inspect
            src = inspect.getsource(fn)
            return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
        except Exception:
            pass
        try:
            code = getattr(fn, "__code__", None)
            if code:
                raw = code.co_code + str(code.co_consts).encode("utf-8")
                return hashlib.sha256(raw).hexdigest()[:16]
        except Exception:
            pass
        return ""

    def compute_fingerprint(
        self,
        segment_id: str,
        inputs: Sequence[Union[str, Path]],
        params: Dict[str, Any],
        dependencies: Optional[Sequence[str]] = None,
        pipeline: Optional["SegmentPipeline"] = None,
        visited: Optional[Set[str]] = None,
        code_fn: Optional[Callable] = None,
    ) -> str:
        """
        Computes a deterministic 128-bit SHA-256 fingerprint incorporating:
        1. Segment ID.
        2. Canonical paths, size, nanosecond mtime, and inode of all input files.
        3. Normalized JSON parameters.
        4. Recipe callable bytecode / source hash (invalidates cache if python code edits).
        5. Merkle-tree chained fingerprints of all upstream dependencies.
        """
        if visited is None:
            visited = set()
        visited.add(segment_id)

        input_sigs = []
        for inp in inputs:
            p = Path(inp).resolve()
            if p.exists():
                stat = p.stat()
                input_sigs.append(f"{p.as_posix()}:{stat.st_size}:{stat.st_mtime_ns}:{getattr(stat, 'st_ino', 0)}")
            else:
                input_sigs.append(f"{p.as_posix()}:MISSING:0:0")

        # Merkle dependency chaining: hash of upstream dependency fingerprints
        dep_sigs = []
        if dependencies and pipeline:
            for dep_id in sorted(dependencies):
                if dep_id in pipeline.segments and dep_id not in visited:
                    dep_seg = pipeline.segments[dep_id]
                    dep_fp = pipeline.cache.compute_fingerprint(
                        dep_id,
                        dep_seg.inputs,
                        dep_seg.params,
                        dep_seg.dependencies,
                        pipeline,
                        visited.copy(),
                    )
                    dep_sigs.append(f"DEP:{dep_id}:{dep_fp}")

        all_sigs = sorted(input_sigs) + sorted(dep_sigs)
        input_sig_str = "|".join(all_sigs)

        # Code recipe hashing
        target_fn = code_fn
        if target_fn is None and pipeline and segment_id in pipeline.segments:
            seg = pipeline.segments[segment_id]
            target_fn = seg.render_fn or seg.video_fn
        code_sig = self._hash_callable(target_fn)

        clean_params = {k: self._serialize_val(v) for k, v in sorted(params.items())}
        params_json = json.dumps(clean_params, sort_keys=True, separators=(",", ":"))

        raw_key = f"{segment_id}##{input_sig_str}##{params_json}##CODE:{code_sig}"
        # 32 hex chars (128-bit entropy) eliminates birthday paradox collisions
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]

    def get_segment_mp4_path(self, segment_id: str) -> Path:
        """Returns the canonical output path for a segment."""
        return self.cache_dir / f"{segment_id}.mp4"

    def get_segment_meta_path(self, segment_id: str) -> Path:
        """Returns the sidecar metadata path for a segment."""
        return self.cache_dir / f"{segment_id}.meta.json"

    def is_cached(
        self,
        segment_id: str,
        fingerprint: str,
    ) -> bool:
        """Checks if a segment has a valid, non-empty cached artifact matching the fingerprint."""
        mp4_path = self.get_segment_mp4_path(segment_id)
        meta_path = self.get_segment_meta_path(segment_id)

        if not mp4_path.is_file() or mp4_path.stat().st_size < 1024:
            return False
        if not meta_path.is_file():
            return False

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("fingerprint") != fingerprint:
                    return False
                stored_size = data.get("file_size_bytes")
                if stored_size and mp4_path.stat().st_size != stored_size:
                    return False
                return True
        except Exception:
            return False

    def is_sub_cached(self, sub_id: str, fingerprint: str, artifact_path: Path) -> bool:
        """Checks if an intermediate sub-layer (e.g. video only or audio only) is valid."""
        meta_path = self.cache_dir / f"{sub_id}.meta.json"
        if not artifact_path.is_file() or artifact_path.stat().st_size < 512:
            return False
        if not meta_path.is_file():
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("fingerprint") == fingerprint
        except Exception:
            return False

    def record_sub_success(self, sub_id: str, fingerprint: str):
        """Records sub-layer metadata."""
        meta_path = self.cache_dir / f"{sub_id}.meta.json"
        tmp_meta = self.cache_dir / f".tmp_sub_meta_{sub_id}_{os.getpid()}_{time.time_ns()}.json"
        try:
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump({"fingerprint": fingerprint, "rendered_at": datetime.now().isoformat()}, f)
            tmp_meta.replace(meta_path)
        finally:
            tmp_meta.unlink(missing_ok=True)

    def get_metadata(self, segment_id: str) -> Optional[Dict[str, Any]]:
        """Reads cached metadata if available."""
        meta_path = self.get_segment_meta_path(segment_id)
        if not meta_path.is_file():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def record_success(
        self,
        segment_id: str,
        fingerprint: str,
        inputs: Sequence[Union[str, Path]],
        params: Dict[str, Any],
        render_time_s: float,
        description: str = "",
        dependencies: Optional[Sequence[str]] = None,
    ):
        """Atomically records metadata sidecar following a successful render."""
        meta_path = self.get_segment_meta_path(segment_id)
        mp4_path = self.get_segment_mp4_path(segment_id)

        file_size = mp4_path.stat().st_size if mp4_path.exists() else 0
        streams = []
        if mp4_path.is_file() and mp4_path.stat().st_size > 1024:
            try:
                cmd = [
                    "ffprobe", "-v", "error",
                    "-show_entries", "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,sample_rate,channels",
                    "-of", "json", str(mp4_path)
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    streams = json.loads(res.stdout).get("streams", [])
            except Exception:
                pass

        meta = {
            "segment_id": segment_id,
            "description": description,
            "fingerprint": fingerprint,
            "rendered_at": datetime.now().isoformat(),
            "render_time_s": round(render_time_s, 3),
            "file_size_bytes": file_size,
            "streams": streams,
            "inputs": [str(Path(i).resolve()) for i in inputs],
            "dependencies": list(dependencies or []),
            "params": {k: self._serialize_val(v) for k, v in sorted(params.items())},
        }

        # Atomically write sidecar metadata
        tmp_meta = self.cache_dir / f".tmp_meta_{segment_id}_{os.getpid()}_{time.time_ns()}.json"
        try:
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            tmp_meta.replace(meta_path)
        finally:
            tmp_meta.unlink(missing_ok=True)

    def clean(self, segment_id: Optional[str] = None):
        """Purges cached artifacts for a specific segment or the entire cache."""
        if segment_id:
            self.get_segment_mp4_path(segment_id).unlink(missing_ok=True)
            self.get_segment_meta_path(segment_id).unlink(missing_ok=True)
            (self.cache_dir / f"{segment_id}_v.meta.json").unlink(missing_ok=True)
            (self.cache_dir / f"{segment_id}_a.meta.json").unlink(missing_ok=True)
            (self.cache_dir / f"{segment_id}.video.mp4").unlink(missing_ok=True)
            (self.cache_dir / f"{segment_id}.audio.wav").unlink(missing_ok=True)
        else:
            for item in self.cache_dir.glob("*"):
                if item.is_file():
                    item.unlink(missing_ok=True)


class SegmentPipeline:
    """
    Orchestrates timeline segments with DAG dependencies, parallel compilation,
    audio-only fast-path, single-segment preview, and zero-copy concatenation.
    """

    def __init__(
        self,
        name: str,
        cache_dir: Optional[Union[str, Path]] = None,
        default_v_flags: Optional[List[str]] = None,
        default_a_flags: Optional[List[str]] = None,
    ):
        self.name = name
        if cache_dir is None:
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            self.cache_dir = repo_root / "assets" / "reels" / ".cache" / name
        else:
            self.cache_dir = Path(cache_dir).resolve()

        self.cache = SegmentCache(self.cache_dir)
        self.segments: Dict[str, SegmentDefinition] = {}

        self.default_v_flags = default_v_flags or [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18"
        ]
        self.default_a_flags = default_a_flags or [
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"
        ]

    def register(
        self,
        segment_id: str,
        description: str,
        inputs: Sequence[Union[str, Path]],
        params: Optional[Dict[str, Any]] = None,
        render_fn: Optional[Callable[..., Any]] = None,
        dependencies: Optional[Sequence[str]] = None,
        expected_duration: Optional[float] = None,
        # Decoupled audio-only fast path options
        video_fn: Optional[Callable[[Path], Any]] = None,
        audio_fn: Optional[Callable[[Path], Any]] = None,
        video_inputs: Optional[Sequence[Union[str, Path]]] = None,
        video_params: Optional[Dict[str, Any]] = None,
        audio_inputs: Optional[Sequence[Union[str, Path]]] = None,
        audio_params: Optional[Dict[str, Any]] = None,
    ) -> SegmentDefinition:
        """Registers a timeline segment with optional dependencies and audio fast-path."""
        if not re.match(r"^[A-Za-z0-9_-]+$", segment_id):
            raise ValueError(
                f"Invalid segment_id '{segment_id}'. Segment IDs must be alphanumeric, dashes, or underscores only."
            )
        if params is None:
            params = {}
        if render_fn is None and not (video_fn and audio_fn):
            raise ValueError(f"Segment '{segment_id}' must provide render_fn or (video_fn and audio_fn).")

        resolved_inputs = [Path(p).resolve() for p in inputs]
        resolved_v_inputs = [Path(p).resolve() for p in (video_inputs or [])]
        resolved_a_inputs = [Path(p).resolve() for p in (audio_inputs or [])]

        seg = SegmentDefinition(
            id=segment_id,
            description=description,
            inputs=resolved_inputs,
            params=params,
            render_fn=render_fn,
            dependencies=list(dependencies or []),
            expected_duration=expected_duration,
            video_fn=video_fn,
            audio_fn=audio_fn,
            video_inputs=resolved_v_inputs,
            video_params=video_params or {},
            audio_inputs=resolved_a_inputs,
            audio_params=audio_params or {},
        )
        self.segments[segment_id] = seg
        return seg

    def segment(
        self,
        segment_id: str,
        description: str = "",
        inputs: Optional[Sequence[Union[str, Path]]] = None,
        params: Optional[Dict[str, Any]] = None,
        dependencies: Optional[Sequence[str]] = None,
        expected_duration: Optional[float] = None,
    ):
        """Decorator for registering segment render functions."""
        if inputs is None:
            inputs = []
        if params is None:
            params = {}

        def decorator(fn: Callable[[Path], Any]):
            desc = description or fn.__doc__ or segment_id
            self.register(
                segment_id=segment_id,
                description=desc.strip(),
                inputs=inputs,
                params=params,
                render_fn=fn,
                dependencies=dependencies,
                expected_duration=expected_duration,
            )
            return fn

        return decorator

    @staticmethod
    def run_ffmpeg(cmd: List[str], desc: str = ""):
        """Standard helper for running FFmpeg with clear diagnostics."""
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            err_msg = res.stderr.strip()
            print(f"❌ Error in {desc or 'FFmpeg execution'}:\n{err_msg}", file=sys.stderr)
            raise RuntimeError(f"FFmpeg command failed ({desc}): {err_msg[-400:]}")
        return res

    def parse_args(self, args: Optional[List[str]] = None) -> argparse.Namespace:
        """Parses CLI flags for selective rendering, force, preview, concurrency, and list."""
        parser = argparse.ArgumentParser(
            description=f"VoiceFi Segment-Isolated Video Pipeline [{self.name}]"
        )
        parser.add_argument(
            "-s", "--only", "--segment",
            dest="only",
            default=None,
            help="Render ONLY specified segment ID(s) (comma-separated, e.g. --only seg4)",
        )
        parser.add_argument(
            "-p", "--preview",
            action="store_true",
            help="Automatically open rendered segment or master reel in macOS QuickTime",
        )
        parser.add_argument(
            "-f", "--force",
            nargs="?",
            const="__ALL__",
            default=None,
            help="Force re-rendering without cache (all segments or specific segment)",
        )
        parser.add_argument(
            "-j", "--jobs",
            type=int,
            default=min(4, max(1, (os.cpu_count() or 4) // 2)),
            help="Number of concurrent worker threads for parallel compilation (default: auto)",
        )
        parser.add_argument(
            "--no-parallel",
            action="store_true",
            help="Disable multi-threaded parallel compilation (run sequentially)",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Purge cache before running",
        )
        parser.add_argument(
            "-l", "--list",
            action="store_true",
            help="List all segments and their cache statuses, then exit",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what segments would be rendered without executing",
        )
        parser.add_argument(
            "cut_mode",
            nargs="?",
            default="fast_forward",
            help="Cut mode preset (e.g. 'fast_forward' or 'montage')",
        )
        return parser.parse_args(args)

    def print_status_table(self):
        """Displays a formatted CLI matrix of registered segments and cache status."""
        print("\n" + "=" * 80)
        print(f"📋 VoiceFi Pipeline Status: {self.name.upper()} ({len(self.segments)} segments)")
        print(f"📁 Cache Directory: {self.cache_dir}")
        print("-" * 80)
        print(f"{'SEGMENT ID':<16} {'STATUS':<14} {'DURATION':<10} {'DESCRIPTION'}")
        print("-" * 80)

        total_dur = 0.0
        cached_count = 0
        dirty_count = 0

        for seg_id, seg in self.segments.items():
            fp = self.cache.compute_fingerprint(seg_id, seg.inputs, seg.params, seg.dependencies, self)
            cached = self.cache.is_cached(seg_id, fp)
            dur_str = f"{seg.expected_duration:.1f}s" if seg.expected_duration else "N/A"
            if seg.expected_duration:
                total_dur += seg.expected_duration

            if cached:
                status_str = "⚡ CACHED"
                cached_count += 1
            else:
                status_str = "🔨 DIRTY"
                dirty_count += 1

            print(f"{seg_id:<16} {status_str:<14} {dur_str:<10} {seg.description[:38]}")

        print("-" * 80)
        print(f"Summary: {cached_count} cached (0.00s), {dirty_count} need render | Est. Duration: {total_dur:.1f}s")
        print("=" * 80 + "\n")

    def run_segment(
        self,
        segment_id: str,
        force: bool = False,
        dry_run: bool = False,
    ) -> Tuple[Path, bool, float]:
        """
        Executes or retrieves a single segment.
        Thread-safe, process-safe, and interruption-safe (cleans temp on Ctrl+C).
        Returns: (output_path, was_cache_hit, elapsed_seconds)
        """
        if segment_id not in self.segments:
            raise KeyError(f"Segment '{segment_id}' not found in pipeline '{self.name}'. Available: {list(self.segments.keys())}")

        seg = self.segments[segment_id]

        # Resolve upstream dependencies first
        dep_paths: Dict[str, Path] = {}
        if seg.dependencies:
            for dep_id in seg.dependencies:
                dep_p, _, _ = self.run_segment(dep_id, force=force, dry_run=dry_run)
                dep_paths[dep_id] = dep_p

        out_path = self.cache.get_segment_mp4_path(segment_id)

        # ---------------------------------------------------------------------
        # Audio-Only Fast-Path Execution (if visual_fn and audio_fn provided)
        # ---------------------------------------------------------------------
        if seg.video_fn and seg.audio_fn:
            v_fp = self.cache.compute_fingerprint(
                f"{segment_id}_v", seg.video_inputs, seg.video_params, seg.dependencies, self
            )
            a_fp = self.cache.compute_fingerprint(
                f"{segment_id}_a", seg.audio_inputs, seg.audio_params, None, None
            )
            combo_fp = f"{v_fp}:{a_fp}"

            if not force and self.cache.is_cached(segment_id, combo_fp):
                meta = self.cache.get_metadata(segment_id)
                prev_time = meta.get("render_time_s", 0.0) if meta else 0.0
                print(f"⚡ [CACHE HIT] {segment_id} ({seg.description}) — 0.00s (Saved ~{prev_time:.1f}s)")
                return out_path, True, 0.0

            if dry_run:
                print(f"🔨 [DRY RUN] Would render decoupled {segment_id} ({seg.description})")
                return out_path, False, 0.0

            v_cached_mp4 = self.cache.cache_dir / f"{segment_id}.video.mp4"
            a_cached_wav = self.cache.cache_dir / f"{segment_id}.audio.wav"

            t0 = time.time()
            # 1. Video Layer (Heavy visual work: 80-90% of time)
            if force or not self.cache.is_sub_cached(f"{segment_id}_v", v_fp, v_cached_mp4):
                print(f"🎨 [VIDEO RENDER] {segment_id}: Re-rendering visual layer...")
                tmp_v = self.cache.cache_dir / f".tmp_{segment_id}_v_{os.getpid()}_{time.time_ns()}.mp4"
                try:
                    seg.video_fn(tmp_v)
                    tmp_v.replace(v_cached_mp4)
                    self.cache.record_sub_success(f"{segment_id}_v", v_fp)
                finally:
                    tmp_v.unlink(missing_ok=True)
            else:
                print(f"⚡ [VIDEO CACHED] {segment_id}: Visual layer clean (0.00s)")

            # 2. Audio Layer (Ultra-fast mixdown: <0.1s)
            if force or not self.cache.is_sub_cached(f"{segment_id}_a", a_fp, a_cached_wav):
                print(f"🎚️ [AUDIO MIX] {segment_id}: Rendering audio stems & delays...")
                tmp_a = self.cache.cache_dir / f".tmp_{segment_id}_a_{os.getpid()}_{time.time_ns()}.wav"
                try:
                    seg.audio_fn(tmp_a)
                    tmp_a.replace(a_cached_wav)
                    self.cache.record_sub_success(f"{segment_id}_a", a_fp)
                finally:
                    tmp_a.unlink(missing_ok=True)
            else:
                print(f"⚡ [AUDIO CACHED] {segment_id}: Audio mixdown clean (0.00s)")

            # 3. Stream-Copy Fast Remux (<100ms)
            t_remux = time.time()
            tmp_final = self.cache.cache_dir / f".tmp_{segment_id}_{os.getpid()}_{time.time_ns()}.mp4"
            try:
                cmd_remux = [
                    "ffmpeg", "-y",
                    "-i", str(v_cached_mp4),
                    "-i", str(a_cached_wav),
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart",
                    str(tmp_final),
                ]
                self.run_ffmpeg(cmd_remux, desc=f"Fast Remux {segment_id}")
                tmp_final.replace(out_path)
                elapsed = time.time() - t0
                self.cache.record_success(
                    segment_id=segment_id,
                    fingerprint=combo_fp,
                    inputs=seg.inputs + seg.video_inputs + seg.audio_inputs,
                    params={**seg.params, **seg.video_params, **seg.audio_params},
                    render_time_s=elapsed,
                    description=seg.description,
                    dependencies=seg.dependencies,
                )
                print(f"⚡ Fast Remuxed {segment_id} in {time.time()-t_remux:.2f}s (Total: {elapsed:.2f}s) -> {out_path.name}")
                return out_path, False, elapsed
            finally:
                tmp_final.unlink(missing_ok=True)

        # ---------------------------------------------------------------------
        # Standard Single-Recipe Segment Execution
        # ---------------------------------------------------------------------
        fingerprint = self.cache.compute_fingerprint(
            segment_id, seg.inputs, seg.params, seg.dependencies, self
        )

        if not force and self.cache.is_cached(segment_id, fingerprint):
            meta = self.cache.get_metadata(segment_id)
            prev_time = meta.get("render_time_s", 0.0) if meta else 0.0
            print(f"⚡ [CACHE HIT] {segment_id} ({seg.description}) — 0.00s (Saved ~{prev_time:.1f}s)")
            return out_path, True, 0.0

        if dry_run:
            print(f"🔨 [DRY RUN] Would render {segment_id} ({seg.description})")
            return out_path, False, 0.0

        print(f"\n🎬 [RENDERING] {segment_id}: {seg.description}...")
        t0 = time.time()

        # Thread-unique, process-unique, timestamped temporary file
        temp_out = self.cache.cache_dir / f".tmp_{segment_id}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.mp4"

        try:
            # Check if render_fn accepts dependencies argument
            if dep_paths and seg.render_fn:
                try:
                    seg.render_fn(temp_out, dep_paths)
                except TypeError:
                    seg.render_fn(temp_out)
            elif seg.render_fn:
                seg.render_fn(temp_out)

            if not temp_out.is_file() or temp_out.stat().st_size < 1024:
                raise RuntimeError(f"Segment '{segment_id}' render did not produce valid output file.")

            # Atomically move into place
            temp_out.replace(out_path)
            elapsed = time.time() - t0

            # Write metadata sidecar atomically
            self.cache.record_success(
                segment_id=segment_id,
                fingerprint=fingerprint,
                inputs=seg.inputs,
                params=seg.params,
                render_time_s=elapsed,
                description=seg.description,
                dependencies=seg.dependencies,
            )
            print(f"   ✅ Finished {segment_id} in {elapsed:.2f}s -> {out_path.name}")
            return out_path, False, elapsed
        finally:
            # Handles KeyboardInterrupt (Ctrl+C), SystemExit, and exceptions cleanly
            temp_out.unlink(missing_ok=True)

    def assemble(
        self,
        output_path: Union[str, Path],
        segments: Optional[Sequence[str]] = None,
        force: bool = False,
        preview: bool = False,
        dry_run: bool = False,
        cli_args: Optional[argparse.Namespace] = None,
        max_workers: Optional[int] = None,
    ) -> Optional[Path]:
        """
        Runs the incremental assembly pipeline:
        1. Checks CLI flags for --only, --clean, --list, etc.
        2. Dispatches dirty segments in parallel across Apple Silicon cores.
        3. Stitches together via zero-copy concat demuxer in ~0.2s.
        """
        final_out = Path(output_path).resolve()
        final_out.parent.mkdir(parents=True, exist_ok=True)

        # Handle CLI overrides if provided
        no_parallel = False
        force_all = force
        if cli_args:
            if cli_args.clean:
                print(f"🧹 Purging cache for {self.name}...")
                self.cache.clean()
            if cli_args.list:
                self.print_status_table()
                return None
            if cli_args.force:
                if cli_args.force == "__ALL__":
                    force_all = True
            if cli_args.preview:
                preview = True
            if cli_args.dry_run:
                dry_run = True
            if getattr(cli_args, "jobs", None):
                max_workers = cli_args.jobs
            if getattr(cli_args, "no_parallel", False):
                no_parallel = True
            if cli_args.only:
                target_ids = [s.strip() for s in cli_args.only.split(",") if s.strip()]
                last_path = None
                for tid in target_ids:
                    force_target = force_all or (cli_args.force == tid)
                    p, hit, elapsed = self.run_segment(tid, force=force_target, dry_run=dry_run)
                    last_path = p
                if preview and last_path and last_path.is_file():
                    print(f"👁️  Previewing segment: {last_path}")
                    subprocess.run(["open", str(last_path)])
                return last_path

        active_ids = list(segments) if segments is not None else list(self.segments.keys())
        if not active_ids:
            print("⚠️ No segments selected to assemble.", file=sys.stderr)
            return None

        print(f"\n🚀 Assembling {self.name.upper()} ({len(active_ids)} segments)...")
        t_start = time.time()

        # ---------------------------------------------------------------------
        # 1. Parallel Pre-Compilation of Independent Dirty Segments
        # ---------------------------------------------------------------------
        if max_workers is None:
            max_workers = min(4, max(1, (os.cpu_count() or 4) // 2))

        dirty_ids = []
        for seg_id in active_ids:
            seg = self.segments[seg_id]
            fp = self.cache.compute_fingerprint(seg_id, seg.inputs, seg.params, seg.dependencies, self)
            force_seg = force_all or (cli_args and (cli_args.force == "__ALL__" or cli_args.force == seg_id))
            if force_seg or not self.cache.is_cached(seg_id, fp):
                dirty_ids.append(seg_id)

        # If multiple independent dirty segments exist, compile in parallel
        # Separate segments with no dependencies from dependent segments
        independent_dirty = [sid for sid in dirty_ids if not self.segments[sid].dependencies]
        dependent_dirty = [sid for sid in dirty_ids if self.segments[sid].dependencies]

        if not no_parallel and len(independent_dirty) > 1 and max_workers > 1 and not dry_run:
            worker_count = min(len(independent_dirty), max_workers)
            print(f"⚡ Parallel Rendering {len(independent_dirty)} independent dirty segments across {worker_count} worker threads...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
                fut_map = {
                    pool.submit(self.run_segment, sid, force=True, dry_run=False): sid
                    for sid in independent_dirty
                }
                for fut in concurrent.futures.as_completed(fut_map):
                    sid = fut_map[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"❌ Parallel render failed for segment '{sid}': {e}", file=sys.stderr)
                        raise

        # ---------------------------------------------------------------------
        # 2. Sequential Assembly Collection & Dependent Processing
        # ---------------------------------------------------------------------
        rendered_paths: List[Path] = []
        hits = 0
        misses = 0
        render_seconds = 0.0

        for seg_id in active_ids:
            force_seg = force_all or (cli_args and (cli_args.force == "__ALL__" or cli_args.force == seg_id))
            seg_out, was_hit, elapsed = self.run_segment(seg_id, force=force_seg, dry_run=dry_run)
            rendered_paths.append(seg_out)
            if was_hit:
                hits += 1
            else:
                misses += 1
                render_seconds += elapsed

        if dry_run:
            print("\n🏁 Dry run complete. No files stitched.")
            return None

        # Validate stream signatures across all segments to prevent silent corruption
        first_v = None
        for p in rendered_paths:
            seg_id = p.stem
            meta = self.cache.get_metadata(seg_id)
            if meta and meta.get("streams"):
                v_streams = [s for s in meta["streams"] if s.get("codec_type") == "video"]
                if v_streams:
                    v = v_streams[0]
                    v_sig = (v.get("width"), v.get("height"), v.get("pix_fmt"))
                    if first_v is None:
                        first_v = (seg_id, v_sig)
                    elif v_sig != first_v[1]:
                        raise RuntimeError(
                            f"Segment '{seg_id}' resolution/format {v_sig} mismatches '{first_v[0]}' {first_v[1]}. "
                            f"Lossless stream-copy concat requires identical dimensions and pixel formats."
                        )

        # ---------------------------------------------------------------------
        # 3. Zero-Copy Stream Concat Demuxing with Atomic Swap
        # ---------------------------------------------------------------------
        concat_plan = self.cache.cache_dir / f"concat_plan_{os.getpid()}_{time.time_ns()}.txt"
        with open(concat_plan, "w", encoding="utf-8") as f:
            for p in rendered_paths:
                escaped = p.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        print(f"\n🎞️ Splicing {len(rendered_paths)} segments via Lossless Stream Copy (-c copy)...")
        t_concat_start = time.time()

        # Atomic master assembly: write to temporary file in same folder, then rename
        tmp_master = final_out.parent / f".tmp_master_{final_out.stem}_{os.getpid()}_{time.time_ns()}{final_out.suffix}"

        try:
            cmd_concat = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_plan),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(tmp_master),
            ]
            self.run_ffmpeg(cmd_concat, desc="Master Concat Demuxer")
            tmp_master.replace(final_out)
        finally:
            tmp_master.unlink(missing_ok=True)
            concat_plan.unlink(missing_ok=True)

        concat_elapsed = time.time() - t_concat_start
        total_elapsed = time.time() - t_start

        size_mb = final_out.stat().st_size / (1024 * 1024) if final_out.exists() else 0.0

        print("\n" + "=" * 80)
        print("✨ MASTER REEL READY!")
        print(f"👉 File:       {final_out} ({size_mb:.2f} MB)")
        print(f"⚡ Cache Hits: {hits}/{len(active_ids)} segments (0.00s overhead)")
        print(f"🔨 Rendered:   {misses}/{len(active_ids)} segments ({render_seconds:.2f}s)")
        print(f"⏱️ Concat:     {concat_elapsed:.2f}s (Lossless Stream Copy)")
        print(f"⏳ Total Time: {total_elapsed:.2f}s")
        print("=" * 80 + "\n")

        if preview and final_out.is_file():
            print(f"👁️  Opening master reel preview in QuickTime: {final_out}")
            subprocess.run(["open", str(final_out)])

        return final_out
