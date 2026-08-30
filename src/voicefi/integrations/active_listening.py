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
    ROUTED_COMMAND = "ROUTED_COMMAND"
    IGNORED = "IGNORED"


class SpokenTargetChannel(str, Enum):
    ANTIGRAVITY = "antigravity"
    CLAUDE = "claude"
    SLACK = "slack"
    LINEAR = "linear"
    GENERAL = "general"


@dataclass
class ActiveListeningResult:
    category: SpokenIntentCategory
    raw_text: str
    normalized_text: str
    is_actionable: bool
    target_channel: SpokenTargetChannel = SpokenTargetChannel.ANTIGRAVITY
    routed_prompt: Optional[str] = None
    target_metadata: Optional[Dict[str, Any]] = None
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
    def match_pending_choice(cls, text: str, pending_question: Dict[str, Any]) -> Optional[str]:
        """
        Match spoken response against multiple choices in pending question.
        Returns the matched canonical option string, or None if no match.
        """
        if not pending_question or "options" not in pending_question:
            return None

        clean_text = text.strip().lower()
        options = pending_question["options"]
        if not options:
            return None

        # 1. Exact match against option text
        for opt in options:
            opt_clean = opt.strip().lower()
            if clean_text == opt_clean:
                return opt
            if opt_clean in clean_text:
                return opt

        # 2. Key content word matching
        text_words = set(re.findall(r"\b[a-z0-9]+\b", clean_text)) - cls.STOP_WORDS
        best_opt = None
        best_overlap = 0

        for opt in options:
            opt_words = set(re.findall(r"\b[a-z0-9]+\b", opt.lower())) - cls.STOP_WORDS
            if not opt_words:
                continue
            overlap = text_words.intersection(opt_words)
            overlap_score = float(len(overlap))
            # Prefix/stem overlap (e.g. stage <-> staging, deploy <-> deployment)
            for tw in text_words:
                for ow in opt_words:
                    if len(tw) >= 4 and len(ow) >= 4:
                        if (tw.startswith(ow[:4]) or ow.startswith(tw[:4])) and tw != ow:
                            overlap_score += 0.8
            if overlap_score > best_overlap:
                best_overlap = overlap_score
                best_opt = opt

        if best_opt and best_overlap > 0:
            return best_opt

        return None

    @classmethod
    def resolve_target_channel(cls, text: str) -> tuple[SpokenTargetChannel, str, Dict[str, Any]]:
        """
        Detect if spoken command is explicitly directed to a specific tool or agent channel
        (e.g., Claude Code, Slack, Linear, or default Antigravity).
        """
        if not text or not text.strip():
            return SpokenTargetChannel.ANTIGRAVITY, text, {}

        clean = text.strip()

        # 1. Claude Code Direct Routing
        claude_patterns = [
            r"^(?:(?:ask|tell|have|send\s+to|switch\s+to)\s+)?claude(?:\s+code)?(?:\s+to|\s*:\s*|\s*,\s*|\s+)\s*(.+)$",
            r"^claude,\s*(.+)$",
        ]
        for pat in claude_patterns:
            m = re.match(pat, clean, re.IGNORECASE)
            if m:
                routed = m.group(1).strip()
                return SpokenTargetChannel.CLAUDE, routed, {"original_agent": "claude"}

        # 2. Slack Channel Routing
        slack_explicit_ch = r"^(?:(?:post|send|message|share|drop)\s+(?:in|into|to|on)\s+slack\s+(?:channel\s+)?#?([a-zA-Z0-9_-]+)(?:\s+that|\s+saying|\s*:\s*|\s*,\s*|\s+)\s*(.+))$"
        slack_general = r"^(?:(?:post|send|message|share|drop)\s+(?:in|into|to|on)\s+slack(?:\s+that|\s+saying|\s*:\s*|\s*,\s*|\s+)\s*(.+))$"

        m_slack_ch = re.match(slack_explicit_ch, clean, re.IGNORECASE)
        if m_slack_ch:
            ch_cand = m_slack_ch.group(1).lower().lstrip("#")
            if ch_cand not in ("that", "this", "saying", "a", "an", "the"):
                msg = m_slack_ch.group(2).strip()
                return SpokenTargetChannel.SLACK, msg, {"channel": ch_cand}

        m_slack_gen = re.match(slack_general, clean, re.IGNORECASE)
        if m_slack_gen:
            msg = m_slack_gen.group(1).strip()
            return SpokenTargetChannel.SLACK, msg, {"channel": "general"}

        # 3. Linear Ticket Routing
        linear_pattern = r"^(?:(?:create|open|log|file|make)\s+(?:a\s+)?(?:new\s+)?linear\s+(?:ticket|issue|bug|task)(?:\s+for|\s+to|\s+titled|\s*:\s*|\s+)?\s*(.+))$"
        m_linear = re.match(linear_pattern, clean, re.IGNORECASE)
        if m_linear:
            title = m_linear.group(1).strip()
            return SpokenTargetChannel.LINEAR, title, {"title": title}

        # 4. Antigravity Direct Routing
        ag_pattern = r"^(?:(?:ask|tell|have)\s+)?antigravity(?:\s+to|\s*:\s*|\s*,\s*|\s+)\s*(.+)$"
        m_ag = re.match(ag_pattern, clean, re.IGNORECASE)
        if m_ag:
            return SpokenTargetChannel.ANTIGRAVITY, m_ag.group(1).strip(), {}

        return SpokenTargetChannel.ANTIGRAVITY, clean, {}

    @classmethod
    def evaluate(
        cls,
        raw_text: str,
        pending_question: Optional[Dict[str, Any]] = None,
        is_ambient: bool = False,
    ) -> ActiveListeningResult:
        """
        Evaluate transcribed spoken audio against intent taxonomy.
        """
        if not raw_text or not raw_text.strip():
            return ActiveListeningResult(
                category=SpokenIntentCategory.CONVERSATIONAL_FILLER,
                raw_text="",
                normalized_text="",
                is_actionable=False,
            )

        # 1. Spoken Code Normalization
        normalized_text = PhoneticNormalizer.normalize(raw_text)

        # 2. Check for Mic Check / Audio Test
        if cls.is_mic_check(raw_text):
            if pending_question and pending_question.get("question_text"):
                q_text = pending_question["question_text"]
                reply = f"Loud and clear! I'm waiting on your choice: {q_text}"
            else:
                reply = "Loud and clear! Ready for your command."

            return ActiveListeningResult(
                category=SpokenIntentCategory.MIC_CHECK,
                raw_text=raw_text,
                normalized_text=normalized_text,
                is_actionable=False,
                quick_spoken_reply=None if is_ambient else reply,
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

        # 5. Check for Routed Intent vs Standard Actionable Command
        target_ch, routed_text, metadata = cls.resolve_target_channel(normalized_text)
        is_routed = (target_ch != SpokenTargetChannel.ANTIGRAVITY)

        return ActiveListeningResult(
            category=SpokenIntentCategory.ROUTED_COMMAND if is_routed else SpokenIntentCategory.ACTIONABLE_COMMAND,
            raw_text=raw_text,
            normalized_text=normalized_text,
            is_actionable=True,
            target_channel=target_ch,
            routed_prompt=routed_text,
            target_metadata=metadata,
        )

    @classmethod
    def extract_wakeword_and_prompt(
        cls,
        text: str,
        aliases: Optional[List[str]] = None,
    ) -> tuple[Optional[str], str]:
        """
        Detect if spoken text begins with or contains a wake word (e.g. 'Hey Viv', 'Viv', 'Hey ViFi'),
        and return (matched_phrase, clean_prompt).
        If the utterance only contained the wake word, clean_prompt will be empty string.
        """
        if not text or not text.strip():
            return None, ""

        clean = text.strip()
        default_names = [
            "viv", "vive", "vifi", "vivi", "wifi", "wi-fi", "antigravity", "eve", "fifi",
            "vim", "veev", "bib", "beb", "thief", "here's", "biff", "vee"
        ]
        prefixes = ["hey", "hi", "okay", "ok", "yo", "hello", "a", "eh"]

        all_aliases = list(aliases or [])
        for name in default_names:
            all_aliases.append(name)
            for p in prefixes:
                all_aliases.append(f"{p} {name}")

        # Sort aliases by length descending so longer phrases match first
        sorted_aliases = sorted(list(set(all_aliases)), key=lambda a: len(a), reverse=True)

        for alias in sorted_aliases:
            words = alias.strip().split()
            pattern_words = r"[\s,.:;!?-]+".join(re.escape(w) for w in words)
            pattern = rf"^(?:{pattern_words})(?:[\s,.:;!?-]+(.*)|$)"
            m = re.match(pattern, clean, re.IGNORECASE)
            if m:
                matched_phrase = alias.strip()
                remainder = m.group(1) if m.group(1) else ""
                # Strip leading punctuation and conjunctions
                remainder = re.sub(r"^[\s,.:;!?-]+", "", remainder)
                return matched_phrase, remainder.strip()

        return None, clean
