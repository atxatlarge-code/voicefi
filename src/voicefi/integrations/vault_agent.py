"""
Vault Agent Integration for VoiceFi.
Provides conversational Q&A, active note summaries, and auditory briefings for Obsidian vaults.
"""

import os
import re
from typing import Dict, Any, Optional
from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine


class VaultAgent:
    """Conversational assistant for Obsidian knowledge vaults."""

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        self.config = config or load_config()

    def answer_vault_query(
        self,
        query: str,
        note_title: str = "",
        note_content: str = "",
    ) -> Dict[str, Any]:
        """
        Process a spoken query against the active note and vault context.
        Generates an auditory-friendly response calibrated for speech synthesis.
        """
        clean_query = query.strip()
        lower_q = clean_query.lower()

        # Phonetic normalization for common STT phonetic slips
        if any(w in lower_q for w in ["some racist", "some raise", "some race", "some race is", "summer eyes", "summerize", "summarise", "summarize"]):
            lower_q = "summarize this note"

        # 1. Handle direct summarization requests
        if any(w in lower_q for w in ["summarize", "summary", "give me a summary", "overview", "what is this note about"]):
            return self._summarize_note(note_title, note_content)

        # 2. Handle task / action item extraction
        if any(w in lower_q for w in ["tasks", "action items", "todos", "what do i need to do", "blockers"]):
            return self._extract_action_items(note_title, note_content)

        # 3. Handle contextual question answering
        return self._answer_question(clean_query, note_title, note_content)

    def _summarize_note(self, title: str, content: str) -> Dict[str, Any]:
        """Create a punchy spoken summary of the note."""
        if not content.strip():
            spoken = f"Your note {title or 'document'} is currently empty."
            return {"spoken_response": spoken, "text_summary": spoken, "action": "summarize"}

        # Extract headings and bullet points
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        headings = [re.sub(r"^#+\s*", "", l) for l in lines if l.startswith("#")]
        bullets = [re.sub(r"^[-*]\s*(\[[ xX]\]\s*)?", "", l) for l in lines if l.startswith("-") or l.startswith("*")]

        total_words = len(content.split())
        title_str = title if title else "active note"

        if headings and bullets:
            top_heading = headings[0]
            bullet_sample = ", ".join(bullets[:3])
            spoken = f"Here is a summary of {title_str}. It focuses on {top_heading}, with key items including {bullet_sample}."
        elif headings:
            sections_str = ", ".join(headings[:3])
            spoken = f"{title_str} contains {total_words} words across sections covering {sections_str}."
        elif bullets:
            spoken = f"{title_str} has {len(bullets)} items. The top points are: {', '.join(bullets[:3])}."
        else:
            first_few = " ".join(lines[:2])
            # Strip markdown formatting
            first_few = re.sub(r"[*_#`\[\]]", "", first_few)
            spoken = f"{title_str} is about {first_few[:180]}."

        return {
            "spoken_response": spoken,
            "text_summary": spoken,
            "action": "summarize",
            "title": title,
            "word_count": total_words,
        }

    def _extract_action_items(self, title: str, content: str) -> Dict[str, Any]:
        """Extract open checkboxes and tasks from the note."""
        open_tasks = re.findall(r"^[-*]\s*\[ \]\s*(.+)$", content, re.MULTILINE)
        completed_tasks = re.findall(r"^[-*]\s*\[[xX]\]\s*(.+)$", content, re.MULTILINE)

        if open_tasks:
            count = len(open_tasks)
            task_str = ", ".join(open_tasks[:3])
            more_str = f", plus {count - 3} more" if count > 3 else ""
            spoken = f"You have {count} open task{'s' if count > 1 else ''} in {title or 'this note'}: {task_str}{more_str}."
        elif completed_tasks:
            spoken = f"All {len(completed_tasks)} tasks in {title or 'this note'} are marked complete! Nice work."
        else:
            spoken = f"I didn't find any checkbox tasks in {title or 'this note'}."

        return {
            "spoken_response": spoken,
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "action": "tasks",
        }

    def _answer_question(self, query: str, title: str, content: str) -> Dict[str, Any]:
        """Answer queries using note content as reference."""
        if not content.strip():
            spoken = f"I couldn't find an answer because {title or 'this note'} has no content yet."
            return {"spoken_response": spoken, "action": "answer"}

        # Keyword matching heuristic for offline / zero-latency lookup
        query_words = set(re.findall(r"\b\w{4,}\b", query.lower()))
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        best_p = ""
        best_score = 0
        for p in paragraphs:
            p_words = set(re.findall(r"\b\w{4,}\b", p.lower()))
            overlap = len(query_words.intersection(p_words))
            if overlap > best_score:
                best_score = overlap
                best_p = p

        if best_score > 0 and best_p:
            clean_ans = re.sub(r"[*_#`\[\]]", "", best_p)[:220]
            spoken = f"According to your note: {clean_ans}"
        else:
            title_str = title if title else "your document"
            spoken = f"Based on {title_str}, I see information about {title_str}, but nothing specifically answering '{query}'."

        return {
            "spoken_response": spoken,
            "matched_snippet": best_p,
            "action": "answer",
            "query": query,
        }
