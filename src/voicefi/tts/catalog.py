"""
Voice catalog and curated agent personas for VoiceFi.
Supports Edge Neural TTS, macOS system voices, and multi-agent persona allocation.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import subprocess


@dataclass
class VoicePersona:
    id: str
    name: str
    provider: str
    gender: str
    locale: str
    style: str
    sample_text: str
    recommended_role: str = "general"


CURATED_PERSONAS: List[VoicePersona] = [
    VoicePersona(
        id="en-US-AndrewNeural",
        name="Andrew",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Warm, articulate, natural conversational",
        sample_text="Hey! I'm Andrew. My natural, articulate tone is great for pair programming and code reviews.",
        recommended_role="Antigravity / Primary Agent",
    ),
    VoicePersona(
        id="en-US-ChristopherNeural",
        name="Christopher",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Deep, grounded, authoritative",
        sample_text="Hey! I'm Christopher. My calm, low-latency neural tone is great for deep focus and long coding sessions.",
        recommended_role="Antigravity / Main Planner",
    ),
    VoicePersona(
        id="en-US-AriaNeural",
        name="Aria",
        provider="edge_tts",
        gender="Female",
        locale="en-US",
        style="Crisp, energetic, highly expressive",
        sample_text="Hello! I'm Aria. I'm quick and expressive, perfect for test announcements, git actions, and build alerts.",
        recommended_role="Debugger / QA Tester",
    ),
    VoicePersona(
        id="en-GB-SoniaNeural",
        name="Sonia",
        provider="edge_tts",
        gender="Female",
        locale="en-GB",
        style="Clear, measured British accent, analytical",
        sample_text="Greetings. I am Sonia. My clear, analytical delivery is well suited for code audits and architecture reviews.",
        recommended_role="Researcher / Codebase Analyst",
    ),
    VoicePersona(
        id="en-US-GuyNeural",
        name="Guy",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Warm, natural, conversational",
        sample_text="Hey there! I'm Guy. I've got a casual, conversational delivery that feels like pair programming with a friend.",
        recommended_role="Claude Code / Interactive Agent",
    ),
    VoicePersona(
        id="en-AU-WilliamNeural",
        name="William",
        provider="edge_tts",
        gender="Male",
        locale="en-AU",
        style="Distinct Australian accent, polished",
        sample_text="G'day! I'm William. I bring a distinct, polished voice to keep multi-agent updates clearly distinguishable.",
        recommended_role="Architect / DevOps",
    ),
    VoicePersona(
        id="en-US-JennyNeural",
        name="Jenny",
        provider="edge_tts",
        gender="Female",
        locale="en-US",
        style="Friendly, professional, articulate",
        sample_text="Hi! I'm Jenny. Professional and articulate, ready to guide you through project deployments.",
        recommended_role="Cursor / Composer",
    ),
    VoicePersona(
        id="Samantha",
        name="Samantha",
        provider="mac_say",
        gender="Female",
        locale="en-US",
        style="Classic macOS native, instant zero-latency",
        sample_text="Hello. I am Samantha, the classic offline macOS system voice.",
        recommended_role="Offline Fallback / Native Say",
    ),
    VoicePersona(
        id="Alex",
        name="Alex",
        provider="mac_say",
        gender="Male",
        locale="en-US",
        style="Classic macOS natural breathing engine",
        sample_text="Alex here. Running natively and offline on Apple Silicon.",
        recommended_role="Offline Fallback / Native Say",
    ),
]


def get_curated_personas(provider: Optional[str] = None) -> List[VoicePersona]:
    """Return curated personas, optionally filtered by provider."""
    if not provider:
        return CURATED_PERSONAS
    p = provider.lower()
    return [cp for cp in CURATED_PERSONAS if cp.provider.lower() == p]


def find_persona(name_or_id: str) -> Optional[VoicePersona]:
    """Find a curated or custom cloned persona by name or exact ID (case-insensitive)."""
    target = name_or_id.lower().strip()
    for cp in CURATED_PERSONAS:
        if cp.id.lower() == target or cp.name.lower() == target:
            return cp

    # Check custom cloned voices
    try:
        from voicefi.tts.cloning import VoiceCloneManager
        cloned = VoiceCloneManager().get_cloned_voice(target)
        if cloned:
            v_style = cloned.acoustic_metrics.get("vocal_range") if cloned.acoustic_metrics else "Custom Cloned Voice"
            desc = f"Custom Clone ({v_style})" if v_style else "Custom Cloned Voice"
            resolved_id = cloned.id if cloned.provider == "elevenlabs" else (cloned.calibrated_voice or cloned.id)
            return VoicePersona(
                id=resolved_id,
                name=cloned.name,
                provider=cloned.provider,
                gender="Custom",
                locale="en-US",
                style=cloned.description or desc,
                sample_text=f"Hey there! This is {cloned.name}, speaking with my custom cloned voice.",
                recommended_role="Personal Voice Clone",
            )
    except Exception:
        pass

    return None


def list_system_mac_voices() -> List[Dict[str, str]]:
    """Query macOS `say -v ?` for all installed system voices."""
    voices = []
    try:
        output = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.DEVNULL)
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            voice_name = parts[0]
            lang = parts[1] if len(parts) > 1 else ""
            desc = " ".join(parts[2:]) if len(parts) > 2 else ""
            voices.append({
                "id": voice_name,
                "name": voice_name,
                "provider": "mac_say",
                "locale": lang,
                "description": desc,
            })
    except Exception:
        for v in ["Samantha", "Alex", "Victoria", "Daniel", "Fred"]:
            voices.append({
                "id": v,
                "name": v,
                "provider": "mac_say",
                "locale": "en_US",
                "description": "macOS System Voice",
            })
    return voices


def list_all_available_voices(provider: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return a unified catalog of voices across Custom Clones, Edge Neural, and macOS system."""
    catalog = []
    p = provider.lower() if provider else None

    # 1. Custom cloned voices first
    try:
        from voicefi.tts.cloning import VoiceCloneManager
        clones = VoiceCloneManager().list_cloned_voices()
        for cv in clones:
            if not p or cv.provider.lower() == p or p in ("cloned", "custom"):
                catalog.append({
                    "id": cv.id,
                    "name": cv.name,
                    "provider": cv.provider,
                    "gender": "Custom",
                    "locale": "en-US",
                    "style": cv.description or f"Custom Cloned Voice ({cv.acoustic_metrics.get('vocal_range', 'Trained')})",
                    "sample_text": f"Hey there! This is {cv.name}, speaking with my custom cloned voice.",
                    "recommended_role": "Personal Voice Clone",
                    "curated": False,
                    "cloned": True,
                    "metrics": cv.acoustic_metrics,
                    "assigned_agents": cv.assigned_agents,
                })
    except Exception:
        pass

    # 2. Curated personas next
    for cp in CURATED_PERSONAS:
        if not p or cp.provider.lower() == p:
            catalog.append({
                "id": cp.id,
                "name": cp.name,
                "provider": cp.provider,
                "gender": cp.gender,
                "locale": cp.locale,
                "style": cp.style,
                "sample_text": cp.sample_text,
                "recommended_role": cp.recommended_role,
                "curated": True,
                "cloned": False,
            })

    # 3. System voices if requested or general
    if not p or p == "mac_say":
        sys_voices = list_system_mac_voices()
        curated_ids = {cp.id.lower() for cp in CURATED_PERSONAS}
        for sv in sys_voices:
            if sv["id"].lower() not in curated_ids:
                catalog.append({
                    "id": sv["id"],
                    "name": sv["name"],
                    "provider": "mac_say",
                    "gender": "Unknown",
                    "locale": sv.get("locale", "en_US"),
                    "style": sv.get("description", "macOS voice"),
                    "sample_text": f"This is the macOS system voice {sv['name']}.",
                    "recommended_role": "General",
                    "curated": False,
                    "cloned": False,
                })

    return catalog

