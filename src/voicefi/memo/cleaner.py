"""
Non-destructive Voice Memo Text Cleaner for VoiceFi.
Preserves developer thought fidelity with zero interpretation.
Performs conservative cleanup:
- Strips true vocal disfluencies (um, uh, uhm, erm, er, ah, hmm)
- Deduplicates stuttered repeated words ("the the" -> "the", "we we" -> "we")
- Preserves all semantic vocabulary ("like", "sort of", "kind of", "right", "wait", etc.)
- Normalizes sentence punctuation, spacing, and capitalization
"""

import re
from typing import Optional, List
from voicefi.config import VoiceFiConfig, load_config
from voicefi.memo.models import CleanedMemo


class MemoCleaner:
    """
    Cleans raw spoken developer rambles without interpreting, summarizing,
    or generating fictitious diagrams/plans.
    """

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        self.config = config or load_config()

    def clean_transcript(self, raw_speech: str) -> str:
        """
        Conservatively clean raw speech:
        1. Remove only true vocal hesitation particles (um, uh, erm, ah, etc.)
        2. Deduplicate stuttered word repetitions (e.g. "we we" -> "we")
        3. Clean up spacing and punctuation
        4. Normalize sentence capitalization
        """
        if not raw_speech or not raw_speech.strip():
            return ""

        text = raw_speech.strip()

        # 1. Remove pure vocal disfluencies (case-insensitive word boundaries)
        # Note: Do NOT match 'like', 'sort of', 'right', 'basically' as they carry semantic meaning
        disfluency_pattern = r"\b(um|uh|uhm|erm|er|ah|hmm)\b"
        text = re.sub(disfluency_pattern, "", text, flags=re.IGNORECASE)

        # 2. Collapse immediate duplicate word stutters (e.g. "we we" -> "we", "the the" -> "the")
        text = re.sub(r"\b([a-zA-Z]+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

        # 3. Clean up multi-spaces, dangling commas/periods
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.:;!?])", r"\1", text)
        text = re.sub(r"([,;])\s*([,;])+", r"\1", text)
        text = re.sub(r"\(\s*\)", "", text)

        # 4. Normalize sentence boundaries and capitalization
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences:
            sentences = [text]

        capitalized_sentences = []
        for s in sentences:
            if s:
                cap_s = s[0].upper() + s[1:] if len(s) > 1 else s.upper()
                capitalized_sentences.append(cap_s)

        cleaned = " ".join(capitalized_sentences).strip()
        return cleaned

    def infer_title(self, text: str, custom_title: Optional[str] = None) -> str:
        """Infer a clean, concise title from the speech or fallback."""
        if custom_title and custom_title.strip():
            return custom_title.strip()

        if not text:
            return "Voice Memo"

        first_part = text.split("\n")[0].strip()
        first_sent = re.split(r"[.!?]", first_part)[0].strip()

        cleaned_intro = re.sub(
            r"^(?:(?:so\s+)?(?:i'm\s+thinking|i\s+am\s+thinking|i\s+want\s+to\s+build|i\s+want\s+to|let's\s+build|let's\s+add|let's|basically|what\s+if\s+we)\s+)*(?:we\s+need\s+to\s+add|we\s+need\s+to|we\s+need|i\s+need|let's\s+build|let's\s+add|let's|to\s+build|to\s+add)?\s*",
            "",
            first_sent,
            flags=re.IGNORECASE,
        ).strip()
        cleaned_intro = re.sub(r"^(?:an?\s+|the\s+)", "", cleaned_intro, flags=re.IGNORECASE).strip()
        cleaned_intro = re.sub(r"[.,;:!?]+$", "", cleaned_intro).strip()

        words = cleaned_intro.split()
        if words:
            title = " ".join(words[:6]).title()
            if len(title) > 3:
                return title

        return "Voice Memo"

    def process(
        self,
        raw_speech: str,
        memo_id: Optional[str] = None,
        custom_title: Optional[str] = None,
        duration_seconds: float = 0.0,
    ) -> CleanedMemo:
        """Process raw voice memo into a cleaned, uninterpreted memo record."""
        import uuid
        mid = memo_id or str(uuid.uuid4())[:8]

        cleaned_text = self.clean_transcript(raw_speech)
        title = self.infer_title(cleaned_text or raw_speech, custom_title=custom_title)
        words = len((cleaned_text or raw_speech).split())

        return CleanedMemo(
            memo_id=mid,
            title=title,
            duration_seconds=duration_seconds,
            raw_transcript=raw_speech,
            cleaned_transcript=cleaned_text or raw_speech,
            word_count=words,
        )

    # Alias methods for backwards compatibility
    def clean_raw_rambles(self, text: str) -> str:
        return self.clean_transcript(text)

    def synthesize(
        self,
        raw_speech: str,
        memo_id: Optional[str] = None,
        custom_title: Optional[str] = None,
    ) -> CleanedMemo:
        """Backwards compatibility wrapper for synthesize()."""
        return self.process(raw_speech=raw_speech, memo_id=memo_id, custom_title=custom_title)
