"""
Data models and storage manager for Voice Memo Buffer.
Preserves developer thought fidelity with zero interpretation and light cleanup.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid
from pydantic import BaseModel, Field


def get_memos_dir() -> Path:
    """Return the root directory for voice memos (~/.voicefi/memos)."""
    m_dir = Path.home() / ".voicefi" / "memos"
    m_dir.mkdir(parents=True, exist_ok=True)
    return m_dir


def format_duration(seconds: float) -> str:
    """Format seconds into MM:SS."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


class MemoChunk(BaseModel):
    """Timestamped audio or transcription chunk."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str = ""


class MemoRecording(BaseModel):
    """Metadata for a raw voice memo recording session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = "Voice Memo"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_seconds: float = 0.0
    target_duration_seconds: float = 180.0
    audio_path: Optional[str] = None
    raw_transcript: str = ""
    word_count: int = 0
    chunks: List[MemoChunk] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


# Deprecated / backwards-compatible stubs for previous plan structures
class ProposedFileChange(BaseModel):
    action: str = "MODIFY"
    path: str
    description: str = ""


class ImplementationStep(BaseModel):
    step_number: int
    title: str
    details: str
    target_files: List[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    goal_summary: str = ""
    problem_context: str = ""
    architectural_decisions: List[str] = Field(default_factory=list)
    proposed_files: List[ProposedFileChange] = Field(default_factory=list)
    steps: List[ImplementationStep] = Field(default_factory=list)


class ArchitecturalDiagram(BaseModel):
    diagram_type: str = "graph TD"
    mermaid_code: str = ""
    description: str = ""


class PRChecklist(BaseModel):
    core_tasks: List[str] = Field(default_factory=list)
    testing_and_verification: List[str] = Field(default_factory=list)
    edge_cases_and_security: List[str] = Field(default_factory=list)
    documentation_and_ops: List[str] = Field(default_factory=list)


class CleanedMemo(BaseModel):
    """Cleaned voice memo capturing developer stream of consciousness without interpretation."""

    memo_id: str
    title: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_seconds: float = 0.0
    raw_transcript: str = ""
    cleaned_transcript: str = ""
    word_count: int = 0
    tags: List[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render clean, faithful developer memo document."""
        lines = []
        lines.append(f"# 🎙️ Voice Memo: {self.title}")
        lines.append(
            f"*Captured: {self.created_at[:19].replace('T', ' ')} UTC* | *Duration: {format_duration(self.duration_seconds)}* | *Words: {self.word_count}* | *ID: `{self.memo_id}`*"
        )
        lines.append("")
        lines.append("## 📝 Cleaned Transcript")
        lines.append(self.cleaned_transcript or self.raw_transcript or "_No speech recorded._")
        lines.append("")
        lines.append("---")
        lines.append("## 🎙️ Raw Voice Transcript")
        lines.append("<details>")
        lines.append("<summary>Click to expand verbatim raw transcript</summary>\n")
        lines.append(f"> {self.raw_transcript or '_Empty_'}")
        lines.append("\n</details>")
        return "\n".join(lines)


# Backwards compatibility alias
SynthesizedMemo = CleanedMemo


class MemoStore:
    """Persistent storage manager for voice memos and transcripts."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or get_memos_dir()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_memo(self, recording: MemoRecording, memo: Optional[CleanedMemo] = None) -> Path:
        """Save a recording and cleaned memo to disk."""
        memo_dir = self.root_dir / recording.id
        memo_dir.mkdir(parents=True, exist_ok=True)

        rec_path = memo_dir / "recording.json"
        with open(rec_path, "w", encoding="utf-8") as f:
            f.write(recording.model_dump_json(indent=2))

        if memo:
            memo_path = memo_dir / "memo.json"
            with open(memo_path, "w", encoding="utf-8") as f:
                f.write(memo.model_dump_json(indent=2))

            # Also write synthesis.json for backward compatibility
            synth_path = memo_dir / "synthesis.json"
            with open(synth_path, "w", encoding="utf-8") as f:
                f.write(memo.model_dump_json(indent=2))

            md_path = memo_dir / "memo.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(memo.to_markdown())

            # Also keep plan.md as compatibility alias
            plan_path = memo_dir / "plan.md"
            with open(plan_path, "w", encoding="utf-8") as f:
                f.write(memo.to_markdown())

        return memo_dir

    def get_memo(self, memo_id: str) -> Optional[tuple[MemoRecording, Optional[CleanedMemo]]]:
        """Load a memo recording and cleaned memo by ID."""
        memo_dir = self.root_dir / memo_id
        if not memo_dir.is_dir():
            # Try finding by prefix
            matches = list(self.root_dir.glob(f"{memo_id}*"))
            if matches and matches[0].is_dir():
                memo_dir = matches[0]
            else:
                return None

        rec_path = memo_dir / "recording.json"
        if not rec_path.is_file():
            return None

        with open(rec_path, "r", encoding="utf-8") as f:
            rec_data = json.load(f)
        recording = MemoRecording(**rec_data)

        memo_path = memo_dir / "memo.json"
        if not memo_path.is_file():
            memo_path = memo_dir / "synthesis.json"

        memo = None
        if memo_path.is_file():
            with open(memo_path, "r", encoding="utf-8") as f:
                memo_data = json.load(f)
            # Handle possible legacy structure gracefully
            cleaned_t = (
                memo_data.get("cleaned_transcript")
                or memo_data.get("executive_summary")
                or memo_data.get("raw_transcript", "")
            )
            memo = CleanedMemo(
                memo_id=memo_data.get("memo_id", recording.id),
                title=memo_data.get("title", recording.title),
                created_at=memo_data.get("created_at", recording.created_at),
                duration_seconds=memo_data.get("duration_seconds", recording.duration_seconds),
                raw_transcript=memo_data.get("raw_transcript", recording.raw_transcript),
                cleaned_transcript=cleaned_t,
                word_count=memo_data.get("word_count", recording.word_count),
                tags=memo_data.get("tags", recording.tags),
            )

        return recording, memo

    def list_memos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all saved memos ordered by creation timestamp (newest first)."""
        results = []
        for memo_dir in self.root_dir.iterdir():
            if not memo_dir.is_dir():
                continue
            rec_path = memo_dir / "recording.json"
            if rec_path.is_file():
                try:
                    with open(rec_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    has_memo = (memo_dir / "memo.json").is_file() or (
                        memo_dir / "synthesis.json"
                    ).is_file()
                    results.append(
                        {
                            "id": data.get("id", memo_dir.name),
                            "title": data.get("title", "Voice Memo"),
                            "created_at": data.get("created_at", ""),
                            "duration_seconds": data.get("duration_seconds", 0.0),
                            "word_count": data.get("word_count", 0),
                            "has_cleaned_memo": has_memo,
                            "has_synthesis": has_memo,
                            "raw_transcript_preview": (data.get("raw_transcript", "")[:120] + "...")
                            if len(data.get("raw_transcript", "")) > 120
                            else data.get("raw_transcript", ""),
                        }
                    )
                except Exception:
                    continue

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    def delete_memo(self, memo_id: str) -> bool:
        """Delete a memo and its associated files."""
        memo_dir = self.root_dir / memo_id
        if not memo_dir.is_dir():
            matches = list(self.root_dir.glob(f"{memo_id}*"))
            if matches and matches[0].is_dir():
                memo_dir = matches[0]
            else:
                return False

        import shutil

        shutil.rmtree(memo_dir)
        return True
