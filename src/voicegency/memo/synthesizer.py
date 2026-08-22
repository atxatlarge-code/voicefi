"""
Stream of Consciousness to Code Synthesizer for Voicegency.
Transforms raw, unstructured developer rambles, brain dumps, and pacing thoughts
into structured Implementation Plans, Mermaid Architectural Diagrams, and PR Checklists.
"""

import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import requests

from voicegency.config import VoicegencyConfig, load_config
from voicegency.memo.models import (
    SynthesizedMemo,
    ImplementationPlan,
    ImplementationStep,
    ProposedFileChange,
    ArchitecturalDiagram,
    PRChecklist,
    MemoRecording,
)


class MemoSynthesizer:
    """
    Synthesizes unstructured spoken developer thoughts into concrete software engineering artifacts.
    Works offline via a structured heuristic parser and can optionally leverage LLMs (Groq, OpenAI, etc.).
    """

    def __init__(self, config: Optional[VoicegencyConfig] = None):
        self.config = config or load_config()

    def clean_raw_rambles(self, text: str) -> str:
        """Strip verbal filler words and normal speech hesitations."""
        if not text:
            return ""

        # Remove verbal ticks and filler words
        filler_patterns = [
            r"\b(um|uh|err|ah|like|you know|sort of|kind of|i guess|i mean|so basically)\b",
            r"\b(let's see|let me think|hang on|wait a second|right)\b",
        ]
        cleaned = text
        for pat in filler_patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

        # Normalize spaces
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned

    def detect_pivots_and_corrections(self, text: str) -> Tuple[List[str], str]:
        """
        Detect when a developer changes their mind or course-corrects during speech.
        Example: 'Let's use Redis... actually wait, SQLite is simpler for local dev.'
        Returns (list_of_corrections, normalized_text).
        """
        corrections = []
        pivot_markers = [
            r"(?:actually\s+wait|wait\s+no|scratch\s+that|on\s+second\s+thought|instead\s+of|nevermind|no\s+wait)[,:]?\s*([^.!?]+)",
            r"(?:let's\s+not\s+use|we\s+shouldn't\s+use)\s+([^.!?]+)",
        ]

        for marker in pivot_markers:
            for match in re.finditer(marker, text, flags=re.IGNORECASE):
                pivot_text = match.group(1).strip()
                if pivot_text and len(pivot_text) > 4:
                    corrections.append(f"Course correction: {pivot_text}")

        return corrections, text

    def extract_technical_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract components, databases, APIs, protocols, tools, and file references."""
        entities: Dict[str, List[str]] = {
            "components": [],
            "databases_and_storage": [],
            "api_endpoints": [],
            "files": [],
            "test_mentions": [],
        }

        # Common tech keywords
        tech_keywords = {
            "sqlite": "databases_and_storage",
            "postgres": "databases_and_storage",
            "redis": "databases_and_storage",
            "mysql": "databases_and_storage",
            "database": "databases_and_storage",
            "storage": "databases_and_storage",
            "queue": "components",
            "worker": "components",
            "daemon": "components",
            "cli": "components",
            "api": "components",
            "server": "components",
            "ui": "components",
            "frontend": "components",
            "backend": "components",
            "hud": "components",
            "menu bar": "components",
            "rest": "api_endpoints",
            "endpoint": "api_endpoints",
            "http": "api_endpoints",
            "get": "api_endpoints",
            "post": "api_endpoints",
            "put": "api_endpoints",
            "delete": "api_endpoints",
            "test": "test_mentions",
            "pytest": "test_mentions",
            "unit test": "test_mentions",
            "integration test": "test_mentions",
            "mock": "test_mentions",
        }

        lower = text.lower()
        for kw, cat in tech_keywords.items():
            if re.search(rf"\b{kw}\b", lower):
                if kw not in entities[cat]:
                    entities[cat].append(kw)

        # Detect potential file names (e.g. models.py, config.yaml, /api/users)
        file_matches = re.findall(r"\b([a-zA-Z0-9_\-/\\]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|md|html|css|sh))\b", text)
        for fm in file_matches:
            if fm not in entities["files"]:
                entities["files"].append(fm)

        # Detect REST endpoints like GET /jobs, POST /auth
        endpoint_matches = re.findall(r"\b((?:GET|POST|PUT|DELETE|PATCH)\s+[/\w\-:]+)", text, flags=re.IGNORECASE)
        for ep in endpoint_matches:
            formatted_ep = ep.strip()
            if formatted_ep not in entities["api_endpoints"]:
                entities["api_endpoints"].append(formatted_ep)

        return entities

    def generate_mermaid_diagram(self, title: str, entities: Dict[str, List[str]], text: str) -> ArchitecturalDiagram:
        """Generate a Mermaid.js diagram visualizing system flow and components."""
        nodes = []
        edges = []

        # Standard User / Trigger node
        nodes.append('    User["👤 Developer / User"]')

        has_cli = "cli" in entities["components"] or "cli" in text.lower()
        has_api = "api" in entities["components"] or bool(entities["api_endpoints"]) or "api" in text.lower()
        has_worker = "worker" in entities["components"] or "queue" in entities["components"] or "worker" in text.lower()
        has_db = bool(entities["databases_and_storage"]) or "database" in text.lower()
        has_ui = "ui" in entities["components"] or "hud" in entities["components"] or "menu bar" in entities["components"]

        primary_entry = "CLI" if has_cli else "UI" if has_ui else "App"

        if has_cli:
            nodes.append('    CLI["⌨️ CLI / Voice Interface"]')
            edges.append('    User -->|Voice / Command| CLI')

        if has_ui and not has_cli:
            nodes.append('    UI["🖥️ UI / HUD Component"]')
            edges.append('    User -->|Interaction| UI')

        if has_api:
            nodes.append('    API["🌐 API Layer / Router"]')
            if has_cli:
                edges.append('    CLI -->|Dispatches Request| API')
            elif has_ui:
                edges.append('    UI -->|HTTP / RPC| API')
            else:
                edges.append('    User -->|Requests| API')

        # Core Engine / Service node
        service_label = f"⚙️ {title[:28]}" if len(title) > 3 else "⚙️ Core Engine"
        nodes.append(f'    Engine["{service_label}"]')

        if has_api:
            edges.append('    API -->|Executes| Engine')
        elif has_cli:
            edges.append('    CLI -->|Invokes| Engine')
        elif has_ui:
            edges.append('    UI -->|Triggers| Engine')
        else:
            edges.append('    User -->|Starts| Engine')

        if has_worker:
            nodes.append('    Queue["📬 Task Queue / Buffer"]')
            nodes.append('    Worker["⚡ Background Worker"]')
            edges.append('    Engine -->|Enqueues Task| Queue')
            edges.append('    Queue -->|Consumes| Worker')

        if has_db:
            db_name = entities["databases_and_storage"][0].capitalize() if entities["databases_and_storage"] else "Storage"
            nodes.append(f'    DB[("💾 {db_name} Database / Store")]')
            if has_worker:
                edges.append('    Worker -->|Persists State| DB')
            else:
                edges.append('    Engine -->|Reads / Writes| DB')

        # Feedback / Output node
        nodes.append('    Output["📄 Output Artifact / Result"]')
        if has_worker:
            edges.append('    Worker -->|Emits Status| Output')
        else:
            edges.append('    Engine -->|Yields Output| Output')
        edges.append('    Output -->|Notifies| User')

        mermaid_lines = ["graph TD"] + nodes + [""] + edges
        code = "\n".join(mermaid_lines)
        return ArchitecturalDiagram(
            diagram_type="graph TD",
            mermaid_code=code,
            description="High-level architecture and data flow synthesized from voice thoughts.",
        )

    def synthesize(
        self,
        raw_speech: str,
        memo_id: Optional[str] = None,
        custom_title: Optional[str] = None,
    ) -> SynthesizedMemo:
        """
        Synthesize raw spoken text into a full structured specification and plan.
        """
        import uuid
        memo_id = memo_id or str(uuid.uuid4())[:8]

        cleaned_text = self.clean_raw_rambles(raw_speech)
        corrections, analyzed_text = self.detect_pivots_and_corrections(cleaned_text)
        entities = self.extract_technical_entities(analyzed_text)

        # Break text into meaningful sentences
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", analyzed_text) if s.strip()]
        if not sentences:
            sentences = [analyzed_text] if analyzed_text else ["Implement requested functionality."]

        # Title inference
        title = custom_title
        if not title:
            first_sent = sentences[0] if sentences else ""
            # Strip common conversational intros
            cleaned_intro = re.sub(
                r"^(?:(?:so\s+)?(?:i'm\s+thinking|i\s+am\s+thinking|i\s+want\s+to\s+build|i\s+want\s+to|let's\s+build|let's\s+add|let's|basically|what\s+if\s+we)\s+)*(?:we\s+need\s+to\s+add|we\s+need\s+to|we\s+need|i\s+need|let's\s+build|let's\s+add|let's|to\s+build|to\s+add)?\s*",
                "",
                first_sent,
                flags=re.IGNORECASE,
            ).strip()
            # Remove trailing periods/commas
            cleaned_intro = re.sub(r"[.,;:!?]+$", "", cleaned_intro).strip()
            words = cleaned_intro.split()
            if words:
                title = " ".join(words[:6]).title()
            else:
                title = "Developer Voice Memo"

        # Executive summary
        exec_summary = " ".join(sentences[:3]) if len(sentences) >= 3 else analyzed_text

        # Key requirements
        key_reqs = []
        for s in sentences:
            if any(k in s.lower() for k in ["need", "should", "must", "want", "have to", "require"]):
                key_reqs.append(s)
        if not key_reqs:
            key_reqs = sentences[:4]

        # Proposed files
        proposed_files: List[ProposedFileChange] = []
        if entities["files"]:
            for f in entities["files"]:
                action = "NEW" if ("new" in raw_speech.lower() or "create" in raw_speech.lower()) else "MODIFY"
                proposed_files.append(ProposedFileChange(action=action, path=f, description=f"Implement changes for {title}"))
        else:
            # Infer plausible files based on components
            if "cli" in entities["components"] or "cli" in raw_speech.lower():
                proposed_files.append(ProposedFileChange(action="MODIFY", path="src/cli.py", description="Add CLI interface and flags"))
            if "worker" in entities["components"] or "queue" in raw_speech.lower():
                proposed_files.append(ProposedFileChange(action="NEW", path="src/worker.py", description="Background worker and queue processor"))
            if entities["databases_and_storage"] or "database" in raw_speech.lower():
                proposed_files.append(ProposedFileChange(action="NEW", path="src/models.py", description="Database schema and storage models"))
            if not proposed_files:
                proposed_files.append(ProposedFileChange(action="NEW", path="src/core.py", description="Core business logic and integration"))

        # Implementation steps
        steps: List[ImplementationStep] = []
        step_idx = 1
        steps.append(ImplementationStep(
            step_number=step_idx,
            title="Define Core Data Models & Schemas",
            details="Establish structured data classes, validation rules, and persistence entities.",
            target_files=[f.path for f in proposed_files if "model" in f.path or "schema" in f.path] or [proposed_files[0].path],
        ))
        step_idx += 1

        steps.append(ImplementationStep(
            step_number=step_idx,
            title="Implement Core Engine & Service Logic",
            details=f"Implement primary execution logic based on developer requirements: {exec_summary[:140]}...",
            target_files=[f.path for f in proposed_files if f.path != "src/cli.py"],
        ))
        step_idx += 1

        if any(f.path.endswith("cli.py") or "cli" in entities["components"] for f in proposed_files) or "cli" in raw_speech.lower():
            steps.append(ImplementationStep(
                step_number=step_idx,
                title="Integrate CLI & User Controls",
                details="Add command-line flags, interactive commands, and graceful error handling.",
                target_files=[f.path for f in proposed_files if "cli" in f.path],
            ))
            step_idx += 1

        steps.append(ImplementationStep(
            step_number=step_idx,
            title="Comprehensive Testing & Verification",
            details="Write unit and integration tests covering happy paths, failure cases, and retries.",
            target_files=["tests/test_feature.py"],
        ))

        # Architectural decisions
        arch_decisions = []
        if corrections:
            arch_decisions.extend(corrections)
        for s in sentences:
            if any(k in s.lower() for k in ["because", "instead", "use", "prefer", "keep it", "architecture"]):
                if s not in arch_decisions:
                    arch_decisions.append(s)
        if not arch_decisions:
            arch_decisions.append("Designed for modularity, low latency, and offline-first execution.")

        plan = ImplementationPlan(
            goal_summary=f"Deliver complete end-to-end implementation for {title}.",
            problem_context=exec_summary,
            architectural_decisions=arch_decisions[:5],
            proposed_files=proposed_files,
            steps=steps,
        )

        # Architectural diagram
        diagram = self.generate_mermaid_diagram(title, entities, raw_speech)

        # PR Checklist
        core_tasks = [
            f"Implement {title} core components and data structures",
            "Ensure clean error handling and graceful fallbacks",
        ]
        if entities["api_endpoints"]:
            core_tasks.append(f"Expose API endpoints: {', '.join(entities['api_endpoints'][:3])}")

        test_tasks = [
            "Add automated unit tests verifying core execution path",
            "Verify edge case behavior under invalid input or network timeout",
            "Ensure 100% test suite pass rate with zero regressions",
        ]

        edge_tasks = [
            "Handle process interruptions and cancel signals gracefully",
            "Validate resource cleanup (file handles, memory buffers, connections)",
        ]

        doc_tasks = [
            "Update documentation, README, and CLI help text",
            "Verify code formatting and linting standards",
        ]

        pr_checklist = PRChecklist(
            core_tasks=core_tasks,
            testing_and_verification=test_tasks,
            edge_cases_and_security=edge_tasks,
            documentation_and_ops=doc_tasks,
        )

        return SynthesizedMemo(
            memo_id=memo_id,
            title=title,
            executive_summary=exec_summary,
            raw_transcript=raw_speech,
            key_requirements=key_reqs[:6],
            course_corrections=corrections,
            implementation_plan=plan,
            architectural_diagram=diagram,
            pr_checklist=pr_checklist,
            tags=list(entities["components"] + entities["databases_and_storage"])[:6],
        )
