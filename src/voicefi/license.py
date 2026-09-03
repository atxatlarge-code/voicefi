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
    payload = f"vifi-trial:{int(started_at)}:{hw_id.strip().lower()}:{duration_days}".encode(
        "utf-8"
    )
    return hmac.new(secret_salt, payload, hashlib.sha256).hexdigest()[:32]


def get_secondary_receipt_path() -> Path:
    """
    Path to secondary tamper-resistant receipt in Application Support.
    """
    app_support = Path.home() / "Library" / "Application Support" / "VoiceFi"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / ".trial_receipt"


def save_secondary_receipt(
    started_at: float, seal: str, hw_id: str, duration_days: int = 14
) -> None:
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


# Master Ed25519 Public Verification Key (Safe to commit to public open-source)
PUBLIC_VERIFICATION_KEY_HEX = (
    "964b998cb1d6721a9b674c820031454f8213d0a038aa18c792792d550ae66426"
)


def generate_license_key(
    tier: str = "PRO",
    expires: str = "PERP",
    tag: str = "USER",
    private_key_hex: Optional[str] = None,
) -> str:
    """
    Generate an unforgeable, Ed25519 cryptographically signed VoiceFi license token.
    Requires private signing key (from argument, env var VOICEFI_SIGNING_PRIVATE_KEY, or ~/.voicefi/admin_keys/).
    
    Format: VF1-<TIER>-<EXPIRATION>-<TAG>.<SIGNATURE_B64>
    - TIER: PRO, ORG, ENTERPRISE, VIP, BETA
    - EXPIRATION: PERP (perpetual) or YYYYMMDD
    - TAG: alphanumeric recipient / promo identifier
    - SIGNATURE_B64: 86-char URL-safe Base64 Ed25519 signature
    """
    import base64
    from cryptography.hazmat.primitives.asymmetric import ed25519

    tier_clean = tier.upper().strip()
    expires_clean = expires.upper().strip()
    tag_clean = "".join(
        c for c in tag.upper().strip().replace(" ", "_") if c.isalnum() or c == "_"
    )
    if not tag_clean:
        tag_clean = "GIFT"

    priv_hex = private_key_hex or os.environ.get("VOICEFI_SIGNING_PRIVATE_KEY")
    if not priv_hex:
        key_path = Path.home() / ".voicefi" / "admin_keys" / "voicefi_ed25519_private.key"
        if key_path.is_file():
            priv_hex = key_path.read_text().strip()

    if not priv_hex:
        raise ValueError(
            "Private signing key not found. Please set VOICEFI_SIGNING_PRIVATE_KEY or ensure ~/.voicefi/admin_keys/ is present."
        )

    priv_bytes = bytes.fromhex(priv_hex.strip())
    priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    prefix = f"VF1-{tier_clean}-{expires_clean}-{tag_clean}"
    payload = prefix.encode("utf-8")
    sig = priv_key.sign(payload)
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

    return f"{prefix}.{sig_b64}"


def _ed25519_verify_pure(pub_bytes: bytes, msg_bytes: bytes, sig_bytes: bytes) -> bool:
    """RFC 8032 pure-Python Ed25519 verification with zero external dependencies."""
    if len(sig_bytes) != 64 or len(pub_bytes) != 32:
        return False
    q = 2**255 - 19
    l = 2**252 + 27742317777372353535851937790883648493
    d = -121665 * pow(121666, q - 2, q) % q
    I = pow(2, (q - 1) // 4, q)

    def inv(z):
        return pow(z, q - 2, q)

    def xrecover(y):
        xx = (y * y - 1) * inv(d * y * y + 1)
        x = pow(xx, (q + 3) // 8, q)
        if (x * x - xx) % q != 0:
            x = (x * I) % q
        if x % 2 != 0:
            x = q - x
        return x

    By = 4 * inv(5) % q
    Bx = xrecover(By)
    B = (Bx, By)

    def edwards_add(P, Q):
        x1, y1 = P
        x2, y2 = Q
        x3 = (x1 * y2 + x2 * y1) * inv(1 + d * x1 * x2 * y1 * y2) % q
        y3 = (y1 * y2 + x1 * x2) * inv(1 - d * x1 * x2 * y1 * y2) % q
        return (x3, y3)

    def scalarmult(P, e):
        if e == 0:
            return (0, 1)
        Q = scalarmult(P, e // 2)
        Q = edwards_add(Q, Q)
        if e & 1:
            Q = edwards_add(Q, P)
        return Q

    def decodepoint(s):
        y = sum(2 ** (i * 8) * b for i, b in enumerate(s[:31])) + sum(
            2 ** (248 + i * 8) * (b & 0x7F) for i, b in enumerate(s[31:])
        )
        x = xrecover(y)
        if (x & 1) != (s[31] >> 7):
            x = q - x
        return (x, y)

    R_bytes, S_bytes = sig_bytes[:32], sig_bytes[32:]
    S = int.from_bytes(S_bytes, "little")
    if S >= l:
        return False
    try:
        A = decodepoint(pub_bytes)
        R = decodepoint(R_bytes)
    except Exception:
        return False
    h = hashlib.sha512(R_bytes + pub_bytes + msg_bytes).digest()
    k = int.from_bytes(h, "little") % l
    SB = scalarmult(B, S)
    RA = edwards_add(R, scalarmult(A, k))
    return SB == RA


def verify_license_key(key: str) -> Dict[str, Any]:
    """
    Verify asymmetric Ed25519 cryptographic signature and expiration of a VoiceFi license token.
    Runs 100% offline in 0ms using the embedded public key with zero network requests.
    """
    import base64

    if not key or not isinstance(key, str):
        return {"is_valid": False, "error": "Empty license key"}

    key_clean = key.strip()

    # Split by dot (standard token format)
    if "." in key_clean:
        parts = key_clean.split(".", 1)
        prefix = parts[0].upper()
        sig_str = parts[1]
    elif "-" in key_clean:
        # Fallback for hyphen-delimited input
        parts = key_clean.rsplit("-", 1)
        prefix = parts[0].upper()
        sig_str = parts[1]
    else:
        return {"is_valid": False, "error": "Invalid license format (must start with VF1-)"}

    prefix_parts = prefix.split("-")
    if len(prefix_parts) < 4 or prefix_parts[0] != "VF1":
        return {"is_valid": False, "error": "Invalid license prefix (expected VF1-<TIER>-<EXP>-<TAG>)"}

    tier = prefix_parts[1]
    expires_str = prefix_parts[2]
    tag = "-".join(prefix_parts[3:])

    # Decode and verify Ed25519 signature
    try:
        sig_padded = sig_str + "=" * (-len(sig_str) % 4)
        sig_bytes = base64.urlsafe_b64decode(sig_padded)
        if len(sig_bytes) != 64:
            return {"is_valid": False, "error": "Invalid signature length"}

        pub_bytes = bytes.fromhex(PUBLIC_VERIFICATION_KEY_HEX)
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519

            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub_key.verify(sig_bytes, prefix.encode("utf-8"))
        except ImportError:
            if not _ed25519_verify_pure(pub_bytes, prefix.encode("utf-8"), sig_bytes):
                return {"is_valid": False, "error": "Invalid cryptographic license signature"}
    except Exception:
        return {"is_valid": False, "error": "Invalid cryptographic license signature"}

    # Expiration check
    is_expired = False
    expires_at = "Perpetual"
    if expires_str != "PERP":
        try:
            exp_date = datetime.datetime.strptime(expires_str, "%Y%m%d").date()
            exp_epoch = datetime.datetime.combine(
                exp_date, datetime.time(23, 59, 59), tzinfo=datetime.timezone.utc
            ).timestamp()
            if time.time() > exp_epoch:
                is_expired = True
            expires_at = exp_date.isoformat()
        except Exception:
            return {"is_valid": False, "error": f"Invalid expiration date format: {expires_str}"}

    return {
        "is_valid": not is_expired,
        "tier": tier.lower(),
        "is_expired": is_expired,
        "expires_at": expires_at,
        "expires_str": expires_str,
        "tag": tag,
        "error": "License key has expired" if is_expired else None,
    }


class FeatureGate:
    """Controls availability of features based on active tier, org code, trial status, and license key."""

    PRO_MONTHLY_PRICE_USD = 9.0
    PRO_ANNUAL_SPECIAL_USD = 69.0
    PRO_ANNUAL_MONTHLY_EQUIVALENT_USD = 5.75
    TRIAL_DURATION_DAYS = 14

    CHECKOUT_URL_MONTHLY = "https://buy.polar.sh/polar_cl_tuzY4BeC8xUOOBTihmRwU2HPzSdPlG2KHSwSC4RJND7"
    CHECKOUT_URL_ANNUAL = "https://buy.polar.sh/polar_cl_CUG0WaMQ6H38cmU1hlwnmcyf63Oj9Js4N1myZ34MEcU"
    UPGRADE_URL = "https://voicefi.org#pricing"

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
    def verify_key(cls, license_key: str) -> Dict[str, Any]:
        """Verify license key signature and expiration."""
        return verify_license_key(license_key)

    @classmethod
    def get_license_status(cls, config: VoiceFiConfig) -> Dict[str, Any]:
        """Check stored license key or org code validity."""
        license_key = getattr(config, "license_key", "").strip()
        org_code = getattr(config, "org_code", "").strip() if hasattr(config, "org_code") else ""
        tier = getattr(config, "tier", "community").lower().strip()

        if org_code and len(org_code) >= 4 and tier in ("org", "enterprise"):
            return {
                "is_licensed": True,
                "tier": tier,
                "is_expired": False,
                "expires_at": "Enterprise",
                "tag": org_code,
                "error": None,
            }

        if not license_key:
            return {"is_licensed": False, "error": "No license key configured"}

        v = verify_license_key(license_key)
        return {
            "is_licensed": v["is_valid"],
            "tier": v.get("tier", tier),
            "is_expired": v.get("is_expired", False),
            "expires_at": v.get("expires_at"),
            "tag": v.get("tag", ""),
            "error": v.get("error"),
        }

    @classmethod
    def get_trial_status(cls, config: VoiceFiConfig) -> Dict[str, Any]:
        """
        Compute 14-day free trial status, remaining days/hours, and cryptographic seal integrity.
        """
        lic_status = cls.get_license_status(config)
        is_licensed = lic_status["is_licensed"]

        trial_started_at = getattr(config, "trial_started_at", None)
        trial_seal = getattr(config, "trial_seal", None)
        trial_duration_days = (
            getattr(config, "trial_duration_days", cls.TRIAL_DURATION_DAYS)
            or cls.TRIAL_DURATION_DAYS
        )

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
                "expires_at_iso": datetime.datetime.fromtimestamp(
                    expires_epoch, tz=datetime.timezone.utc
                ).isoformat(),
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
                "expires_at_iso": datetime.datetime.fromtimestamp(
                    now, tz=datetime.timezone.utc
                ).isoformat(),
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
        expires_iso = datetime.datetime.fromtimestamp(
            expires_epoch, tz=datetime.timezone.utc
        ).isoformat()

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
        lic_status = cls.get_license_status(config)
        if lic_status.get("is_licensed"):
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
        lic_status = cls.get_license_status(config)
        is_licensed = lic_status["is_licensed"]
        trial = cls.get_trial_status(config)
        pro_active = is_licensed or trial["is_active"]

        if is_licensed:
            tier_val = lic_status.get("tier", "pro").capitalize()
            expires_at = lic_status.get("expires_at", "Perpetual")
            tier_label = tier_val
            status_text = f"{tier_val} (Licensed · {expires_at})"
        elif trial["tampered"]:
            tier_label = "Community (Seal Tampered)"
            status_text = "Community ($0 / OSS · Trial Invalid)"
        elif trial["is_active"]:
            days = trial["days_remaining"]
            tier_label = f"Pro Trial ({days}d left)" if days > 0 else "Pro Trial (Ends Today)"
            status_text = (
                f"Pro (14-Day Free Trial · {days} days remaining)"
                if days > 0
                else "Pro (14-Day Free Trial · Ends Today)"
            )
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
            "license_info": lic_status,
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
                "upgrade_url": cls.UPGRADE_URL,
                "checkout_monthly": cls.CHECKOUT_URL_MONTHLY,
                "checkout_annual": cls.CHECKOUT_URL_ANNUAL,
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
            save_secondary_receipt(
                config.trial_started_at, config.trial_seal, hw_id, config.trial_duration_days
            )

        if save:
            try:
                save_config(config)
            except Exception:
                pass

        return config

    @classmethod
    def sync_cloud_license(
        cls, config: VoiceFiConfig, force: bool = False, timeout: float = 3.0
    ) -> Dict[str, Any]:
        """Silently sync subscription license renewals with voicefi.org in background."""
        return sync_license_with_cloud(config, force=force, timeout=timeout)


def sync_license_with_cloud(
    config: VoiceFiConfig, force: bool = False, timeout: float = 3.0
) -> Dict[str, Any]:
    """
    Silently sync time-bound subscription license with voicefi.org in background.
    If the subscription was renewed on Polar, updates config.license_key with the extended token.
    Runs with 3.0s timeout and never raises exceptions.
    """
    import urllib.request
    import urllib.error
    from voicefi.config import save_config

    license_key = getattr(config, "license_key", "").strip()
    if not license_key:
        return {"synced": False, "reason": "No license key configured"}

    # Perpetual keys never need online renewal
    if "-PERP-" in license_key:
        return {"synced": True, "is_perp": True, "expires_at": "Perpetual"}

    # Local verification
    local_ver = verify_license_key(license_key)
    if not local_ver["is_valid"] and local_ver.get("error") != "License key has expired":
        return {"synced": False, "error": local_ver.get("error")}

    # Rate limiting: only check once every 24 hours unless forced or expiring within 7 days
    now = time.time()
    last_sync = getattr(config, "last_license_sync", 0.0) or 0.0
    is_expiring_soon = False

    if local_ver.get("expires_at") and local_ver["expires_at"] != "Perpetual":
        try:
            exp_date = datetime.datetime.strptime(local_ver["expires_str"], "%Y%m%d").date()
            days_left = (exp_date - datetime.date.today()).days
            if days_left <= 7:
                is_expiring_soon = True
        except Exception:
            pass

    if not force and not is_expiring_soon and (now - last_sync) < 86400:
        return {"synced": True, "cached": True, "expires_at": local_ver.get("expires_at")}

    # Cloud sync request to voicefi.org
    try:
        hw_id = get_hardware_identifier()
        payload = json.dumps({"license_key": license_key, "hw_id": hw_id}).encode("utf-8")
        req = urllib.request.Request(
            "https://voicefi.org/api/license/sync",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "VoiceFi-Mac/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                config.last_license_sync = now

                if data.get("renewed") and data.get("license_key"):
                    new_key = data["license_key"].strip()
                    new_ver = verify_license_key(new_key)
                    if new_ver["is_valid"]:
                        config.license_key = new_key
                        config.tier = "pro"
                        save_config(config)
                        return {
                            "synced": True,
                            "renewed": True,
                            "license_key": new_key,
                            "expires_at": new_ver.get("expires_at"),
                        }

                if data.get("status") == "canceled":
                    return {"synced": True, "renewed": False, "status": "canceled"}

                save_config(config)
                return {
                    "synced": True,
                    "renewed": False,
                    "expires_at": local_ver.get("expires_at"),
                }
    except Exception as e:
        return {"synced": False, "offline": True, "error": str(e)}

    return {"synced": True, "renewed": False}

