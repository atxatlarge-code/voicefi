"""
License and Tier Management for VoiceFi.
Handles feature gates between Community (Open-Source), 14-Day Free Trial, and Pro tiers,
with Hardware-Anchored Cryptographic HMAC Trial Seals and secondary receipt persistence.
"""

import datetime
import hashlib
import hmac
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from voicefi.config import VoiceFiConfig


def get_hardware_identifier() -> str:
    """
    Retrieve immutable macOS Hardware UUID (IOPlatformUUID) to anchor trials to hardware.
    Falls back gracefully to platform network MAC node if not on macOS or permission restricted.
    """
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "IOPlatformUUID" in line:
                        parts = line.split('"')
                        if len(parts) >= 4 and parts[3].strip():
                            return parts[3].strip().lower()
        except Exception:
            pass

    # Fallback to network MAC node hash
    node = uuid.getnode()
    return hashlib.sha256(f"hw-{node}".encode()).hexdigest()[:32]


def compute_trial_hmac(started_at: float, hw_id: str, duration_days: int = 14) -> str:
    """
    Compute cryptographic HMAC-SHA256 seal for trial anchor.
    """
    secret_salt = b"voicefi-trial-v1-secure-mac-seal-2026"
    payload = f"vifi-trial:{int(started_at)}:{hw_id.strip().lower()}:{duration_days}".encode("utf-8")
    return hmac.new(secret_salt, payload, hashlib.sha256).hexdigest()[:32]


def get_secondary_receipt_path() -> Path:
    """
    Path to secondary tamper-resistant receipt in Application Support.
    """
    app_support = Path.home() / "Library" / "Application Support" / "VoiceFi"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / ".trial_receipt"


def save_secondary_receipt(started_at: float, seal: str, hw_id: str, duration_days: int = 14) -> None:
    """Save trial receipt to secondary location with restricted permissions."""
    try:
        receipt_path = get_secondary_receipt_path()
        data = {
            "started_at": float(started_at),
            "seal": seal,
            "hw_id": hw_id,
            "duration_days": int(duration_days),
            "created_at": time.time(),
        }
        receipt_path.write_text(json.dumps(data, indent=2))
        os.chmod(receipt_path, 0o600)
    except Exception:
        pass


def load_secondary_receipt() -> Optional[Dict[str, Any]]:
    """Load and validate secondary receipt from Application Support."""
    try:
        receipt_path = get_secondary_receipt_path()
        if not receipt_path.is_file():
            return None
        data = json.loads(receipt_path.read_text())
        started_at = float(data.get("started_at", 0))
        seal = str(data.get("seal", ""))
        hw_id = str(data.get("hw_id", ""))
        duration = int(data.get("duration_days", 14))

        expected_seal = compute_trial_hmac(started_at, hw_id, duration)
        if hmac.compare_digest(seal, expected_seal):
            return data
    except Exception:
        pass
    return None


class FeatureGate:
    """Controls availability of features based on active tier, org code, trial status, and license key."""

    PRO_MONTHLY_PRICE_USD = 9.0
    PRO_ANNUAL_SPECIAL_USD = 69.0
    PRO_ANNUAL_MONTHLY_EQUIVALENT_USD = 5.75
    TRIAL_DURATION_DAYS = 14

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
    def get_trial_status(cls, config: VoiceFiConfig) -> Dict[str, Any]:
        """
        Compute 14-day free trial status, remaining days/hours, and cryptographic seal integrity.
        """
        tier = getattr(config, "tier", "community").lower().strip()
        license_key = getattr(config, "license_key", "").strip()
        org_code = getattr(config, "org_code", "").strip() if hasattr(config, "org_code") else ""
        is_licensed = tier in ("pro", "org", "enterprise") and (len(license_key) >= 6 or len(org_code) >= 4)

        trial_started_at = getattr(config, "trial_started_at", None)
        trial_seal = getattr(config, "trial_seal", None)
        trial_duration_days = getattr(config, "trial_duration_days", cls.TRIAL_DURATION_DAYS) or cls.TRIAL_DURATION_DAYS

        now = time.time()
        hw_id = get_hardware_identifier()

        if trial_started_at is None:
            # Brand new uninitialized trial
            trial_seconds_total = trial_duration_days * 86400
            expires_epoch = now + trial_seconds_total
            return {
                "is_trial": not is_licensed,
                "is_active": not is_licensed,
                "is_expired": False,
                "days_remaining": trial_duration_days if not is_licensed else 0,
                "hours_remaining": float(trial_duration_days * 24) if not is_licensed else 0.0,
                "started_at_epoch": None,
                "expires_at_epoch": expires_epoch,
                "expires_at_iso": datetime.datetime.fromtimestamp(expires_epoch, tz=datetime.timezone.utc).isoformat(),
                "trial_duration_days": trial_duration_days,
                "is_licensed": is_licensed,
                "tampered": False,
                "hardware_id": hw_id,
            }

        # Validate Cryptographic HMAC Seal
        tampered = False
        if trial_seal:
            expected_seal = compute_trial_hmac(trial_started_at, hw_id, trial_duration_days)
            if not hmac.compare_digest(trial_seal, expected_seal):
                tampered = True
        else:
            # Missing seal on existing started_at
            receipt = load_secondary_receipt()
            if receipt and receipt.get("hw_id") == hw_id:
                trial_started_at = receipt["started_at"]
                trial_seal = receipt["seal"]
            else:
                tampered = False

        # Clock Rollback Detection (system clock moved more than 5 minutes before started_at)
        if float(trial_started_at) > now + 300:
            tampered = True

        if tampered and not is_licensed:
            # Invalidate trial if tampered
            return {
                "is_trial": True,
                "is_active": False,
                "is_expired": True,
                "days_remaining": 0,
                "hours_remaining": 0.0,
                "started_at_epoch": float(trial_started_at),
                "expires_at_epoch": now,
                "expires_at_iso": datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).isoformat(),
                "trial_duration_days": trial_duration_days,
                "is_licensed": False,
                "tampered": True,
                "hardware_id": hw_id,
            }

        trial_seconds_total = trial_duration_days * 86400
        elapsed = max(0.0, now - float(trial_started_at))
        remaining_seconds = max(0.0, trial_seconds_total - elapsed)
        days_remaining = max(0, int(math.ceil(remaining_seconds / 86400.0)))
        hours_remaining = round(remaining_seconds / 3600.0, 1)
        is_active = remaining_seconds > 0
        is_expired = not is_active
        expires_epoch = float(trial_started_at) + trial_seconds_total
        expires_iso = datetime.datetime.fromtimestamp(expires_epoch, tz=datetime.timezone.utc).isoformat()

        return {
            "is_trial": not is_licensed,
            "is_active": is_active and not is_licensed,
            "is_expired": is_expired and not is_licensed,
            "days_remaining": days_remaining if not is_licensed else 0,
            "hours_remaining": hours_remaining if not is_licensed else 0.0,
            "started_at_epoch": float(trial_started_at),
            "expires_at_epoch": expires_epoch,
            "expires_at_iso": expires_iso,
            "trial_duration_days": trial_duration_days,
            "is_licensed": is_licensed,
            "tampered": False,
            "hardware_id": hw_id,
        }

    @classmethod
    def is_pro(cls, config: VoiceFiConfig) -> bool:
        """Check if user has Pro or Org tier enabled with a valid license or active 14-day free trial."""
        tier = getattr(config, "tier", "community").lower().strip()
        license_key = getattr(config, "license_key", "").strip()
        org_code = getattr(config, "org_code", "").strip() if hasattr(config, "org_code") else ""

        if tier in ("pro", "org", "enterprise") and (len(license_key) >= 6 or len(org_code) >= 4):
            return True

        trial = cls.get_trial_status(config)
        if trial.get("is_active"):
            return True

        return False

    @classmethod
    def can_run_app(cls, config: VoiceFiConfig) -> bool:
        """
        Verify if the macOS native application / daemon is permitted to run.
        The DMG is a paid commercial product ($9/mo or $69/yr):
        - Allowed during the 14-day free trial.
        - Allowed with a valid Developer Pro / Org license key.
        - Blocked if the trial is expired without a license.
        """
        return cls.is_pro(config)

    @classmethod
    def get_paywall_message(cls, config: VoiceFiConfig) -> str:
        """Return user-facing paywall prompt with pricing and checkout link."""
        return (
            f"🔒 VoiceFi 14-Day Free Trial Expired\n\n"
            f"VoiceFi for macOS requires an active Developer Pro license (${int(cls.PRO_MONTHLY_PRICE_USD)}/mo or ${int(cls.PRO_ANNUAL_SPECIAL_USD)}/yr Special Pass).\n\n"
            f"👉 Visit https://voicefi.app to unlock your license key."
        )

    @classmethod
    def can_use_feature(cls, feature_name: str, config: VoiceFiConfig) -> bool:
        """Verify if a specific feature is enabled for the active tier."""
        if feature_name in cls.PRO_PROVIDERS:
            return cls.is_pro(config)
        return True

    @classmethod
    def get_tier_summary(cls, config: VoiceFiConfig) -> Dict[str, Any]:
        """Return human-readable tier status, trial countdown, pricing, and capabilities."""
        trial = cls.get_trial_status(config)
        tier = getattr(config, "tier", "community").lower().strip()
        license_key = getattr(config, "license_key", "").strip()
        org_code = getattr(config, "org_code", "").strip() if hasattr(config, "org_code") else ""
        is_licensed = tier in ("pro", "org", "enterprise") and (len(license_key) >= 6 or len(org_code) >= 4)
        pro_active = is_licensed or trial["is_active"]

        if is_licensed:
            tier_label = tier.capitalize()
            status_text = f"{tier_label} (Licensed)"
        elif trial["tampered"]:
            tier_label = "Community (Seal Tampered)"
            status_text = "Community ($0 / OSS · Trial Invalid)"
        elif trial["is_active"]:
            days = trial["days_remaining"]
            tier_label = f"Pro Trial ({days}d left)" if days > 0 else "Pro Trial (Ends Today)"
            status_text = f"Pro (14-Day Free Trial · {days} days remaining)" if days > 0 else "Pro (14-Day Free Trial · Ends Today)"
        elif trial["is_expired"]:
            tier_label = "Community (Trial Expired)"
            status_text = "Community ($0 / OSS · 14-Day Trial Expired)"
        else:
            tier_label = "Community (.org)"
            status_text = "Community ($0 / OSS)"

        return {
            "tier": tier_label,
            "status_text": status_text,
            "is_licensed": is_licensed,
            "is_pro": pro_active,
            "is_trial": trial["is_trial"] and trial["is_active"],
            "trial_expired": trial["is_expired"],
            "trial_days_remaining": trial["days_remaining"],
            "trial_hours_remaining": trial["hours_remaining"],
            "trial_expires_at": trial["expires_at_iso"],
            "pricing": {
                "monthly_usd": cls.PRO_MONTHLY_PRICE_USD,
                "annual_special_usd": cls.PRO_ANNUAL_SPECIAL_USD,
                "annual_monthly_equivalent": cls.PRO_ANNUAL_MONTHLY_EQUIVALENT_USD,
                "trial_duration_days": cls.TRIAL_DURATION_DAYS,
                "upgrade_url": "https://voicefi.org#pricing",
                "app_url": "https://voicefi.app",
            },
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

    @classmethod
    def ensure_trial_started(cls, config: VoiceFiConfig, save: bool = True) -> VoiceFiConfig:
        """
        Ensure trial timestamp and hardware-anchored HMAC seal are initialized.
        Restores from secondary receipt if config was reset or deleted.
        """
        from voicefi.config import save_config

        if getattr(config, "license_key", "").strip():
            return config

        hw_id = get_hardware_identifier()
        receipt = load_secondary_receipt()

        if receipt and receipt.get("hw_id") == hw_id:
            # Restore true trial anchor from secondary receipt
            config.trial_started_at = receipt["started_at"]
            config.trial_seal = receipt["seal"]
            config.trial_duration_days = receipt.get("duration_days", 14)
        elif config.trial_started_at is None or config.trial_seal is None:
            # Brand new machine trial initialization
            now = time.time()
            config.trial_started_at = now
            config.trial_duration_days = cls.TRIAL_DURATION_DAYS
            config.trial_seal = compute_trial_hmac(now, hw_id, config.trial_duration_days)
            save_secondary_receipt(config.trial_started_at, config.trial_seal, hw_id, config.trial_duration_days)

        if save:
            try:
                save_config(config)
            except Exception:
                pass

        return config
