"""
Native macOS Floating Agent Speech HUD Capsule (Unified Dynamic Island Adapter).
Routes all agent speech pop-up displays and subtitle updates directly to the single
Unified Dynamic Island HUD container.
"""

from typing import Optional, Dict, Any
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD, AVATAR_ICONS


class AgentSpeechHUD:
    """Compatibility Adapter routing all speech popup calls to the UnifiedDynamicIslandHUD."""

    _instance: Optional[UnifiedDynamicIslandHUD] = None

    @classmethod
    def get_instance(cls) -> UnifiedDynamicIslandHUD:
        return UnifiedDynamicIslandHUD.get_instance()
