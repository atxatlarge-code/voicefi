"""
Antigravity lifecycle hook and transcript integration.
Listens to agent Stop events, summarizes output, speaks aloud, and captures voice response.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from talk2me.config import Talk2MeConfig, load_config
from talk2me.tts import get_tts_engine
from talk2me.stt import get_stt_engine
from talk2me.audio.recorder import AudioRecorder
from talk2me.audio.chimes import play_chime
from talk2me.integrations.injector import inject_text_to_active_app


def clean_markdown_for_speech(text: str, max_words: int = 25) -> str:
    """
    Clean markdown formatting and extract punchy 1-2 sentence spoken updates/questions.
    """
    if not text:
        return ""

    # Remove code blocks ```...```
    text = re.sub(r"```[\s\S]*?```", " [code snippet] ", text)

    # Remove inline code `...`
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove markdown headers (#, ##, etc.) with optional leading whitespace
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)

    # Remove bold/italic markers (*, _, ~)
    text = re.sub(r"[*_~]{1,3}", "", text)

    # Remove blockquotes
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Remove bullet markers (- , * , 1. )
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Remove excessive whitespace
    text = " ".join(text.split()).strip()

    # If there are multiple sentences, look for questions or concluding statements
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences:
        # Check if the last sentence is a question
        last_sentence = sentences[-1].strip()
        if last_sentence.endswith("?") and len(last_sentence.split()) <= max_words:
            # If previous sentence is also short, combine them
            if len(sentences) >= 2 and len((sentences[-2] + " " + last_sentence).split()) <= max_words:
                return f"{sentences[-2]} {last_sentence}"
            return last_sentence
        
        # Otherwise take the first 1-2 sentences up to max_words
        first_part = ""
        for s in sentences:
            if not first_part:
                first_part = s
            elif len((first_part + " " + s).split()) <= max_words:
                first_part += " " + s
            else:
                break
        text = first_part

    # Split into words and limit length
    words = text.split()
    if len(words) > max_words:
        truncated = " ".join(words[:max_words])
        last_punct = max(truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"))
        if last_punct > len(truncated) // 2:
            return truncated[: last_punct + 1]
        return truncated + "..."

    return text


def extract_latest_agent_summary(transcript_path: Path, max_words: int = 60) -> str:
    """
    Extract the latest assistant response or question from transcript.jsonl.
    """
    if not transcript_path.is_file():
        return "I have finished the task. What would you like to do next?"

    last_model_content = ""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    step = json.loads(line)
                    step_type = step.get("type", "")
                    step_source = step.get("source", "")
                    content = step.get("content", "")

                    if (step_type == "PLANNER_RESPONSE" or step_source == "MODEL") and content:
                        last_model_content = content
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[Antigravity] Error reading transcript: {e}", file=sys.stderr)

    if not last_model_content:
        return "The process is complete and ready for your input."

    return clean_markdown_for_speech(last_model_content, max_words=max_words)


def handle_antigravity_stop_hook(payload: Dict[str, Any], config: Optional[Talk2MeConfig] = None) -> Dict[str, Any]:
    """
    Execute the Talk 2 Me loop on Antigravity Stop event.
    
    1. Summarize agent turn.
    2. Speak summary via TTS.
    3. Open mic, record speech with VAD.
    4. Transcribe via STT.
    5. Inject transcribed text into active window.
    """
    cfg = config or load_config()

    transcript_path_str = payload.get("transcriptPath", "")
    transcript_path = Path(transcript_path_str) if transcript_path_str else Path("")

    summary = extract_latest_agent_summary(transcript_path, max_words=cfg.antigravity.max_spoken_words)

    # 1. Speak summary if enabled
    if cfg.antigravity.read_summary_aloud and summary:
        tts = get_tts_engine(cfg)
        tts.speak(summary, block=True)

    # 2. Automatically listen if enabled
    if cfg.antigravity.auto_listen:
        if cfg.audio_cues.enabled:
            play_chime("start", block=False)

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=cfg.vad.max_record_seconds,
        )

        audio_data, temp_wav = recorder.record_speech_auto()

        stt = get_stt_engine(cfg)
        try:
            transcription = stt.transcribe(temp_wav)
        finally:
            temp_wav.unlink(missing_ok=True)

        if transcription and transcription.strip():
            if cfg.antigravity.inject_to_active_window:
                inject_text_to_active_app(transcription, submit_enter=True)

            if cfg.audio_cues.enabled:
                play_chime(cfg.audio_cues.sent_chime, block=False)

    return {}
