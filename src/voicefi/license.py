"""
License and Tier Management for VoiceFi.
Handles feature gates between Community (Open-Source) and Pro tiers.
"""

from typing import Dict, Any, Optional
from voicefi.config import VoiceFiConfig


class FeatureGate:
    """Controls availability of features based on active tier, org code, and license key."""

    PRO_PROVIDERS = {
        "elevenlabs",
        "openai_realtime",
        "cartesia",
        "deepgram",
        "streaming_stt",
        "realtime_token_stream",
        "cloud_realtime_stt",
        "auto_update",
    }

    @classmethod
    def is_pro(cls, config: VoiceFiConfig) -> bool:
        """Check if user has Pro or Org tier enabled with a valid license format or code."""
        tier = getattr(config, "tier", "community").lower().strip()
        license_key = getattr(config, "license_key", "").strip()
        org_code = getattr(config, "org_code", "").strip() if hasattr(config, "org_code") else ""

        if tier in ("pro", "org", "enterprise") and (len(license_key) >= 6 or len(org_code) >= 4):
            return True
        return False

    @classmethod
    def can_use_feature(cls, feature_name: str, config: VoiceFiConfig) -> bool:
        """Verify if a specific feature is enabled for the active tier."""
        if feature_name in cls.PRO_PROVIDERS:
            return cls.is_pro(config)
        return True

    @classmethod
    def get_tier_summary(cls, config: VoiceFiConfig) -> Dict[str, Any]:
        """Return human-readable tier status and capabilities."""
        pro_active = cls.is_pro(config)
        tier_label = getattr(config, "tier", "community").capitalize() if pro_active else "Community (.org)"
        return {
            "tier": tier_label,
            "license_valid": pro_active,
            "features": {
                "mac_say_tts": True,
                "edge_tts": True,
                "whisper_local_stt": True,
                "groq_stt": True,
                "antigravity_hooks": True,
                "global_hotkey": True,
                "streaming_stt": pro_active,
                "realtime_token_stream": pro_active,
                "elevenlabs_neural": pro_active,
                "custom_wake_words": pro_active,
                "multi_agent_dashboard": pro_active,
                "auto_update": pro_active,
            },
        }
