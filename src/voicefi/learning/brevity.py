"""
Adaptive Cognitive Brevity & Interruption Learner for VoiceFi.
Dynamically tunes AI agent spoken turn length based on real-time developer barge-in feedback.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional


def get_cognitive_profile_path() -> Path:
    """Return path to persistent cognitive brevity profile."""
    path = Path.home() / ".voicefi"
    path.mkdir(parents=True, exist_ok=True)
    return path / "cognitive_profile.json"


class BrevityLearner:
    """
    Learns developer conversational tolerance and dynamically compresses spoken responses.
    """

    _instance: Optional["BrevityLearner"] = None

    DEFAULT_MAX_WORDS = 24
    MIN_MAX_WORDS = 10
    MAX_MAX_WORDS = 40

    def __init__(self, profile_path: Optional[Path] = None):
        self.profile_path = profile_path or get_cognitive_profile_path()
        self.total_turns: int = 0
        self.total_interruptions: int = 0
        self.learned_max_words: int = self.DEFAULT_MAX_WORDS
        self._load_profile()

    @classmethod
    def get_instance(cls) -> "BrevityLearner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_profile(self):
        """Load cognitive profile from disk."""
        if self.profile_path.is_file():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.total_turns = data.get("total_turns", 0)
                    self.total_interruptions = data.get("total_interruptions", 0)
                    self.learned_max_words = data.get("learned_max_words", self.DEFAULT_MAX_WORDS)
            except Exception:
                self.total_turns = 0
                self.total_interruptions = 0
                self.learned_max_words = self.DEFAULT_MAX_WORDS
        else:
            self.total_turns = 0
            self.total_interruptions = 0
            self.learned_max_words = self.DEFAULT_MAX_WORDS

    def _save_profile(self):
        """Save cognitive profile to disk."""
        try:
            tmp_path = self.profile_path.with_suffix(".tmp")
            data = {
                "version": 1,
                "total_turns": self.total_turns,
                "total_interruptions": self.total_interruptions,
                "interruption_rate": self.get_interruption_rate(),
                "learned_max_words": self.learned_max_words,
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.profile_path)
        except Exception:
            pass

    def record_turn(self, word_count: int, was_interrupted: bool = False) -> None:
        """
        Record a spoken turn completion and recursively adjust target brevity limit.
        """
        self.total_turns += 1
        if was_interrupted:
            self.total_interruptions += 1
            # User barged in -> decrease target max words to make soundbites punchier
            self.learned_max_words = max(self.MIN_MAX_WORDS, self.learned_max_words - 2)
        else:
            # User listened through -> gently increase allowance if consistently completed
            if self.total_turns % 5 == 0 and self.learned_max_words < self.DEFAULT_MAX_WORDS:
                self.learned_max_words = min(self.MAX_MAX_WORDS, self.learned_max_words + 1)

        self._save_profile()

    def get_interruption_rate(self) -> float:
        """Calculate percentage of turns interrupted by developer barge-in."""
        if self.total_turns == 0:
            return 0.0
        return round(self.total_interruptions / self.total_turns, 3)

    def get_optimal_max_words(self) -> int:
        """Return the learned optimal word count limit for spoken turns."""
        return self.learned_max_words

    def format_soundbite(self, text: str) -> str:
        """
        Extract the most critical sentence/clause from text that fits within the learned max words limit.
        """
        if not text or not text.strip():
            return ""

        clean_text = text.strip()
        words = clean_text.split()
        if len(words) <= self.learned_max_words:
            return clean_text

        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        soundbite_parts = []
        current_count = 0

        for s in sentences:
            s_words = s.split()
            if current_count + len(s_words) <= self.learned_max_words:
                soundbite_parts.append(s)
                current_count += len(s_words)
            else:
                if not soundbite_parts:
                    # Take first N words of first sentence
                    soundbite_parts.append(" ".join(s_words[:self.learned_max_words]) + "...")
                break

        return " ".join(soundbite_parts)

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics of brevity profile."""
        return {
            "total_turns": self.total_turns,
            "total_interruptions": self.total_interruptions,
            "interruption_rate_pct": round(self.get_interruption_rate() * 100.0, 1),
            "learned_max_words": self.learned_max_words,
            "profile_file": str(self.profile_path),
        }

    def reset(self) -> None:
        """Reset learned brevity metrics."""
        self.total_turns = 0
        self.total_interruptions = 0
        self.learned_max_words = self.DEFAULT_MAX_WORDS
        if self.profile_path.is_file():
            try:
                self.profile_path.unlink()
            except Exception:
                pass
