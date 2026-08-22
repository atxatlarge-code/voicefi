"""
Proactive Intent Triage Engine and Subagent Dispatcher.
Evaluates ambient transcript streams in real time, classifies developer intents,
and dispatches background research or isolated sandbox subagents (Workspace="branch").
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Callable


class TriageCategory(str, Enum):
    IGNORE = "IGNORE"
    RESEARCH = "RESEARCH"
    SCAFFOLD = "SCAFFOLD"
    DIAGNOSE = "DIAGNOSE"
    TICKET = "TICKET"


@dataclass
class ProactiveTask:
    id: str
    category: TriageCategory
    raw_utterance: str
    summary: str
    action_prompt: str
    suggested_workspace: str  # "branch", "inherit", or "read_only"
    status: str = "staged"  # "staged", "running", "completed", "dismissed"
    created_at: float = field(default_factory=time.time)
    result_summary: Optional[str] = None


class ProactiveTriageEngine:
    """Classifies streaming transcript chunks into actionable developer intents."""

    # Trigger patterns for fast local classification
    SCAFFOLD_PATTERNS = [
        r"\b(?:let\'?s|we (?:should|need to)|can we|could we)\s+(?:build|add|create|scaffold|implement|write|draft|integrate)\b",
        r"\b(?:create|add|implement)\s+(?:a|an|the)\s+(?:component|route|endpoint|model|migration|schema|test|service|hook)\b",
        r"\b(?:support for|integration with)\s+[A-Za-z0-9_-]+\b",
    ]

    RESEARCH_PATTERNS = [
        r"\b(?:what(?:'s| is)|how does|how do we|look up|check)\s+(?:the|an?)\s+(?:api|docs?|documentation|spec|signature|schema|config)\b",
        r"\b(?:is there a|do we have|where is)\s+[A-Za-z0-9_-]+\b",
        r"\b(?:compare|difference between)\s+[A-Za-z0-9_-]+\s+and\s+[A-Za-z0-9_-]+\b",
    ]

    DIAGNOSE_PATTERNS = [
        r"\b(?:why is|debug|audit|inspect|investigate)\s+(?:the|this|our)?\s*(?:lcp|performance|error|bug|test failure|memory|crash|lag)\b",
        r"\b(?:slow|hanging|failing|broken|crashing)\b",
    ]

    TICKET_PATTERNS = [
        r"\b(?:action item|todo|ticket|linear|jira|task)\s*:\s*",
        r"\b(?:someone needs to|let\'?s make a ticket for|assign to)\b",
    ]

    IGNORE_PATTERNS = [
        r"^(?:yeah|yes|no|nope|okay|ok|uh-huh|mhm|sure|thanks|thank you|bye|hello|hi|hey)[\s.?!]*$",
        r"\b(?:lunch|coffee|weather|weekend|dinner|traffic)\b",
    ]

    @classmethod
    def evaluate(cls, text: str) -> Optional[ProactiveTask]:
        """Evaluate a transcribed sentence and produce a proactive task if actionable."""
        clean_text = text.strip()
        if not clean_text or len(clean_text.split()) < 3:
            return None

        # 1. Quick check for ignore / smalltalk
        for pat in cls.IGNORE_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return None

        task_id = str(uuid.uuid4())[:8]

        # 2. Check for DIAGNOSE intent
        for pat in cls.DIAGNOSE_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return ProactiveTask(
                    id=task_id,
                    category=TriageCategory.DIAGNOSE,
                    raw_utterance=clean_text,
                    summary=f"Diagnose: {clean_text[:60]}...",
                    action_prompt=f"Investigate and diagnose the reported issue: '{clean_text}'",
                    suggested_workspace="inherit",
                )

        # 3. Check for SCAFFOLD intent (Isolated branch workspace)
        for pat in cls.SCAFFOLD_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return ProactiveTask(
                    id=task_id,
                    category=TriageCategory.SCAFFOLD,
                    raw_utterance=clean_text,
                    summary=f"Scaffold: {clean_text[:60]}...",
                    action_prompt=f"In an isolated branch sandbox, scaffold and implement: '{clean_text}'",
                    suggested_workspace="branch",
                )

        # 4. Check for RESEARCH intent
        for pat in cls.RESEARCH_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return ProactiveTask(
                    id=task_id,
                    category=TriageCategory.RESEARCH,
                    raw_utterance=clean_text,
                    summary=f"Research: {clean_text[:60]}...",
                    action_prompt=f"Research documentation and codebase context for: '{clean_text}'",
                    suggested_workspace="inherit",
                )

        # 5. Check for TICKET / Action items
        for pat in cls.TICKET_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return ProactiveTask(
                    id=task_id,
                    category=TriageCategory.TICKET,
                    raw_utterance=clean_text,
                    summary=f"Ticket: {clean_text[:60]}...",
                    action_prompt=f"Record meeting action item: '{clean_text}'",
                    suggested_workspace="inherit",
                )

        return None


class ProactiveDispatcher:
    """Manages proactive tasks and coordinates background subagents."""

    def __init__(self, on_task_created: Optional[Callable[[ProactiveTask], None]] = None):
        self.tasks: Dict[str, ProactiveTask] = {}
        self.on_task_created = on_task_created

    def process_utterance(self, text: str) -> Optional[ProactiveTask]:
        """Evaluate transcribed speech and stage proactive task if actionable."""
        task = ProactiveTriageEngine.evaluate(text)
        if task:
            self.tasks[task.id] = task
            if self.on_task_created:
                try:
                    self.on_task_created(task)
                except Exception as ex:
                    print(f"[ProactiveDispatcher] Callback error: {ex}")
            return task
        return None

    def get_staged_tasks(self) -> List[ProactiveTask]:
        """Return all active staged tasks awaiting developer action."""
        return [t for t in self.tasks.values() if t.status in ("staged", "running")]

    def dismiss_task(self, task_id: str):
        """Dismiss a staged task."""
        if task_id in self.tasks:
            self.tasks[task_id].status = "dismissed"

    def complete_task(self, task_id: str, result_summary: str):
        """Mark task completed with result summary."""
        if task_id in self.tasks:
            self.tasks[task_id].status = "completed"
            self.tasks[task_id].result_summary = result_summary
