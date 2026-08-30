"""
VoiceFi Recursive Self-Learning Engine.
Provides phonetic spoken-code self-correction and adaptive cognitive brevity learning.
"""

from voicefi.learning.phonetic import PhoneticLearner
from voicefi.learning.brevity import BrevityLearner

__all__ = ["PhoneticLearner", "BrevityLearner"]
