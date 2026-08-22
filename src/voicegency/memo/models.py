"""
Data models and storage manager for Voice Memo Buffer and Stream-of-Consciousness synthesis.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid
from pydantic import BaseModel, Field


def get_memos_dir() -> Path:
    """Return the root directory for voice memos (~/.voicegency/memos)."""
    m_dir = Path.home() / ".voicegency" / "memos"
    m_dir.mkdir(parents=True, exist_ok=True)
    return m_dir


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


class ProposedFileChange(BaseModel):
    """File modification proposal."""
    action: str = "MODIFY"  # "NEW", "MODIFY", "DELETE"
    path: str
    description: str


class ImplementationStep(BaseModel):
    """Step in the execution plan."""
    step_number: int
    title: str
    details: str
    target_files: List[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    """Structured implementation plan distilled from developer thoughts."""
    goal_summary: str
    problem_context: str = ""
    architectural_decisions: List[str] = Field(default_factory=list)
    proposed_files: List[ProposedFileChange] = Field(default_factory=list)
    steps: List[ImplementationStep] = Field(default_factory=list)


class ArchitecturalDiagram(BaseModel):
    """Mermaid.js diagram representation."""
    diagram_type: str = "graph TD"  # "graph TD", "flowchart LR", "sequenceDiagram"
    mermaid_code: str
    description: str = ""


class PRChecklist(BaseModel):
    """GitHub-flavored pull request checklist and acceptance criteria."""
    core_tasks: List[str] = Field(default_factory=list)
    testing_and_verification: List[str] = Field(default_factory=list)
    edge_cases_and_security: List[str] = Field(default_factory=list)
    documentation_and_ops: List[str] = Field(default_factory=list)


class SynthesizedMemo(BaseModel):
    """Complete synthesized output from developer stream-of-consciousness."""
    memo_id: str
    title: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    executive_summary: str
    raw_transcript: str
    key_requirements: List[str] = Field(default_factory=list)
    course_corrections: List[str] = Field(default_factory=list)
    implementation_plan: ImplementationPlan
    architectural_diagram: ArchitecturalDiagram
    pr_checklist: PRChecklist
    tags: List[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render complete structured memo as a clean Markdown artifact."""
        lines = []
        lines.append(f"# 🧠 Voice Memo: {self.title}")
        lines.append(f"**Synthesized from Developer Stream of Consciousness** | *ID: `{self.memo_id}`*")
        lines.append("")
        lines.append("## 📋 Executive Summary")
        lines.append(self.executive_summary)
        lines.append("")

        if self.key_requirements:
            lines.append("### 🎯 Key Requirements & Objectives")
            for req in self.key_requirements:
                lines.append(f"- {req}")
            lines.append("")

        if self.course_corrections:
            lines.append("### 🔄 Course Corrections & Pivots (Decisions Made)")
            for pivot in self.course_corrections:
                lines.append(f"- {pivot}")
            lines.append("")

        lines.append("---")
        lines.append("## 🏗️ Architectural Diagram")
        lines.append("```mermaid")
        lines.append(self.architectural_diagram.mermaid_code.strip())
        lines.append("```")
        if self.architectural_diagram.description:
            lines.append(f"> *{self.architectural_diagram.description}*")
        lines.append("")

        lines.append("---")
        lines.append("## 🚀 Implementation Plan")
        lines.append(f"**Goal**: {self.implementation_plan.goal_summary}")
        if self.implementation_plan.problem_context:
            lines.append(f"\n**Context**: {self.implementation_plan.problem_context}")
        lines.append("")

        if self.implementation_plan.architectural_decisions:
            lines.append("### Architectural Decisions")
            for dec in self.implementation_plan.architectural_decisions:
                lines.append(f"- {dec}")
            lines.append("")

        if self.implementation_plan.proposed_files:
            lines.append("### Proposed File Changes")
            for f in self.implementation_plan.proposed_files:
                lines.append(f"- **[{f.action}]** `{f.path}`: {f.description}")
            lines.append("")

        if self.implementation_plan.steps:
            lines.append("### Execution Steps")
            for s in self.implementation_plan.steps:
                lines.append(f"#### Step {s.step_number}: {s.title}")
                lines.append(s.details)
                if s.target_files:
                    lines.append(f"*Target Files*: {', '.join(f'`{tf}`' for tf in s.target_files)}")
                lines.append("")

        lines.append("---")
        lines.append("## ✅ PR Checklist & Acceptance Criteria")
        if self.pr_checklist.core_tasks:
            lines.append("### Core Implementation")
            for task in self.pr_checklist.core_tasks:
                lines.append(f"- [ ] {task}")
            lines.append("")

        if self.pr_checklist.testing_and_verification:
            lines.append("### Testing & Verification")
            for test in self.pr_checklist.testing_and_verification:
                lines.append(f"- [ ] {test}")
            lines.append("")

        if self.pr_checklist.edge_cases_and_security:
            lines.append("### Edge Cases & Reliability")
            for edge in self.pr_checklist.edge_cases_and_security:
                lines.append(f"- [ ] {edge}")
            lines.append("")

        if self.pr_checklist.documentation_and_ops:
            lines.append("### Documentation & Delivery")
            for doc in self.pr_checklist.documentation_and_ops:
                lines.append(f"- [ ] {doc}")
            lines.append("")

        lines.append("---")
        lines.append("## 🎙️ Raw Voice Transcript (Stream of Consciousness)")
        lines.append("<details>")
        lines.append("<summary>Click to expand full spoken developer ramble</summary>\n")
        lines.append(f"> {self.raw_transcript}")
        lines.append("\n</details>")
        return "\n".join(lines)


class MemoStore:
    """Persistent storage manager for voice memos and synthesized plans."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or get_memos_dir()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_memo(self, recording: MemoRecording, synthesis: Optional[SynthesizedMemo] = None) -> Path:
        """Save a recording and optional synthesis to disk."""
        memo_dir = self.root_dir / recording.id
        memo_dir.mkdir(parents=True, exist_ok=True)

        rec_path = memo_dir / "recording.json"
        with open(rec_path, "w", encoding="utf-8") as f:
            f.write(recording.model_dump_json(indent=2))

        if synthesis:
            synth_path = memo_dir / "synthesis.json"
            with open(synth_path, "w", encoding="utf-8") as f:
                f.write(synthesis.model_dump_json(indent=2))

            md_path = memo_dir / "plan.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(synthesis.to_markdown())

        return memo_dir

    def get_memo(self, memo_id: str) -> Optional[tuple[MemoRecording, Optional[SynthesizedMemo]]]:
        """Load a memo recording and synthesis by ID."""
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

        synth_path = memo_dir / "synthesis.json"
        synthesis = None
        if synth_path.is_file():
            with open(synth_path, "r", encoding="utf-8") as f:
                synth_data = json.load(f)
            synthesis = SynthesizedMemo(**synth_data)

        return recording, synthesis

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
                    has_synth = (memo_dir / "synthesis.json").is_file()
                    results.append({
                        "id": data.get("id", memo_dir.name),
                        "title": data.get("title", "Voice Memo"),
                        "created_at": data.get("created_at", ""),
                        "duration_seconds": data.get("duration_seconds", 0.0),
                        "word_count": data.get("word_count", 0),
                        "has_synthesis": has_synth,
                        "raw_transcript_preview": (data.get("raw_transcript", "")[:120] + "...") if len(data.get("raw_transcript", "")) > 120 else data.get("raw_transcript", ""),
                    })
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
