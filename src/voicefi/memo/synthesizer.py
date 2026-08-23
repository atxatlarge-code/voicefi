"""
Voice Memo Processing for VoiceFi.
Preserves developer thought fidelity with zero interpretation and light cleanup.
"""

from typing import Optional
from voicefi.config import VoiceFiConfig, load_config
from voicefi.memo.cleaner import MemoCleaner
from voicefi.memo.models import CleanedMemo, SynthesizedMemo


class MemoSynthesizer(MemoCleaner):
    """
    Backwards-compatible wrapper around MemoCleaner.
    Cleans raw speech without generating artificial diagrams or plans.
    """

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        super().__init__(config=config)

