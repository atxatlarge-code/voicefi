"""
Secret redaction for text leaving VoiceFi.

Notes, transcripts, and vault snippets routinely contain live credentials —
users paste API keys into their own documents and forget. Any feature that
reads that text and then speaks it aloud, returns it to a caller, or ships it
to a cloud LLM is a credential exfiltration path.

:func:`redact_secrets` is the choke point. Apply it where text leaves its
origin, not where it is consumed, so a new consumer cannot forget to call it.

Design bias: **false positives are cheap, false negatives are not.** Masking a
harmless hex string costs the user a slightly worse answer. Missing a live
Stripe key ships it to a third party.
"""

import re
from typing import List, Pattern, Tuple

REDACTION_PLACEHOLDER = "[redacted]"

# Vendor-prefixed credentials. These prefixes are unambiguous — matching one is
# effectively proof the string is a secret, so they are matched greedily.
_PREFIXED_SECRETS: Tuple[str, ...] = (
    r"sk-[A-Za-z0-9_\-]{16,}",                 # OpenAI / Anthropic style
    r"sk_(?:live|test)_[A-Za-z0-9]{8,}",       # Stripe secret
    r"pk_(?:live|test)_[A-Za-z0-9]{8,}",       # Stripe publishable
    r"rk_(?:live|test)_[A-Za-z0-9]{8,}",       # Stripe restricted
    r"whsec_[A-Za-z0-9+/=]{8,}",               # Stripe webhook signing
    r"re_[A-Za-z0-9_\-]{16,}",                 # Resend
    r"polar_[A-Za-z0-9_\-]{16,}",              # Polar
    r"ghp_[A-Za-z0-9]{20,}",                   # GitHub PAT (classic)
    r"gh[osu]_[A-Za-z0-9]{20,}",               # GitHub OAuth / server / user
    r"github_pat_[A-Za-z0-9_]{20,}",           # GitHub PAT (fine-grained)
    r"glpat-[A-Za-z0-9_\-]{16,}",              # GitLab
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",          # Slack
    r"AKIA[0-9A-Z]{16}",                       # AWS access key
    r"ASIA[0-9A-Z]{16}",                       # AWS temporary key
    r"AIza[0-9A-Za-z_\-]{35}",                 # Google API key
    r"ya29\.[0-9A-Za-z_\-]{20,}",              # Google OAuth token
    r"dop_v1_[a-f0-9]{40,}",                   # DigitalOcean
    r"shpat_[a-fA-F0-9]{32}",                  # Shopify
    r"sq0[a-z]{3}-[0-9A-Za-z_\-]{20,}",        # Square
    r"npm_[A-Za-z0-9]{30,}",                   # npm
    r"pypi-[A-Za-z0-9_\-]{32,}",               # PyPI
    r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWT
)

# Words that mark the *value* beside them as sensitive, however it is shaped.
_SECRET_KEYWORD = (
    r"(?:api[_\-\s]?key|secret|token|password|passwd|pwd|credential|"
    r"auth|bearer|private[_\-\s]?key|access[_\-\s]?key|client[_\-\s]?secret|"
    r"signing[_\-\s]?secret|webhook[_\-\s]?secret|passphrase|session[_\-\s]?id)"
)

_COMPILED: List[Pattern[str]] = [
    # 1. PEM private key blocks — mask the whole block, headers included.
    re.compile(
        r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----",
        re.DOTALL | re.IGNORECASE,
    ),
    # 2. Vendor-prefixed credentials.
    re.compile("|".join(_PREFIXED_SECRETS)),
    # 3. KEY=value / KEY: value where the key name is sensitive.
    #    The value is masked; the key name survives so the text still reads.
    re.compile(
        rf"(?i)\b((?:[A-Za-z0-9_\-]*{_SECRET_KEYWORD}[A-Za-z0-9_\-]*)\s*[:=]\s*)"
        r"(\"|')?([^\s\"',;]{8,})(\2)?",
    ),
    # 4. Authorization headers.
    re.compile(r"(?i)\b(authorization\s*:\s*)(bearer\s+|basic\s+)?[A-Za-z0-9._\-+/=]{12,}"),
]

# 5. Long high-entropy strings with no other explanation. Deliberately
#    conservative: 32+ chars mixing case and digits, or 40+ hex.
_HIGH_ENTROPY = re.compile(
    r"\b(?=[A-Za-z0-9+/_\-=]{32,}\b)"
    r"(?=[^\s]*[a-z])(?=[^\s]*[A-Z])(?=[^\s]*[0-9])"
    r"[A-Za-z0-9+/_\-=]{32,}\b"
)
_LONG_HEX = re.compile(r"\b[a-fA-F0-9]{40,}\b")


def redact_secrets(text: str, placeholder: str = REDACTION_PLACEHOLDER) -> str:
    """
    Mask credential-shaped substrings in ``text``.

    Returns the text with secrets replaced by ``placeholder``. Surrounding
    prose is preserved so the result still reads naturally aloud.
    """
    if not text:
        return text

    result = text

    # PEM blocks and prefixed vendor tokens: mask the entire match.
    result = _COMPILED[0].sub(placeholder, result)
    result = _COMPILED[1].sub(placeholder, result)

    # Keyword-assigned values: keep the key name, mask the value.
    result = _COMPILED[2].sub(lambda m: f"{m.group(1)}{placeholder}", result)
    result = _COMPILED[3].sub(lambda m: f"{m.group(1)}{placeholder}", result)

    # Entropy-based sweep last, so already-masked spans are not re-scanned.
    result = _HIGH_ENTROPY.sub(placeholder, result)
    result = _LONG_HEX.sub(placeholder, result)

    return result


def contains_secret(text: str) -> bool:
    """True when :func:`redact_secrets` would mask something in ``text``."""
    return bool(text) and redact_secrets(text) != text


def mask_license_key(key: str) -> str:
    """Mask a VoiceFi license key for UI display (e.g. VF1-PRO-••••••••••••••••)."""
    if not key:
        return ""
    key = key.strip()
    if key.startswith("VF1-"):
        parts = key.split("-")
        if len(parts) >= 3:
            prefix = "-".join(parts[:2])
            return f"{prefix}-" + "•" * 24
    return "•" * min(len(key), 28)

