#!/usr/bin/env python3
"""
VoiceFi™ Gemini Multi-Speaker Dialogue Generator.
Synthesizes expressive multi-speaker dialogues programmatically using
Google's Gemini TTS API without needing to click buttons in Google AI Studio.

Features:
- Auto-detects speakers from "Speaker: Text" or "Name: Text" formats.
- Supports all Gemini neural voices: Aoede, Puck, Charon, Kore, Fenrir.
- Retains inline emotional & pacing tags: [excited], [whispers], [chuckles], [pause 1.0s].
- Automatically writes standard WAV audio file (24kHz mono PCM).
- Optional instant playback via macOS `afplay`.
"""

import argparse
import io
import os
import re
import subprocess
import sys
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add VoiceFi to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from voicefi.config import resolve_gemini_api_key

DEFAULT_VOICE_MAP = {
    "speaker 1": "Aoede",
    "speaker1": "Aoede",
    "aoede": "Aoede",
    "viv": "Aoede",
    "speaker 2": "Puck",
    "speaker2": "Puck",
    "puck": "Puck",
    "claude": "Puck",
    "charon": "Charon",
    "narrator": "Charon",
    "attenborough": "Charon",
    "kore": "Kore",
    "fenrir": "Fenrir",
}

VALID_GEMINI_VOICES = {"Aoede", "Puck", "Charon", "Kore", "Fenrir"}


def parse_script_lines(text: str) -> List[Tuple[str, str]]:
    """
    Parses a script into a list of (speaker_label, utterance) tuples.
    Recognizes lines like:
      Aoede: Hello there!
      Speaker 1 (Aoede): [whispers] Are you ready?
      Puck: Yes!
    """
    parsed = []
    lines = text.strip().splitlines()
    current_speaker = "Aoede"
    current_text = []

    speaker_pattern = re.compile(r"^\s*([A-Za-z0-9_\s\(\)]+?)\s*:\s*(.*)$")

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        match = speaker_pattern.match(line_str)
        if match:
            # Check if what precedes the colon looks like a speaker name
            raw_speaker = match.group(1).strip()
            rest = match.group(2).strip()
            # Clean up speaker name, e.g. "Speaker 1 (Aoede)" -> "Aoede" or "Speaker 1"
            clean_speaker = raw_speaker
            if "(" in clean_speaker and ")" in clean_speaker:
                inside = clean_speaker[clean_speaker.find("(") + 1 : clean_speaker.find(")")].strip()
                if inside.capitalize() in VALID_GEMINI_VOICES:
                    clean_speaker = inside.capitalize()
                else:
                    clean_speaker = clean_speaker[: clean_speaker.find("(")].strip()

            parsed.append((clean_speaker, rest))
        else:
            if parsed:
                # Append continuation line to previous utterance
                prev_speaker, prev_text = parsed[-1]
                parsed[-1] = (prev_speaker, f"{prev_text} {line_str}")
            else:
                parsed.append(("Speaker 1", line_str))

    return parsed


def generate_gemini_dialogue(
    script_text: str,
    output_path: Optional[Path] = None,
    speaker_map: Optional[Dict[str, str]] = None,
    model: str = "gemini-2.5-flash-preview-tts",
    api_key: Optional[str] = None,
) -> Path:
    """
    Synthesizes a multi-speaker script into a WAV file using Google Gemini TTS API.
    """
    from google import genai
    from google.genai import types

    key = api_key or resolve_gemini_api_key() or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "Gemini API key not found! Please set GEMINI_API_KEY in your environment "
            "or run `vifi setup` to configure your keys."
        )

    parsed = parse_script_lines(script_text)
    if not parsed:
        raise ValueError("Script text is empty or could not be parsed into speaker lines.")

    # Identify distinct speakers in the script
    unique_speakers = []
    for spk, _ in parsed:
        if spk not in unique_speakers:
            unique_speakers.append(spk)

    # Build speaker-to-voice mapping
    s_map = speaker_map or {}
    assigned_configs = []
    
    # We assign voices to speakers in order
    fallback_voices = ["Aoede", "Puck", "Charon", "Kore", "Fenrir"]
    
    # Format a clean standardized prompt for Gemini TTS
    formatted_lines = []
    
    # Gemini multi-speaker supports up to 2 distinct speakers in multi_speaker_voice_config
    # Standardize speaker labels to Speaker1 and Speaker2 if there are 2 speakers
    if len(unique_speakers) == 2:
        spk1_orig, spk2_orig = unique_speakers[0], unique_speakers[1]
        voice1 = s_map.get(spk1_orig) or DEFAULT_VOICE_MAP.get(spk1_orig.lower(), fallback_voices[0])
        voice2 = s_map.get(spk2_orig) or DEFAULT_VOICE_MAP.get(spk2_orig.lower(), fallback_voices[1])
        
        # Ensure voice1 and voice2 are valid
        voice1 = voice1.capitalize() if voice1.capitalize() in VALID_GEMINI_VOICES else "Aoede"
        voice2 = voice2.capitalize() if voice2.capitalize() in VALID_GEMINI_VOICES else "Puck"
        if voice1 == voice2:
            voice2 = "Puck" if voice1 == "Aoede" else "Aoede"

        speaker_configs = [
            types.SpeakerVoiceConfig(
                speaker="Speaker1",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice1)
                ),
            ),
            types.SpeakerVoiceConfig(
                speaker="Speaker2",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice2)
                ),
            ),
        ]

        for spk, utt in parsed:
            label = "Speaker1" if spk == spk1_orig else "Speaker2"
            formatted_lines.append(f"{label}: {utt}")

        prompt = "\n".join(formatted_lines)
        speech_config = types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=speaker_configs
            )
        )
    else:
        # Single speaker or custom mapping
        spk = unique_speakers[0]
        voice = s_map.get(spk) or DEFAULT_VOICE_MAP.get(spk.lower(), "Aoede")
        voice = voice.capitalize() if voice.capitalize() in VALID_GEMINI_VOICES else "Aoede"
        
        prompt = "\n".join([utt for _, utt in parsed])
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        )

    client = genai.Client(api_key=key)
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
    )

    print(f"🎙️ Synthesizing dialogue via {model}...")
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    audio_bytes = None
    if resp.candidates:
        parts = resp.candidates[0].content.parts
        for part in parts:
            if part.inline_data and part.inline_data.data:
                audio_bytes = part.inline_data.data
                break

    if not audio_bytes:
        raise RuntimeError("No audio bytes returned from Gemini TTS API.")

    # Determine destination WAV
    if output_path is None:
        output_dir = repo_root / "dist" / "generated_dialogues"
        output_dir.mkdir(parents=True, exist_ok=True)
        import time
        output_path = output_dir / f"dialogue_{int(time.time())}.wav"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Gemini returns 24kHz mono 16-bit PCM. Wrap in a standard WAV header.
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_bytes)

    print(f"✅ Dialogue saved to: {output_path} ({len(audio_bytes):,} bytes)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Programmatically synthesize multi-speaker dialogues with Gemini TTS.")
    parser.add_argument("script", nargs="?", default="", help="Inline script text to synthesize.")
    parser.add_argument("-f", "--file", help="Path to text or markdown file containing the script.")
    parser.add_argument("-o", "--out", help="Output WAV path (default: dist/generated_dialogues/dialogue_<ts>.wav).")
    parser.add_argument("--voice1", default="Aoede", help="Voice for Speaker 1 (default: Aoede).")
    parser.add_argument("--voice2", default="Puck", help="Voice for Speaker 2 (default: Puck).")
    parser.add_argument("--model", default="gemini-2.5-flash-preview-tts", help="TTS Model ID.")
    parser.add_argument("-p", "--play", action="store_true", help="Automatically play synthesized audio aloud with afplay.")

    args = parser.parse_args()

    script_text = ""
    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"❌ File not found: {fpath}", file=sys.stderr)
            sys.exit(1)
        script_text = fpath.read_text(encoding="utf-8")
    elif args.script:
        script_text = args.script
    else:
        # Check stdin
        if not sys.stdin.isatty():
            script_text = sys.stdin.read()
        else:
            # Provide sample default
            script_text = (
                "Aoede: [soft sigh] Jake, tell me you didn't just merge directly into main.\n"
                "Puck: [chuckles] Define directly! GitHub Actions was thinking about turning green!"
            )
            print("💡 No script provided. Using default demo script:\n" + script_text + "\n")

    speaker_map = {
        "Speaker1": args.voice1,
        "Speaker 1": args.voice1,
        "Aoede": args.voice1,
        "Speaker2": args.voice2,
        "Speaker 2": args.voice2,
        "Puck": args.voice2,
    }

    try:
        out_wav = generate_gemini_dialogue(
            script_text=script_text,
            output_path=Path(args.out) if args.out else None,
            speaker_map=speaker_map,
            model=args.model,
        )

        if args.play:
            print("🔊 Playing synthesized audio...")
            subprocess.run(["afplay", str(out_wav)], check=True)

    except Exception as e:
        print(f"❌ Error synthesizing dialogue: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
