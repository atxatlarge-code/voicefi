"""
Native macOS Floating Dictation HUD Capsule (Unified Dynamic Island Adapter).
Routes all dictation HUD calls directly to the single Unified Dynamic Island HUD container.
"""

from typing import Optional
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


class DictationHUD:
    """Compatibility Adapter routing all dictation HUD calls to the UnifiedDynamicIslandHUD."""

    _instance: Optional[UnifiedDynamicIslandHUD] = None

    @classmethod
    def get_instance(cls) -> UnifiedDynamicIslandHUD:
        return UnifiedDynamicIslandHUD.get_instance()
