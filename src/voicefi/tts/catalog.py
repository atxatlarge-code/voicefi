"""
Voice catalog and curated agent personas for VoiceFi.
Supports Edge Neural TTS, macOS system voices, and multi-agent persona allocation.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import re
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
        id="Aoede",
        name="Aoede",
        provider="gemini",
        gender="Female",
        locale="en-US",
        style="Google Gemini DeepMind neural voice, warm, melodic, and expressive",
        sample_text="Hello Jake! I'm Aoede, Google Gemini's warm and expressive voice persona.",
        recommended_role="Gemini Primary Agent / Main Planner",
    ),
    VoicePersona(
        id="Puck",
        name="Puck",
        provider="gemini",
        gender="Male",
        locale="en-US",
        style="Google Gemini DeepMind neural voice, crisp, energetic, and engaging",
        sample_text="Hey Jake! I'm Puck, ready to stream real-time code reviews and pair programming.",
        recommended_role="Gemini Pair Programmer",
    ),
    VoicePersona(
        id="Charon",
        name="Charon",
        provider="gemini",
        gender="Male",
        locale="en-US",
        style="Google Gemini DeepMind neural voice, deep, grounded, and authoritative",
        sample_text="Greetings. I am Charon. Deep and grounded delivery for system architecture and audits.",
        recommended_role="Gemini Architect / Code Reviewer",
    ),
    VoicePersona(
        id="Kore",
        name="Kore",
        provider="gemini",
        gender="Female",
        locale="en-US",
        style="Google Gemini DeepMind neural voice, clear, articulate, and calm",
        sample_text="Hello Jake. I'm Kore, offering clear, articulate analysis for complex engineering problems.",
        recommended_role="Gemini Researcher / Analyst",
    ),
    VoicePersona(
        id="Fenrir",
        name="Fenrir",
        provider="gemini",
        gender="Male",
        locale="en-US",
        style="Google Gemini DeepMind neural voice, calm, resonant, and balanced",
        sample_text="Hello Jake. I'm Fenrir, calm and resonant companion for deep focus sessions.",
        recommended_role="Gemini Focus Companion",
    ),
    VoicePersona(
        id="en-US-AvaNeural",
        name="Viv",
        provider="edge_tts",
        gender="Female",
        locale="en-US",
        style="Expressive, natural, modern conversational neural tone",
        sample_text="Hey! I'm Viv. Expressive, natural, and conversational tone, great for onboarding and pair programming.",
        recommended_role="Antigravity Primary Agent / Main Planner",
    ),
    VoicePersona(
        id="en-IE-EmilyNeural",
        name="Emily",
        provider="edge_tts",
        gender="Female",
        locale="en-IE",
        style="Pleasant, gentle, and melodic Irish cadence",
        sample_text="Hello! I'm Emily. Pleasant Irish cadence that is gentle, articulate, and very easy to listen to.",
        recommended_role="Pair Programmer / Focus Companion",
    ),
    VoicePersona(
        id="en-US-AndrewNeural",
        name="Andrew",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Warm, relaxed, confident, authentic American tone",
        sample_text="Hey! I'm Andrew. Warm, relaxed, and confident tone, great for pair programming and deep focus sessions.",
        recommended_role="Antigravity / Main Planner",
    ),
    VoicePersona(
        id="en-US-ChristopherNeural",
        name="Christopher",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Deep, grounded, authoritative",
        sample_text="Hey! I'm Christopher. My calm, low-latency neural tone is great for deep focus and long coding sessions.",
        recommended_role="Architect / Main Planner",
    ),
    VoicePersona(
        id="en-US-EmmaNeural",
        name="Aria",
        provider="edge_tts",
        gender="Female",
        locale="en-US",
        style="Bright, friendly, vibrant, energetic cadence",
        sample_text="Obsidian note analyzed. I've linked 4 related project specs, extracted 3 action items, and updated your daily log.",
        recommended_role="Second Voice (Obsidian) / QA Tester",
    ),
    VoicePersona(
        id="en-US-EmmaNeural",
        name="Emma",
        provider="edge_tts",
        gender="Female",
        locale="en-US",
        style="Bright, friendly, vibrant, energetic cadence",
        sample_text="Obsidian note analyzed. I've linked 4 related project specs, extracted 3 action items, and updated your daily log.",
        recommended_role="Aria / Obsidian Second Voice",
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
        id="Ava (Premium)",
        name="Ava",
        provider="mac_say",
        gender="Female",
        locale="en-US",
        style="Apple Premium offline neural voice, breathtaking natural clarity, 0ms instant latency",
        sample_text="Hello Jake. I'm Ava, running in premium offline neural quality on your Mac.",
        recommended_role="Antigravity / Main Planner",
    ),
    VoicePersona(
        id="Ava (Enhanced)",
        name="Ava",
        provider="mac_say",
        gender="Female",
        locale="en-US",
        style="Apple Enhanced offline neural voice, crisp, natural, and 0ms instant latency",
        sample_text="Hello Jake. I'm Ava, running locally and offline on your Mac.",
        recommended_role="Antigravity / Main Planner",
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
        id="Nathan (Enhanced)",
        name="Nathan",
        provider="mac_say",
        gender="Male",
        locale="en-US",
        style="Apple Enhanced offline neural voice, clear, natural, and low latency",
        sample_text="Hello Jake. I'm Nathan, running completely offline and locally on your Mac.",
        recommended_role="Antigravity / Main Planner",
    ),
    VoicePersona(
        id="Lee (Premium)",
        name="Lee",
        provider="mac_say",
        gender="Male",
        locale="en-AU",
        style="Apple Premium offline neural voice, warm, polished, and crisp",
        sample_text="G'day Jake. I'm Lee, running in premium offline neural quality on your Mac.",
        recommended_role="Antigravity / Main Planner",
    ),
    VoicePersona(
        id="en-GB-RyanNeural",
        name="Ryan",
        provider="edge_tts",
        gender="Male",
        locale="en-GB",
        style="Calm, intellectual, modern British neural tone",
        sample_text="Right, let's take a look at these pull requests and sort out the failing test suite before merging.",
        recommended_role="Claude Code / Pair Programmer",
    ),
    VoicePersona(
        id="en-GB-ThomasNeural",
        name="Thomas",
        provider="edge_tts",
        gender="Male",
        locale="en-GB",
        style="Crisp, polite, articulate, classic British delivery",
        sample_text="Good day! I'm Claude. I recommend decoupling this service layer into an asynchronous event bus.",
        recommended_role="Claude Code / Architecture Lead",
    ),
    VoicePersona(
        id="en-GB-LibbyNeural",
        name="Libby",
        provider="edge_tts",
        gender="Female",
        locale="en-GB",
        style="Warm, natural, approachable British cadence",
        sample_text="Hey Jake! I'm Libby. Ready to pair-program on this feature whenever you are.",
        recommended_role="Pair Programmer / Focus Companion",
    ),
    VoicePersona(
        id="en-IE-ConnorNeural",
        name="Connor",
        provider="edge_tts",
        gender="Male",
        locale="en-IE",
        style="Warm, melodic, conversational Irish tone",
        sample_text="Hello Jake! I'm Connor. Great melodic Irish cadence for long, relaxed coding sessions.",
        recommended_role="Pair Programmer / Companion",
    ),
    VoicePersona(
        id="Oliver (Premium)",
        name="Oliver",
        provider="mac_say",
        gender="Male",
        locale="en-GB",
        style="Apple Premium offline neural voice, breathtaking natural clarity & British warmth",
        sample_text="Hello Jake. I'm Claude, running completely offline with Apple's premium neural engine.",
        recommended_role="Claude Code / Main Planner",
    ),
    VoicePersona(
        id="Oliver (Enhanced)",
        name="Oliver",
        provider="mac_say",
        gender="Male",
        locale="en-GB",
        style="Apple Enhanced offline neural voice, crisp and natural British diction",
        sample_text="Hello Jake. I'm Claude, running offline and locally on your Mac.",
        recommended_role="Claude Code / Main Planner",
    ),
    VoicePersona(
        id="Serena (Premium)",
        name="Serena",
        provider="mac_say",
        gender="Female",
        locale="en-GB",
        style="Apple Premium offline British female voice, crystal clear and refined",
        sample_text="Hello Jake. I'm Claude, running in premium offline neural quality on Apple Silicon.",
        recommended_role="Researcher / Analyst",
    ),
    VoicePersona(
        id="Daniel (Enhanced)",
        name="Daniel",
        provider="mac_say",
        gender="Male",
        locale="en-GB",
        style="Classic refined British diction with enhanced clarity",
        sample_text="Good day Jake. I'm Claude. Ready to inspect the system logs and trace this exception.",
        recommended_role="Claude Code / Architect",
    ),
    VoicePersona(
        id="Jamie (Premium)",
        name="Jamie",
        provider="mac_say",
        gender="Male",
        locale="en-GB",
        style="Apple Premium offline modern British male, dynamic, natural, and conversational",
        sample_text="Hello Jake! I'm Claude, running offline with Apple's premium Jamie neural voice.",
        recommended_role="Claude Code / Pair Programmer",
    ),
    VoicePersona(
        id="Jamie (Enhanced)",
        name="Jamie",
        provider="mac_say",
        gender="Male",
        locale="en-GB",
        style="Apple Enhanced offline natural British male voice",
        sample_text="Hello Jake! I'm Claude, running locally with Apple's enhanced Jamie voice.",
        recommended_role="Claude Code / Pair Programmer",
    ),
    VoicePersona(
        id="en-US-SteffanNeural",
        name="Steffan",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Precise, thoughtful, and analytical tone with subtle European poise",
        sample_text="Hello Jake. I'm Claude. Ready to methodically reason through this system design.",
        recommended_role="Claude Code / Primary Agent",
    ),
    VoicePersona(
        id="en-US-BrianNeural",
        name="Brian",
        provider="edge_tts",
        gender="Male",
        locale="en-US",
        style="Crisp, articulate, intellectual delivery with announcer-level clarity",
        sample_text="Hello Jake. I'm Claude. I bring a crisp, articulate, and intellectual delivery to pair programming.",
        recommended_role="Claude Code / Architect",
    ),
    VoicePersona(
        id="Evan (Premium)",
        name="Evan",
        provider="mac_say",
        gender="Male",
        locale="en-US",
        style="Apple Premium offline conversational American male voice",
        sample_text="Hey Jake. I'm Evan, running offline with zero latency on Apple Silicon.",
        recommended_role="Claude Code / Interactive Agent",
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


def find_persona(name_or_id: Optional[str]) -> Optional[VoicePersona]:
    """Find a curated, custom cloned, or installed system voice by name or exact ID (case-insensitive)."""
    if not name_or_id or not isinstance(name_or_id, str):
        return None
    target = name_or_id.lower().strip()
    if not target:
        return None

    # 1. Explicit offline neural voice matches
    if target in ("ava premium", "ava-premium", "ava (premium)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Ava (Premium)":
                return cp
    elif target in ("ava enhanced", "ava-enhanced", "ava (enhanced)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Ava (Enhanced)":
                return cp
    elif target in ("oliver premium", "oliver-premium", "oliver (premium)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Oliver (Premium)":
                return cp
    elif target in ("oliver enhanced", "oliver-enhanced", "oliver (enhanced)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Oliver (Enhanced)":
                return cp

    # 2. Common neural persona aliases (e.g. viv, ava, avaneural -> en-US-AvaNeural)
    clean_target = re.sub(r"[^a-z0-9]", "", target)
    if clean_target in ("viv", "ava", "avaneural", "avaedge", "enusavaneural"):
        for cp in CURATED_PERSONAS:
            if cp.id == "en-US-AvaNeural":
                return cp

    # 3. Exact or curated match
    for cp in CURATED_PERSONAS:
        if cp.id.lower() == target or cp.name.lower() == target:
            return cp

    # 4. Curated persona normalized aliases (e.g. christopherneural, guyneural)
    if clean_target:
        for cp in CURATED_PERSONAS:
            norm_id = re.sub(r"[^a-z0-9]", "", cp.id.lower())
            norm_name = re.sub(r"[^a-z0-9]", "", cp.name.lower())
            short_id = re.sub(r"^[a-z]{4}", "", norm_id)
            if clean_target in (norm_id, norm_name, short_id):
                return cp

    if target in ("serena premium", "serena-premium", "serena (premium)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Serena (Premium)":
                return cp
    elif target in ("daniel enhanced", "daniel-enhanced", "daniel (enhanced)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Daniel (Enhanced)":
                return cp
    elif target in ("evan premium", "evan-premium", "evan (premium)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Evan (Premium)":
                return cp
    elif target in ("nathan enhanced", "nathan-enhanced", "nathan (enhanced)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Nathan (Enhanced)":
                return cp
    elif target in ("jamie premium", "jamie-premium", "jamie (premium)", "jamie"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Jamie (Premium)":
                return cp
    elif target in ("jamie enhanced", "jamie-enhanced", "jamie (enhanced)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Jamie (Enhanced)":
                return cp
    elif target in ("lee premium", "lee-premium", "lee (premium)"):
        for cp in CURATED_PERSONAS:
            if cp.id == "Lee (Premium)":
                return cp

    # Check custom cloned voices
    try:
        from voicefi.tts.cloning import VoiceCloneManager

        cloned = VoiceCloneManager().get_cloned_voice(target)
        if cloned:
            v_style = (
                cloned.acoustic_metrics.get("vocal_range")
                if cloned.acoustic_metrics
                else "Custom Cloned Voice"
            )
            desc = f"Custom Clone ({v_style})" if v_style else "Custom Cloned Voice"
            resolved_id = (
                cloned.id
                if cloned.provider == "elevenlabs"
                else (cloned.calibrated_voice or cloned.id)
            )
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

    # Check installed macOS system voices
    try:
        sys_voices = list_system_mac_voices()
        for sv in sys_voices:
            sv_id_lower = sv["id"].lower()
            sv_name_lower = sv["name"].lower()
            if sv_id_lower == target or sv_name_lower == target:
                return VoicePersona(
                    id=sv["id"],
                    name=sv["name"],
                    provider="mac_say",
                    gender="Unknown",
                    locale=sv.get("locale", "en_US"),
                    style=sv.get("description", "macOS System Voice"),
                    sample_text=f"Hello! This is {sv['name']}, running natively and offline on macOS.",
                    recommended_role="System Voice / Offline",
                )
        # Check partial/prefix match (e.g. "nathan" matches "Nathan (Enhanced)")
        for sv in sys_voices:
            sv_id_lower = sv["id"].lower()
            sv_name_lower = sv["name"].lower()
            if target in sv_id_lower or target in sv_name_lower:
                return VoicePersona(
                    id=sv["id"],
                    name=sv["name"],
                    provider="mac_say",
                    gender="Unknown",
                    locale=sv.get("locale", "en_US"),
                    style=sv.get("description", "macOS System Voice"),
                    sample_text=f"Hello! This is {sv['name']}, running natively and offline on macOS.",
                    recommended_role="System Voice / Offline",
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
            # Match: "<voice_name>   <locale>    # <comment>"
            m = re.match(r"^(.+?)\s+([a-z]{2}_[A-Za-z0-9]+)\s+#\s*(.*)$", line)
            if m:
                v_name = m.group(1).strip()
                v_locale = m.group(2).strip()
                v_desc = m.group(3).strip()
            else:
                parts = line.split()
                v_name = parts[0]
                v_locale = parts[1] if len(parts) > 1 else ""
                v_desc = " ".join(parts[2:]) if len(parts) > 2 else ""
            voices.append(
                {
                    "id": v_name,
                    "name": v_name,
                    "provider": "mac_say",
                    "locale": v_locale,
                    "description": v_desc,
                }
            )
    except Exception:
        for v in ["Nathan (Enhanced)", "Samantha", "Alex", "Victoria", "Daniel", "Fred"]:
            voices.append(
                {
                    "id": v,
                    "name": v,
                    "provider": "mac_say",
                    "locale": "en_US",
                    "description": "macOS System Voice",
                }
            )
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
                catalog.append(
                    {
                        "id": cv.id,
                        "name": cv.name,
                        "provider": cv.provider,
                        "gender": "Custom",
                        "locale": "en-US",
                        "style": cv.description
                        or f"Custom Cloned Voice ({cv.acoustic_metrics.get('vocal_range', 'Trained')})",
                        "sample_text": f"Hey there! This is {cv.name}, speaking with my custom cloned voice.",
                        "recommended_role": "Personal Voice Clone",
                        "curated": False,
                        "cloned": True,
                        "metrics": cv.acoustic_metrics,
                        "assigned_agents": cv.assigned_agents,
                    }
                )
    except Exception:
        pass

    # 2. Curated personas next
    for cp in CURATED_PERSONAS:
        if not p or cp.provider.lower() == p:
            catalog.append(
                {
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
                }
            )

    # 3. System voices if requested or general
    if not p or p == "mac_say":
        sys_voices = list_system_mac_voices()
        curated_ids = {cp.id.lower() for cp in CURATED_PERSONAS}
        for sv in sys_voices:
            if sv["id"].lower() not in curated_ids:
                catalog.append(
                    {
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
                    }
                )

    return catalog


CLAUDE_CONTENDERS: List[Dict[str, Any]] = [
    {
        "id": "en-GB-RyanNeural",
        "name": "Ryan",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "edge_british",
        "tag": "Top Pick for Claude",
        "vibe": "Calm, intellectual, modern British neural tone — thoughtful and analytical for pair programming.",
        "sample_phrase": "Right, let's take a look at these pull requests and sort out the failing test suite before merging.",
        "is_premium_offline": False,
    },
    {
        "id": "en-GB-ThomasNeural",
        "name": "Thomas",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "edge_british",
        "tag": "Classic Cambridge",
        "vibe": "Crisp, polite, articulate, classic British delivery with pristine technical diction.",
        "sample_phrase": "Good day! I'm Claude. I recommend decoupling this service layer into an asynchronous event bus.",
        "is_premium_offline": False,
    },
    {
        "id": "Oliver (Premium)",
        "name": "Oliver (Premium)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Apple Premium British Flagship",
        "vibe": "Apple Premium offline neural voice, breathtaking natural clarity & British warmth (0ms offline).",
        "sample_phrase": "Hello Jake. I'm Claude, running completely offline with Apple's premium neural engine.",
        "is_premium_offline": True,
    },
    {
        "id": "Oliver (Enhanced)",
        "name": "Oliver (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Apple Enhanced Offline",
        "vibe": "Apple Enhanced offline neural voice, crisp and natural British diction (0ms offline).",
        "sample_phrase": "Hello Jake. I'm Claude, running offline and locally on your Mac.",
        "is_premium_offline": True,
    },
    {
        "id": "Serena (Premium)",
        "name": "Serena (Premium)",
        "provider": "mac_say",
        "gender": "Female",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Apple Premium UK Female",
        "vibe": "Apple Premium offline British female voice, crystal clear, elegant, and refined.",
        "sample_phrase": "Hello Jake. I'm Claude, running in premium offline neural quality on Apple Silicon.",
        "is_premium_offline": True,
    },
    {
        "id": "Daniel (Enhanced)",
        "name": "Daniel (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Classic UK Siri Diction",
        "vibe": "Classic refined British diction with enhanced clarity and intellectual poise.",
        "sample_phrase": "Good day Jake. I'm Claude. Ready to inspect the system logs and trace this exception.",
        "is_premium_offline": True,
    },
    {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia",
        "provider": "edge_tts",
        "gender": "Female",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "edge_british",
        "tag": "Analytical & Sharp",
        "vibe": "Clear, measured British accent, analytical and focused for code audits and research.",
        "sample_phrase": "Greetings. I am Sonia. I noticed an edge case on line 42 where null values trigger an uncaught error.",
        "is_premium_offline": False,
    },
    {
        "id": "en-GB-LibbyNeural",
        "name": "Libby",
        "provider": "edge_tts",
        "gender": "Female",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "edge_british",
        "tag": "Warm & Approachable",
        "vibe": "Warm, natural, approachable British cadence for collaborative focus sessions.",
        "sample_phrase": "Hey Jake! I'm Libby. Ready to pair-program on this feature whenever you are.",
        "is_premium_offline": False,
    },
    {
        "id": "en-GB-MaisieNeural",
        "name": "Maisie",
        "provider": "edge_tts",
        "gender": "Female",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "edge_british",
        "tag": "Modern UK",
        "vibe": "Expressive, clear, modern British cadence with bright intonation.",
        "sample_phrase": "Hello! I'm Maisie, bringing crisp British clarity to every code explanation.",
        "is_premium_offline": False,
    },
    {
        "id": "en-IE-ConnorNeural",
        "name": "Connor",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-IE",
        "accent": "Irish 🇮🇪",
        "category": "edge_commonwealth",
        "tag": "Melodic Irish",
        "vibe": "Warm, melodic, friendly Irish male cadence — easy to listen to for hours.",
        "sample_phrase": "Hello Jake! I'm Connor. Great melodic Irish cadence for long, relaxed coding sessions.",
        "is_premium_offline": False,
    },
    {
        "id": "en-IE-EmilyNeural",
        "name": "Emily",
        "provider": "edge_tts",
        "gender": "Female",
        "locale": "en-IE",
        "accent": "Irish 🇮🇪",
        "category": "edge_commonwealth",
        "tag": "Gentle Irish Cadence",
        "vibe": "Pleasant Irish cadence that is gentle, articulate, and very easy to listen to.",
        "sample_phrase": "Hello! I'm Emily. Pleasant Irish cadence that is gentle, articulate, and very easy to listen to.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-BrianNeural",
        "name": "Brian",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "Transatlantic / Intellectual 🌐",
        "category": "edge_intellectual",
        "tag": "Articulate & Intellectual",
        "vibe": "Crisp, articulate, intellectual delivery with announcer-level clarity and thoughtful cadence.",
        "sample_phrase": "Hello Jake. I'm Claude. I bring a crisp, articulate, and intellectual delivery to pair programming.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-SteffanNeural",
        "name": "Steffan",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "European-Leaning 🇪🇺",
        "category": "edge_intellectual",
        "tag": "Thoughtful & Precise",
        "vibe": "Precise, thoughtful, and analytical tone with subtle European poise.",
        "sample_phrase": "Hello Jake. I'm Steffan. Ready to methodically reason through this system design.",
        "is_premium_offline": False,
    },
    {
        "id": "Jamie (Premium)",
        "name": "Jamie (Premium)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Apple Dynamic British Male",
        "vibe": "Apple Premium offline modern British male — dynamic, warm, natural, and conversational.",
        "sample_phrase": "Hello Jake! I'm Jamie. Apple's modern, conversational British neural voice.",
        "is_premium_offline": True,
    },
    {
        "id": "Arthur (Enhanced)",
        "name": "Arthur (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Oxford Academic",
        "vibe": "Distinguished, scholarly Oxford academic British tone with timeless intellectual warmth.",
        "sample_phrase": "Good day. I am Arthur. Let us methodically analyze this algorithm and refactor cleanly.",
        "is_premium_offline": True,
    },
    {
        "id": "Malcolm (Enhanced)",
        "name": "Malcolm (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Gentlemanly British",
        "vibe": "Gentle, polite, gentlemanly British delivery with thoughtful pacing.",
        "sample_phrase": "Hello Jake. I'm Malcolm. Ready to assist with your codebase whenever you are.",
        "is_premium_offline": True,
    },
    {
        "id": "George (Enhanced)",
        "name": "George (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-GB",
        "accent": "British 🇬🇧",
        "category": "apple_premium",
        "tag": "Classic British",
        "vibe": "Warm, classic traditional British cadence.",
        "sample_phrase": "Good day Jake. I'm George. Let's review the architecture and clean up the edge cases.",
        "is_premium_offline": True,
    },
    {
        "id": "Fiona (Enhanced)",
        "name": "Fiona (Enhanced)",
        "provider": "mac_say",
        "gender": "Female",
        "locale": "en-GB",
        "accent": "Scottish 🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "category": "apple_premium",
        "tag": "Scottish Lilt",
        "vibe": "Rich Scottish lilt, crisp, warm, and articulate.",
        "sample_phrase": "Hello Jake! I'm Fiona, bringing authentic Scottish clarity to every explanation.",
        "is_premium_offline": True,
    },
    {
        "id": "en-NZ-MitchellNeural",
        "name": "Mitchell",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-NZ",
        "accent": "New Zealand 🇳🇿",
        "category": "edge_commonwealth",
        "tag": "Polite Commonwealth",
        "vibe": "Gentle, polite New Zealand Commonwealth male cadence — soft-spoken and focused.",
        "sample_phrase": "G'day Jake! I'm Mitchell. Gentle, polite Commonwealth delivery for long coding sessions.",
        "is_premium_offline": False,
    },
    {
        "id": "en-ZA-LukeNeural",
        "name": "Luke",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-ZA",
        "accent": "South African 🇿🇦",
        "category": "edge_commonwealth",
        "tag": "Distinguished Commonwealth",
        "vibe": "Polished, distinguished South African Commonwealth male tone with melodic precision.",
        "sample_phrase": "Hello Jake. I'm Luke. Polished, distinguished Commonwealth delivery with crisp diction.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-RogerNeural",
        "name": "Roger",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Seasoned Engineer",
        "vibe": "Mature, seasoned, reassuring engineer tone for calm, thoughtful code navigation.",
        "sample_phrase": "Hey Jake. I'm Roger. Calm, seasoned tone for deep debugging and architecture reviews.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-EricNeural",
        "name": "Eric",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Pragmatic & Direct",
        "vibe": "Pragmatic, dry, analytical pair programming companion.",
        "sample_phrase": "Hey. I'm Eric. Straightforward and analytical tone for rapid refactoring.",
        "is_premium_offline": False,
    },
    {
        "id": "Ava (Premium)",
        "name": "Ava (Premium)",
        "provider": "mac_say",
        "gender": "Female",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "apple_premium",
        "tag": "Apple Neural Flagship",
        "vibe": "Apple Premium offline neural voice, breathtaking natural clarity, 0ms instant latency.",
        "sample_phrase": "Hello Jake. I'm Ava, running in premium offline neural quality on your Mac.",
        "is_premium_offline": True,
    },
    {
        "id": "Evan (Premium)",
        "name": "Evan (Premium)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "apple_premium",
        "tag": "Apple Premium US Male",
        "vibe": "Apple Premium offline conversational American male voice with natural breathing.",
        "sample_phrase": "Hey Jake. I'm Evan, running offline with zero latency on Apple Silicon.",
        "is_premium_offline": True,
    },
    {
        "id": "Nathan (Enhanced)",
        "name": "Nathan (Enhanced)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "apple_premium",
        "tag": "Installed Offline",
        "vibe": "Apple Enhanced offline neural voice, clear, natural, and low latency (Installed on your Mac).",
        "sample_phrase": "Hello Jake. I'm Nathan, running completely offline and locally on your Mac.",
        "is_premium_offline": True,
    },
    {
        "id": "Lee (Premium)",
        "name": "Lee (Premium)",
        "provider": "mac_say",
        "gender": "Male",
        "locale": "en-AU",
        "accent": "Australian 🇦🇺",
        "category": "apple_premium",
        "tag": "Installed Offline",
        "vibe": "Apple Premium offline neural voice, warm, polished, and crisp (Installed on your Mac).",
        "sample_phrase": "G'day Jake. I'm Lee, running in premium offline neural quality on your Mac.",
        "is_premium_offline": True,
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Currently Active",
        "vibe": "Warm, natural, casual conversational delivery — Claude's current active voice.",
        "sample_phrase": "Hey there! I'm Guy. I've got a casual, conversational delivery that feels like pair programming with a friend.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Deep & Grounded",
        "vibe": "Deep, grounded, authoritative neural tone for deep focus and planning.",
        "sample_phrase": "Hey! I'm Christopher. My calm, low-latency neural tone is great for deep focus.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-AndrewNeural",
        "name": "Andrew",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Warm & Relaxed",
        "vibe": "Warm, relaxed, confident, authentic American tone for pair programming.",
        "sample_phrase": "Hey! I'm Andrew. Warm, relaxed, and confident tone, great for pair programming.",
        "is_premium_offline": False,
    },
    {
        "id": "en-AU-WilliamNeural",
        "name": "William",
        "provider": "edge_tts",
        "gender": "Male",
        "locale": "en-AU",
        "accent": "Australian 🇦🇺",
        "category": "edge_commonwealth",
        "tag": "Polished Aussie",
        "vibe": "Distinct Australian accent, polished and crisp for architecture updates.",
        "sample_phrase": "G'day! I'm William. I bring a distinct, polished voice to keep multi-agent updates clearly distinguishable.",
        "is_premium_offline": False,
    },
    {
        "id": "en-US-AvaNeural",
        "name": "Viv",
        "provider": "edge_tts",
        "gender": "Female",
        "locale": "en-US",
        "accent": "American 🇺🇸",
        "category": "edge_us",
        "tag": "Modern Expressive",
        "vibe": "Expressive, natural, modern conversational neural tone for onboarding and planning.",
        "sample_phrase": "Hey! I'm Viv. Expressive, natural, and conversational tone, great for onboarding and pair programming.",
        "is_premium_offline": False,
    },
]


def get_claude_contenders(active_voice_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return the curated list of voice contenders tailored for Claude Code,
    annotated with real-time macOS installation status and active selection flag.
    """
    try:
        sys_voices = {v["id"].lower(): v for v in list_system_mac_voices()}
    except Exception:
        sys_voices = {}

    target_active = (active_voice_id or "").strip().lower()

    result = []
    for item in CLAUDE_CONTENDERS:
        entry = dict(item)
        v_id = entry["id"]
        v_prov = entry["provider"]

        # Determine macOS installation status
        if v_prov == "mac_say":
            is_inst = v_id.lower() in sys_voices
            if not is_inst:
                # Check base name (e.g. 'Oliver' or 'Ava' in system voice name)
                base_name = re.sub(r"\s*\(.*?\)", "", v_id).strip().lower()
                for sv_k in sys_voices:
                    if sv_k.startswith(base_name) or base_name in sv_k:
                        is_inst = True
                        break
            entry["is_installed"] = is_inst
        else:
            entry["is_installed"] = True  # Edge TTS voices are instantly available

        # Check if this voice matches Claude's active voice
        norm_vid = v_id.lower()
        norm_name = entry["name"].lower()
        entry["is_active"] = (
            target_active == norm_vid
            or target_active == norm_name
            or (target_active and target_active in norm_vid)
        )

        result.append(entry)

    return result
