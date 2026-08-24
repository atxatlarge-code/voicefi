"""
Active Listening, Intent Safety, and Conversational Triage Engine.
Filters non-actionable acoustic mic checks and conversational filler,
normalizes phonetic spoken code slang, and manages contextual disambiguation.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
import difflib

from voicefi.stt.biasing import PhoneticNormalizer


class SpokenIntentCategory(str, Enum):
    MIC_CHECK = "MIC_CHECK"
    CONVERSATIONAL_FILLER = "CONVERSATIONAL_FILLER"
    PENDING_ANSWER = "PENDING_ANSWER"
    ACTIONABLE_COMMAND = "ACTIONABLE_COMMAND"
    IGNORED = "IGNORED"


@dataclass
class ActiveListeningResult:
    category: SpokenIntentCategory
    raw_text: str
    normalized_text: str
    is_actionable: bool
    quick_spoken_reply: Optional[str] = None
    selected_option: Optional[str] = None
    confidence: float = 1.0


class ActiveListeningEngine:
    """Evaluates developer speech against acoustic safety and intent verification rules."""

    MIC_CHECK_PATTERNS = [
        r"^(?:(?:okay|ok|hey|hi)\s+)?(?:can|could|do)?\s*(?:you\s+)?(?:hear|hearing)\s+me[\s.?!]*$",
        r"^(?:mic\s+)?check(?:ing)?(?:\s+(?:one|1|two|2|three|3|check|testing))*[\s.?!]*$",
        r"^(?:testing|test)(?:\s+(?:one|1|two|2|three|3|mic|audio|check))*[\s.?!]*$",
        r"^(?:audio|sound|voice)\s+check[\s.?!]*$",
        r"^(?:is\s+(?:this\s+thing\s+on|anyone\s+there|the\s+mic\s+working))[\s.?!]*$",
    ]

    CONVERSATIONAL_FILLER_PATTERNS = [
        r"^(?:okay|ok|nice|cool|sweet|awesome|perfect|thank you|thanks|got it|sounds good|sounds great)[\s.?!]*$",
        r"^(?:okay\s+)?(?:nice\s+)?(?:that\s+)?(?:sounds|looks)\s+(?:great|good|awesome|nice|fine|solid)[\s.?!]*$",
        r"^(?:yeah|yes|yep|yup|nope|no|sure|right|all right|alright)[\s.?!]*$",
    ]

    # Stop words for word overlap comparison
    STOP_WORDS = {"the", "a", "an", "is", "it", "to", "in", "on", "of", "and", "or", "for", "do", "you", "we", "i", "now"}

    @classmethod
    def is_mic_check(cls, text: str) -> bool:
        """Return True if text is a microphone test or audio check phrase."""
        if not text or not text.strip():
            return False
        clean = text.strip().lower()
        for pat in cls.MIC_CHECK_PATTERNS:
            if re.match(pat, clean, re.IGNORECASE):
                return True
        # Check repeated check tokens like "check check check check"
        words = clean.split()
        if len(words) >= 2 and all(w in ("check", "testing", "test", "one", "two", "three", "1", "2", "3") for w in words):
            return True
        return False

    @classmethod
    def is_conversational_filler(cls, text: str) -> bool:
        """Return True if text is conversational filler or non-actionable affirmation."""
        if not text or not text.strip():
            return True
        clean = text.strip().lower()
        for pat in cls.CONVERSATIONAL_FILLER_PATTERNS:
            if re.match(pat, clean, re.IGNORECASE):
                return True
        return False

    @classmethod
    def match_pending_choice(cls, text: str, pending_question: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Evaluate if text selects or matches one of the options in an active pending question.
        Returns the matched option string or None.
        """
        if not pending_question or not text:
            return None

        options: List[str] = pending_question.get("options", [])
        if not options:
            return None

        clean_input = re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()
        input_words = set(clean_input.split()) - cls.STOP_WORDS

        best_match = None
        best_score = 0.0

        for opt in options:
            clean_opt = re.sub(r"[^a-z0-9\s]", "", opt.lower()).strip()
            opt_words = set(clean_opt.split()) - cls.STOP_WORDS

            # 1. Exact or substring match
            if clean_opt in clean_input or clean_input in clean_opt:
                return opt

            # 2. Word overlap match (e.g. "deploy to staging now" vs "Stage on Railway")
            if input_words and opt_words:
                overlap = input_words.intersection(opt_words)
                score = len(overlap) / max(1, len(opt_words))
                if score > 0.4 and score > best_score:
                    best_score = score
                    best_match = opt

            # 3. Fuzzy similarity
            ratio = difflib.SequenceMatcher(None, clean_input, clean_opt).ratio()
            if ratio > 0.65 and ratio > best_score:
                best_score = ratio
                best_match = opt

        # Semantic deployment alias handling
        if "stage" in clean_input or "staging" in clean_input:
            for opt in options:
                if "stage" in opt.lower() or "railway" in opt.lower():
                    return opt
        if "ship" in clean_input or "prod" in clean_input or "production" in clean_input:
            for opt in options:
                if "ship" in opt.lower() or "straightaway" in opt.lower() or "prod" in opt.lower():
                    return opt

        return best_match

    @classmethod
    def evaluate(
        cls,
        text: str,
        pending_question: Optional[Dict[str, Any]] = None,
        is_ambient: bool = False,
    ) -> ActiveListeningResult:
        """
        Evaluate transcribed utterance for active listening, cognitive safety, and intent verification.
        """
        raw_text = text.strip() if text else ""
        if not raw_text:
            return ActiveListeningResult(
                category=SpokenIntentCategory.IGNORED,
                raw_text="",
                normalized_text="",
                is_actionable=False,
            )

        # 1. Phonetic normalization of developer slang
        normalized_text = PhoneticNormalizer.normalize(raw_text)

        # 2. Check for Mic Check / Acoustic Test
        if cls.is_mic_check(raw_text) or cls.is_mic_check(normalized_text):
            if is_ambient:
                return ActiveListeningResult(
                    category=SpokenIntentCategory.MIC_CHECK,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    is_actionable=False,
                    quick_spoken_reply=None,
                )

            # In active conversation, reply immediately with vocal reassurance
            if pending_question and pending_question.get("question_text"):
                q_text = pending_question["question_text"]
                reply = f"I hear you loud and clear. {q_text}"
            else:
                reply = "I hear you loud and clear."

            return ActiveListeningResult(
                category=SpokenIntentCategory.MIC_CHECK,
                raw_text=raw_text,
                normalized_text=normalized_text,
                is_actionable=False,
                quick_spoken_reply=reply,
            )

        # 3. Check for Pending Question / Choice Match
        if pending_question:
            matched_option = cls.match_pending_choice(normalized_text, pending_question)
            if matched_option:
                return ActiveListeningResult(
                    category=SpokenIntentCategory.PENDING_ANSWER,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    is_actionable=True,
                    selected_option=matched_option,
                )

        # 4. Check for Conversational Filler / Smalltalk
        if cls.is_conversational_filler(raw_text):
            # Check if there is an actionable command attached (e.g. "Looks great, deploy to staging now")
            has_action_verb = any(
                re.search(rf"\b{verb}\b", normalized_text, re.IGNORECASE)
                for verb in ["deploy", "build", "run", "ship", "push", "test", "fix", "add", "create", "delete", "stage"]
            )
            if not has_action_verb:
                return ActiveListeningResult(
                    category=SpokenIntentCategory.CONVERSATIONAL_FILLER,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    is_actionable=False,
                    quick_spoken_reply=None if is_ambient else "Got it.",
                )

        # 5. Full Actionable Developer Command
        return ActiveListeningResult(
            category=SpokenIntentCategory.ACTIONABLE_COMMAND,
            raw_text=raw_text,
            normalized_text=normalized_text,
            is_actionable=True,
        )
