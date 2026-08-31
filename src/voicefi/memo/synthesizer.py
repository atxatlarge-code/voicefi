"""
Voice Memo Processing & Synthesis for VoiceFi.
Preserves developer thought fidelity with zero interpretation by default,
with optional Google Gemini Flash structured synthesis when enabled.
"""

from typing import Optional, Dict, Any
from voicefi.config import VoiceFiConfig, load_config
from voicefi.memo.cleaner import MemoCleaner
from voicefi.memo.models import CleanedMemo, SynthesizedMemo


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
