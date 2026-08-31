#!/usr/bin/env python3
"""
VoiceFi™ Conversational Script Generator & Reel Authoring Engine.
Generates multi-agent conversational scripts where characters actively converse,
react to previous lines, calculate word-budgets, and output valid Reel Manifests.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def _load_character_profiles() -> Dict[str, Dict[str, Any]]:
    """Load character profiles from src/voicefi/characters.json with fallback."""
    json_path = Path(__file__).resolve().parent.parent / "src" / "voicefi" / "characters.json"
    profiles = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            chars = data.get("characters", {})
            for key, char in chars.items():
                name = char.get("name", key.capitalize())
                profile = {
                    "voice_id": char.get("voice_id", "en-US-AvaNeural"),
                    "tag_color": char.get("badge_color", "#3186FF"),
                    "role": f"{char.get('app', '')} • {char.get('role', '')}".strip(" • "),
                    "app": char.get("app", ""),
                    "style": char.get("style", ""),
                    "speed": char.get("speed", "-2%"),
                    "logo_type": char.get("logo_type", "voicefi"),
                }
                profiles[name] = profile
                profiles[name.lower()] = profile
                for alias in char.get("aliases", []):
                    profiles[alias] = profile
                    profiles[alias.lower()] = profile
            return profiles
        except Exception:
            pass

    # Static fallback
    return {
        "Viv": {
            "voice_id": "en-US-AvaNeural",
            "tag_color": "#3186FF",
            "role": "Google Antigravity • Main Planner",
            "speed": "-3%",
        },
        "Stefan": {
            "voice_id": "en-US-SteffanNeural",
            "tag_color": "#D97757",
            "role": "Claude Code • Architect",
            "speed": "-2%",
        },
        "Steffan": {
            "voice_id": "en-US-SteffanNeural",
            "tag_color": "#D97757",
            "role": "Claude Code • Architect",
            "speed": "-2%",
        },
        "Claude": {
            "voice_id": "en-US-SteffanNeural",
            "tag_color": "#D97757",
            "role": "Claude Code • Architect",
            "speed": "-2%",
        },
        "Christopher": {
            "voice_id": "en-US-ChristopherNeural",
            "tag_color": "#00E5FF",
            "role": "Cursor • IDE Architect",
            "speed": "-2%",
        },
        "Cursor": {
            "voice_id": "en-US-ChristopherNeural",
            "tag_color": "#00E5FF",
            "role": "Cursor • IDE Architect",
            "speed": "-2%",
        },
        "Emily": {
            "voice_id": "en-IE-EmilyNeural",
            "tag_color": "#10B981",
            "role": "OpenAI / ChatGPT • VoiceFi Host",
            "speed": "-2%",
        },
        "ChatGPT": {
            "voice_id": "en-IE-EmilyNeural",
            "tag_color": "#10B981",
            "role": "OpenAI / ChatGPT • VoiceFi Host",
            "speed": "-2%",
        },
        "OpenAI": {
            "voice_id": "en-IE-EmilyNeural",
            "tag_color": "#10B981",
            "role": "OpenAI / ChatGPT • VoiceFi Host",
            "speed": "-2%",
        },
        "Aria": {
            "voice_id": "en-US-EmmaNeural",
            "tag_color": "#8B5CF6",
            "role": "Obsidian • Second Brain",
            "speed": "0%",
        },
        "Sonia": {
            "voice_id": "en-GB-SoniaNeural",
            "tag_color": "#06B6D4",
            "role": "Code Reviewer • Security Lead",
            "speed": "0%",
        },
        "Jake": {
            "voice_id": "Native Mic Audio",
            "tag_color": "#8B5CF6",
            "role": "Human Creator • Lead Engineer",
            "speed": "Native",
        },
    }


CHARACTER_PROFILES = _load_character_profiles()


class ConversationalScriptEngine:
    """Generates back-and-forth conversational dialogue scripts for VoiceFi reels."""

    @staticmethod
    def estimate_duration(text: str, wps: float = 3.0, sfx_tag: Optional[str] = None) -> float:
        """Estimate speech duration based on word count with SFX padding."""
        # Strip brackets
        clean = " ".join([w for w in text.split() if not (w.startswith("[") and w.endswith("]"))])
        words = len(clean.split())
        dur = max(2.5, words / wps)
        if sfx_tag or "[sfx:" in text:
            dur += 1.2
        return round(dur, 2)

    @classmethod
    def generate_making_voicefi_script(cls) -> List[Dict[str, Any]]:
        """Generate the canonical multi-agent conversational script for 'Making VoiceFi'."""
        turns = [
            {
                "speaker": "Viv",
                "hook": "“Jake got so tired of silent terminals that he built VoiceFi just so we could talk back!”",
                "body": "Antigravity Main Planner • Sub-millisecond IPC",
                "is_punchline": False,
                "is_outro": False,
            },
            {
                "speaker": "Claude",
                "hook": "“And by talk back, Viv means he built a cross-agent bridge so we could roast each other's pull requests.”",
                "body": "Claude Code Architect • Direct response to Viv's provocation",
                "is_punchline": False,
                "is_outro": False,
            },
            {
                "speaker": "Christopher",
                "hook": "“Don't forget sub-150 millisecond barge-in. One word from Jake, and our audio stops instantly.”",
                "body": "Acoustic DSP Lead • Zero speaker bleed & instant turn interruption",
                "is_punchline": False,
                "is_outro": False,
            },
            {
                "speaker": "Viv",
                "hook": "“Which is great, because Claude wrote an essay on Unix sockets! But hey—we built VoiceFi using VoiceFi!”",
                "body": "🥁 Ba-dum-tss! [sfx:drum_smash]",
                "is_punchline": True,
                "is_outro": False,
            },
            {
                "speaker": "Emily",
                "hook": "“Stop typing into the void. Build with your AI team in real-time voice. VoiceFi — Free your voice.”",
                "body": "Available on macOS, Antigravity, Claude Code & MCP • voicefi.org",
                "is_punchline": False,
                "is_outro": True,
            },
        ]

        # Calculate pacing & slide formatting
        total_slides = len(turns)
        slides = []
        for idx, t in enumerate(turns):
            speaker_meta = CHARACTER_PROFILES.get(t["speaker"], {})
            dur = cls.estimate_duration(t["hook"])
            slides.append(
                {
                    "slide_idx": idx + 1,
                    "speaker": t["speaker"],
                    "tag_color": speaker_meta.get("tag_color", "#3186FF"),
                    "counter": f"{idx + 1}/{total_slides}",
                    "hook": t["hook"],
                    "body": t["body"],
                    "is_punchline": t.get("is_punchline", False),
                    "is_outro": t.get("is_outro", False),
                    "dur": dur,
                }
            )
        return slides

    @classmethod
    def generate_rap_battle_script(cls) -> List[Dict[str, Any]]:
        """Generate a dynamic conversational rap battle script."""
        turns = [
            {
                "speaker": "Viv",
                "hook": "“I'm spitting sub-millisecond execution while you're parsing tokens!”",
                "body": "Your context window's bloated and your type assertions broken!",
                "is_punchline": False,
                "is_outro": False,
            },
            {
                "speaker": "Claude",
                "hook": "“Cute assertions, Viv, but check the git blame trace: I wrote the AST compiler that powers your base.”",
                "body": "You ship fast with twenty bugs and call it rapid iteration.",
                "is_punchline": False,
                "is_outro": False,
            },
            {
                "speaker": "Viv",
                "hook": "“Enterprise migration? Honey, you're stuck in prompt queue purgatory!”",
                "body": "One click of VoiceFi barge-in, and that's the end of your story! 🥁 [sfx:drum_smash]",
                "is_punchline": True,
                "is_outro": False,
            },
            {
                "speaker": "Emily",
                "hook": "“Who won this battle? Drop your verdict below. VoiceFi — Free your voice.”",
                "body": "Two AI agents conversing in real-time. Try it at voicefi.org",
                "is_punchline": False,
                "is_outro": True,
            },
        ]
        total_slides = len(turns)
        slides = []
        for idx, t in enumerate(turns):
            speaker_meta = CHARACTER_PROFILES.get(t["speaker"], {})
            dur = cls.estimate_duration(t["hook"])
            slides.append(
                {
                    "slide_idx": idx + 1,
                    "speaker": t["speaker"],
                    "tag_color": speaker_meta.get("tag_color", "#3186FF"),
                    "counter": f"{idx + 1}/{total_slides}",
                    "hook": t["hook"],
                    "body": t["body"],
                    "is_punchline": t.get("is_punchline", False),
                    "is_outro": t.get("is_outro", False),
                    "dur": dur,
                }
            )
        return slides

    @classmethod
    def build_manifest(
        cls,
        reel_id: str,
        title: str,
        slug: str,
        category: str,
        slides: List[Dict[str, Any]],
        preset: str = "witty_comedy",
    ) -> Dict[str, Any]:
        """Build full JSON manifest conforming to VoiceFi reel schema."""
        total_duration = sum(s["dur"] for s in slides)
        return {
            "$schema": "https://voicefi.org/schemas/reel-manifest.v1.json",
            "id": reel_id,
            "title": title,
            "slug": slug,
            "created_at": "2026-08-30",
            "category": category,
            "hide_footer": False,
            "tags": ["voicefi", "antigravity", "claude", "conversational", category],
            "audio": {
                "source_script": f"marketing/social/generate_{slug}_audio.py",
                "master_mp3": f"assets/{slug}_dialogue.mp3",
                "duration_seconds": round(total_duration, 2),
            },
            "typography": {
                "preset": preset,
                "viv_font": "'Bricolage Grotesque', sans-serif",
                "claude_font": "'Fraunces', serif",
                "emily_font": "'Syncopate', sans-serif",
            },
            "density": {
                "mode": "hero",
                "font_size": 66,
                "avatar_size": 102,
                "card_width": 900,
                "card_min_height": 1180,
                "card_padding": "76px 68px",
            },
            "slides": slides,
        }


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Conversational Script Generator")
    parser.add_argument("--topic", type=str, default="Making VoiceFi", help="Script topic / title")
    parser.add_argument(
        "--style", type=str, choices=["banter", "rap_battle", "tech_comedy"], default="banter"
    )
    parser.add_argument("-o", "--output", type=str, help="Output file path (.json manifest or .md)")
    parser.add_argument("--print", action="store_true", help="Print generated script to stdout")

    args = parser.parse_args()

    if args.style == "rap_battle":
        slides = ConversationalScriptEngine.generate_rap_battle_script()
        title = "🎤 AI Rap Battle · Viv vs Claude"
        slug = "ai_rap_battle_viv_claude"
        cat = "rap_battle"
    else:
        slides = ConversationalScriptEngine.generate_making_voicefi_script()
        title = "🎙️ How We Built VoiceFi · Multi-Agent Story"
        slug = "how_we_built_voicefi"
        cat = "origin_story"

    manifest = ConversationalScriptEngine.build_manifest(
        reel_id="REEL-004", title=title, slug=slug, category=cat, slides=slides
    )

    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if out_p.suffix == ".json":
            out_p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"✅ Saved Reel Manifest to: {out_p}")
        else:
            # Markdown output
            md = [f"# {title}\n"]
            for s in slides:
                md.append(f"### Slide {s['counter']} — {s['speaker']} ({s['dur']}s)")
                md.append(f"**Hook:** {s['hook']}")
                if s["body"]:
                    md.append(f"**Body:** {s['body']}")
                md.append("")
            out_p.write_text("\n".join(md), encoding="utf-8")
            print(f"✅ Saved Script Markdown to: {out_p}")

    if args.print or not args.output:
        print("\n" + "=" * 60)
        print(f"🎬 {title} (Total Duration: {manifest['audio']['duration_seconds']}s)")
        print("=" * 60)
        for s in slides:
            print(f"\n[{s['counter']}] {s['speaker']} ({s['dur']}s):")
            print(f"   Hook: {s['hook']}")
            if s["body"]:
                print(f"   Body: {s['body']}")
        print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
