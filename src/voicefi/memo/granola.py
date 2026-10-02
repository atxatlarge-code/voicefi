"""
Granola-Style Structured Meeting Note Synthesizer.
Transforms ambient and mobile meeting transcripts into executive summaries,
key decisions, bulleted insights, and action items, while intercepting alert words
('VoiceFi', 'Vi-Fi', 'Viv') to silently dispatch background tasks and sanitize notes.
"""

import re
import datetime
from typing import Optional, Dict, Any, List, Tuple
from voicefi.config import VoiceFiConfig, load_config
from voicefi.memo.cleaner import MemoCleaner
from voicefi.integrations.active_listening import ActiveListeningEngine


class GranolaMeetingResult:
    def __init__(
        self,
        title: str,
        summary: str,
        decisions: List[str],
        insights: List[str],
        action_items: List[str],
        dispatched_actions: List[str],
        markdown: str,
    ):
        self.title = title
        self.summary = summary
        self.decisions = decisions
        self.insights = insights
        self.action_items = action_items
        self.dispatched_actions = dispatched_actions
        self.markdown = markdown


class GranolaSynthesizer(MemoCleaner):
    """Synthesizes raw meeting transcripts into Granola-style meeting notes with command interception."""

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        super().__init__(config=config)
        self.config = config or load_config()

    def intercept_and_sanitize(
        self, raw_text: str, strip_commands: bool = False
    ) -> Tuple[str, List[str]]:
        """
        Scan spoken text for alert words ('VoiceFi', 'Vi-Fi', 'Viv', 'Hey Viv') followed by action commands.
        Extracts action commands for background subagent dispatch.
        If strip_commands is True, removes the commands from the transcript.
        By default (strip_commands=False), preserves 100% of the speech in the transcript for complete meeting fidelity.
        """
        if not raw_text or not raw_text.strip():
            return "", []

        alert_words = list(
            getattr(
                getattr(self.config, "wakeword", None),
                "alert_words",
                ["VoiceFi", "Vi-Fi", "Viv", "Hey Viv", "Hey VoiceFi", "Hey Vi-Fi"],
            )
        )

        sentences = re.split(r"(?<=[.?!])\s+", raw_text.strip())
        sanitized_sentences = []
        dispatched_commands = []

        for sentence in sentences:
            matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(
                sentence, aliases=alert_words
            )
            if matched and prompt:
                # Spoken action command detected
                dispatched_commands.append(prompt.strip())
                # Silently dispatch to active agent if enabled
                try:
                    from voicefi.integrations.injector import send_message_to_agent

                    send_message_to_agent(text=prompt.strip())
                except Exception:
                    pass
                if not strip_commands:
                    sanitized_sentences.append(sentence)
            else:
                sanitized_sentences.append(sentence)

        clean_text = " ".join(sanitized_sentences).strip()
        return clean_text, dispatched_commands

    def synthesize_meeting(
        self,
        raw_speech: str,
        title_hint: Optional[str] = None,
        highlights: Optional[List[Any]] = None,
        tasks: Optional[List[Any]] = None,
        strip_commands: bool = False,
    ) -> GranolaMeetingResult:
        """Process meeting speech into a Granola-style structured document."""
        sanitized_text, dispatched = self.intercept_and_sanitize(
            raw_speech, strip_commands=strip_commands
        )
        cleaned = self.clean_transcript(sanitized_text) if sanitized_text else ""

        title = title_hint or self.infer_title(cleaned or sanitized_text)
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # 1. Try local model or Gemini if configured
        structured_data = None
        if getattr(getattr(self.config, "local_model", None), "airgapped_memos", False):
            structured_data = self._synthesize_with_local_model(cleaned)
        elif getattr(getattr(self.config, "gemini", None), "enable_memo_structuring", True):
            structured_data = self._synthesize_with_gemini(cleaned)

        if structured_data and isinstance(structured_data, dict):
            summary = structured_data.get("summary", cleaned[:300] + "...")
            decisions = structured_data.get("decisions", [])
            insights = structured_data.get("insights", [])
            action_items = structured_data.get("action_items", [])
        else:
            # High-fidelity offline rule-based extraction
            summary = cleaned if len(cleaned) < 350 else cleaned[:350] + "..."
            decisions = []
            insights = [p.strip() for p in cleaned.split(". ") if len(p.strip()) > 20][:6]
            action_items = []

        # Merge in explicitly passed tasks (e.g. from Scout or user tap)
        if tasks:
            for t in tasks:
                t_str = t if isinstance(t, str) else t.get("text", str(t))
                if t_str and t_str not in action_items:
                    action_items.append(t_str)

        # Build markdown sections
        md_lines = [
            f"# 🎙️ {date_str} - {title}\n",
            "## 📌 Executive Summary",
            f"{summary}\n",
        ]

        if highlights:
            md_lines.append("## ⭐ Key Highlights & Bookmarks")
            for h in highlights:
                if isinstance(h, dict):
                    ts = h.get("timestamp", "")
                    txt = h.get("text", "")
                    tag = h.get("tag", "")
                    prefix = f"**{ts}** " if ts else ""
                    tag_str = f"`{tag}` " if tag else ""
                    md_lines.append(f"- ⭐ {prefix}{tag_str}{txt}")
                else:
                    md_lines.append(f"- ⭐ {h}")
            md_lines.append("")

        if decisions:
            md_lines.append("## 🎯 Key Decisions")
            for d in decisions:
                md_lines.append(f"- **Decision**: {d}")
            md_lines.append("")

        if insights:
            md_lines.append("## 💬 Discussion & Insights")
            for ins in insights:
                md_lines.append(f"- {ins}")
            md_lines.append("")

        md_lines.append("## 📋 Action Items")
        for item in action_items:
            md_lines.append(f"- [ ] {item}")
        for disp in dispatched:
            md_lines.append(f"- [x] ⚡ **Dispatched via VoiceFi**: {disp}")
        if not action_items and not dispatched:
            md_lines.append("- [ ] Review meeting notes and assign follow-ups")
        md_lines.append("")

        md_lines.append("## 📝 Clean Transcript")
        md_lines.append(f"> {cleaned}\n")

        full_md = "\n".join(md_lines)
        return GranolaMeetingResult(
            title=title,
            summary=summary,
            decisions=decisions,
            insights=insights,
            action_items=action_items,
            dispatched_actions=dispatched,
            markdown=full_md,
        )

    def _synthesize_with_local_model(self, text: str) -> Optional[Dict[str, Any]]:
        """Run on-device structuring via local Gemma 26B."""
        try:
            from voicefi.local.engine import get_local_engine

            engine = get_local_engine(self.config)
            if engine and engine.is_available():
                prompt = (
                    "Synthesize the following meeting text into Granola-style notes with JSON keys: "
                    "'summary', 'decisions', 'insights', 'action_items'.\n\n"
                    f"Meeting text: {text}"
                )
                res = engine.generate(prompt, max_tokens=1024)
                import json

                return json.loads(res)
        except Exception:
            pass
        return None

    def _synthesize_with_gemini(self, text: str) -> Optional[Dict[str, Any]]:
        """Run cloud structuring via Gemini Flash if configured."""
        try:
            from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

            gemini = GeminiIntelligenceEngine(self.config)
            if gemini.is_available():
                return gemini.structure_voice_memo(text)
        except Exception:
            pass
        return None
