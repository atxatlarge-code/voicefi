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


from voicefi.integrations.active_listening import ActiveListeningEngine, SpokenIntentCategory


class ProactiveTriageEngine:
    """Classifies streaming transcript chunks into actionable developer intents."""

    @classmethod
    def evaluate(cls, text: str) -> Optional[ProactiveTask]:
        """Evaluate a transcribed sentence and produce a proactive task if actionable."""
        clean_text = text.strip()
        if not clean_text or len(clean_text.split()) < 3:
            return None

        # 1. Filter out mic checks and conversational filler using ActiveListeningEngine
        active_res = ActiveListeningEngine.evaluate(clean_text, is_ambient=True)
        if not active_res.is_actionable or active_res.category in (
            SpokenIntentCategory.MIC_CHECK,
            SpokenIntentCategory.CONVERSATIONAL_FILLER,
            SpokenIntentCategory.IGNORED,
        ):
            return None

        # 2. Synchronous Ollama System 1 Structured Output call
        import urllib.request
        import json
        
        system_prompt = (
            "You are VoiceFi's proactive triage engine. Analyze ambient speech to extract actionable tasks. "
            "If the speech is filler or unrelated, classify it as 'IGNORE'.\n"
            "Categories:\n"
            "- RESEARCH: Look up docs, find files, explain code.\n"
            "- SCAFFOLD: Build, create, write, or implement new code.\n"
            "- DIAGNOSE: Investigate bugs, memory leaks, or test failures.\n"
            "- TICKET: Create action items, todos, or Jira tickets.\n"
            "- IGNORE: Unrelated chatter, lunch, coffee, etc."
        )

        payload = {
            "model": "gemma2:2b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Ambient Speech: {clean_text}"}
            ],
            "format": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["IGNORE", "RESEARCH", "SCAFFOLD", "DIAGNOSE", "TICKET"]
                    },
                    "summary": {
                        "type": "string",
                        "description": "Short 3-6 word summary of the task."
                    },
                    "action_prompt": {
                        "type": "string",
                        "description": "Specific action the background subagent should perform."
                    },
                    "workspace": {
                        "type": "string",
                        "enum": ["inherit", "branch"],
                        "description": "Use 'branch' for SCAFFOLD or unsafe changes. Use 'inherit' for research/diagnostics."
                    }
                },
                "required": ["category", "summary", "action_prompt", "workspace"]
            },
            "stream": False,
            "options": {"temperature": 0.0}
        }
        
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=5.0) as response:
                result = json.loads(response.read().decode())
                parsed = json.loads(result["message"]["content"])
        except Exception as e:
            return None
            
        cat_str = parsed.get("category", "IGNORE")
        if cat_str == "IGNORE":
            return None
            
        try:
            category = TriageCategory(cat_str)
        except ValueError:
            return None

        task_id = str(uuid.uuid4())[:8]
        workspace = parsed.get("workspace", "inherit")
        action_prompt = parsed.get("action_prompt", clean_text)
        if workspace == "branch" and "isolated branch" not in action_prompt.lower():
            action_prompt = f"On an isolated branch: {action_prompt}"

        return ProactiveTask(
            id=task_id,
            category=category,
            raw_utterance=clean_text,
            summary=parsed.get("summary", f"{cat_str}: {clean_text[:60]}..."),
            action_prompt=action_prompt,
            suggested_workspace=workspace,
        )


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
