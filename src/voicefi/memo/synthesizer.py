"""
Voice Memo Processing & Synthesis for VoiceFi.
Preserves developer thought fidelity with zero interpretation by default,
with optional Google Gemini Flash structured synthesis when enabled.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from voicefi.config import VoiceFiConfig, load_config
from voicefi.memo.cleaner import MemoCleaner
from voicefi.memo.models import CleanedMemo, SynthesizedMemo


class StructuredMemoResult(BaseModel):
    title: str = "Voice Memo"
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)
    diagram_code: Optional[str] = None
    diagram_type: str = "mermaid"
    action_items: List[str] = Field(default_factory=list)
    pr_checklist: List[str] = Field(default_factory=list)
    raw_transcript: str = ""
    cleaned_transcript: str = ""


class MemoSynthesizer(MemoCleaner):
    """
    Synthesizes and cleans raw developer voice memos.
    Preserves verbatim fidelity with optional Gemini Flash architectural structuring.
    """

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        super().__init__(config=config)

    def synthesize_structured(
        self, raw_speech: str, timeout: float = 3.0
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt structured architecture synthesis via Gemini Flash if configured.
        Returns parsed JSON dict with title, summary, decisions, action_items.
        """
        try:
            from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

            gemini_engine = GeminiIntelligenceEngine(self.config)
            if gemini_engine.is_available() and getattr(
                getattr(self.config, "gemini", None), "enable_memo_structuring", True
            ):
                return gemini_engine.structure_voice_memo(raw_speech, timeout=timeout)
        except Exception:
            pass
        return None

    def synthesize_memo(self, raw_speech: str) -> StructuredMemoResult:
        """
        Synthesizes a raw spoken transcript into a structured memo result.
        Uses Gemini Flash if configured and available; otherwise performs clean,
        faithful extraction with zero hallucination.
        """
        raw_text = (raw_speech or "").strip()
        cleaned = self.clean_transcript(raw_text)
        title = self.infer_title(cleaned or raw_text)

        structured = self.synthesize_structured(raw_text)
        if structured and isinstance(structured, dict):
            return StructuredMemoResult(
                title=structured.get("title") or title,
                summary=structured.get("summary") or cleaned or raw_text,
                key_points=structured.get("decisions") or structured.get("key_points") or [],
                diagram_code=structured.get("diagram_code"),
                diagram_type=structured.get("diagram_type", "mermaid"),
                action_items=structured.get("action_items") or [],
                pr_checklist=structured.get("pr_checklist") or [],
                raw_transcript=raw_text,
                cleaned_transcript=cleaned,
            )

        return StructuredMemoResult(
            title=title,
            summary=cleaned or raw_text,
            key_points=[],
            diagram_code=None,
            diagram_type="mermaid",
            action_items=[],
            pr_checklist=[],
            raw_transcript=raw_text,
            cleaned_transcript=cleaned,
        )
