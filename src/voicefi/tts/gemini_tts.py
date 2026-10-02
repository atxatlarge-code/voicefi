"""
Google Gemini Neural Voice & Multimodal Live TTS Provider for VoiceFi.
Supports Google's native neural voices: Aoede, Puck, Charon, Kore, Fenrir.
"""

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from voicefi.tts.base import (
    BaseTTS,
    speech_turn_lock,
    DuplicateSpeechSuppressed,
    is_speech_interrupted,
    set_agent_audio_playing,
    is_agent_speaking,
    safe_terminate_process,
)
from voicefi.audio.meeting_detection import is_user_on_call
from voicefi.tts.normalizer import normalize_tts_text

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def truncate_or_summarize_sentence(sentence: str, max_words: int = 18) -> str:
    """
    Truncate or compress a long sentence at a natural clause boundary (comma, dash, semicolon, colon)
    or word budget so it remains punchy, clear, and conversational.
    """
    if not sentence or not sentence.strip():
        return ""
    s = sentence.strip()
    words = s.split()
    if max_words is None or max_words <= 0 or len(words) <= max_words:
        return s

    # 1. Look for the earliest natural clause break (comma, semicolon, dash, colon)
    # that already has sufficient substance (min_words >= 5) so it forms a complete thought
    min_words = max(5, int(max_words * 0.35))
    first_chunk = " ".join(words[: max_words + 1])

    clause_delimiters = [",", ";", ":", "—", " - ", "–"]
    breaks = []
    for delim in clause_delimiters:
        for m in re.finditer(re.escape(delim), first_chunk):
            pos = m.start()
            prefix = first_chunk[:pos].strip()
            w_count = len(prefix.split())
            if min_words <= w_count <= max_words:
                breaks.append((pos, w_count))

    if breaks:
        # Pick the earliest clause boundary that satisfies min_words for a crisp punchy summary
        breaks.sort(key=lambda b: b[0])
        best_pos = breaks[0][0]
        clause = first_chunk[:best_pos].strip()
        clause = re.sub(r"[\s,;:\-—–]+$", "", clause).strip()
        if clause:
            if not clause.endswith((".", "!", "?")):
                clause += "."
            return clause

    # 2. Cut cleanly at max_words, stripping dangling prepositions / conjunctions
    truncated = " ".join(words[:max_words]).strip()
    truncated = re.sub(
        r"\b(?:and|or|but|with|for|to|in|on|at|by|of|that|which|because|as|if|then|when|where|while)\s*$",
        "",
        truncated,
        flags=re.IGNORECASE,
    ).strip()
    truncated = re.sub(r"[\s,;:\-—–]+$", "", truncated).strip()
    if truncated and not truncated.endswith((".", "!", "?")):
        truncated += "."
    return truncated


def extract_first_sentence(text: str, max_words: Optional[int] = 18) -> str:
    """
    Extract the first complete sentence from the text, handling markdown headers,
    bullet points, and short acknowledgments.
    If the sentence exceeds max_words, it is cleanly cut off at a natural clause
    boundary (comma, dash, semicolon) or word budget so it remains punchy.
    """
    if not text or not text.strip():
        return ""
    t = text.strip()
    # Strip leading markdown header tags or bullet points
    t = re.sub(r"^[#*`\-_—\s]+", "", t).strip()

    # Find the first sentence ending with [.!?] (ignoring ellipses)
    match = re.search(r"^(.*?(?<!\.)[.!?](?!\.))(?:\s+|$)", t, flags=re.DOTALL)
    if match:
        first = match.group(1).strip()
        words = first.split()
        # If the first segment is trivial like "Done.", "Sure!", "Okay." (<= 2 words),
        # grab the subsequent sentence to form a complete thought
        if len(words) <= 2 and len(t) > len(first):
            remainder = t[len(first):].strip()
            remainder = re.sub(r"^[#*`\-_—\s]+", "", remainder).strip()
            second_match = re.search(r"^(.*?(?<!\.)[.!?](?!\.))(?:\s+|$)", remainder, flags=re.DOTALL)
            if second_match:
                first = f"{first} {second_match.group(1).strip()}"
        if max_words:
            return truncate_or_summarize_sentence(first, max_words=max_words)
        return first

    if max_words:
        return truncate_or_summarize_sentence(t, max_words=max_words)
    return t


DEFAULT_CHARACTER_PROMPT_TEMPLATE = (
    "You are {character_persona}.\n"
    "The user will be spoken the first sentence summarizing the work:\n"
    "Sentence one: \"{first_sentence}\"\n"
    "Context of the work just completed:\n{context}\n\n"
    "TASK:\n"
    "Invent ONLY the SECOND sentence to follow sentence one.\n"
    "- Deliver it strictly in your character persona ({character_persona}).\n"
    "- It can be a punchy joke, funny military bark, witty remark, or humorous reaction strictly related to this work.\n"
    "- CRITICAL: Do not repeat, rephrase, or echo Sentence one. Your response must start immediately with your in-character reaction.\n"
    "- Include natural inline stage directions like [bark], [shouts], [chuckles], [sigh] where fitting.\n"
    "- Keep it concise (1 to 2 short sentences, under 25 words). ALWAYS finish your full thought and end with clean punctuation (. ! ?).\n"
    "- Output ONLY the spoken dialogue wrapped in <reaction>...</reaction> tags. No other text or markdown."
)


def normalize_stage_directions(text: str) -> str:
    """
    Normalize plural or informal acting tags into standardized singular cues
    so Gemini 3.8 Latent Audio and TTS models interpret them as acoustic actions.
    """
    if not text:
        return ""
    text = re.sub(r"\[\s*sighs?\s*\]", "[sigh]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*giggles?\s*\]", "[giggle]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*laughs?\s*\]", "[laugh]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*chuckles?\s*\]", "[chuckle]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*whispers?\s*\]", "[whisper]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*gasps?\s*\]", "[gasp]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*growls?\s*\]", "[growl]", text, flags=re.IGNORECASE)
    return text


def clean_character_statement(raw_statement: str, first_sentence: str = "") -> str:
    """
    Clean and isolate a character reaction statement, preventing repetition of the first sentence,
    stripping roleplay prefixes/labels, extracting delimited content, and ensuring complete sentence termination.
    """
    if not raw_statement or not raw_statement.strip():
        return ""

    text = raw_statement.strip()

    # 1. Extract from <reaction>...</reaction> or <statement>...</statement> if present
    xml_match = re.search(
        r"<(?:reaction|statement)[^>]*>(.*?)</(?:reaction|statement)>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if xml_match:
        text = xml_match.group(1).strip()
    else:
        # Strip unmatched opening or closing XML tags if model omitted closing tag
        text = re.sub(r"^<(?:reaction|statement)[^>]*>\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*</(?:reaction|statement)>$", "", text, flags=re.IGNORECASE)

    # 2. Strip conversational prefixes and line labels like "Sentence 2:", "Reaction:", "Persona:"
    text = re.sub(
        r"^(?:sentence\s*2\s*[:\-]|reaction\s*[:\-]|character\s*[:\-]|statement\s*[:\-]|second\s*sentence\s*[:\-])\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # Strip if model printed both: "Sentence 1: ... \nSentence 2: ..."
    if re.search(r"sentence\s*1\s*[:\-]", text, flags=re.IGNORECASE) and re.search(
        r"sentence\s*2\s*[:\-]", text, flags=re.IGNORECASE
    ):
        s2_match = re.search(
            r"sentence\s*2\s*[:\-]\s*(.*)$", text, flags=re.DOTALL | re.IGNORECASE
        )
        if s2_match:
            text = s2_match.group(1).strip()

    # 3. Strip wrapping quotes
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    # 4. Check for direct repetition or echo of first_sentence
    if first_sentence and first_sentence.strip():
        fs_norm = re.sub(r"[.!?\s]+$", "", first_sentence.strip()).lower()
        if fs_norm:
            text_norm = text.lower()
            if text_norm.startswith(fs_norm):
                remainder = text[len(fs_norm) :].strip()
                remainder = re.sub(r"^[\s.!?,\-—:]+", "", remainder).strip()
                if remainder:
                    text = remainder
            else:
                # Semantic / token-overlap check for paraphrased echoes
                first_clause_match = re.search(r"^(.*?[.!?])(?:\s+|$)", text)
                if first_clause_match:
                    fc = first_clause_match.group(1).strip()
                    fc_words = set(re.findall(r"\w{3,}", fc.lower()))
                    fs_words = set(re.findall(r"\w{3,}", fs_norm))
                    if fc_words and fs_words and len(fc_words & fs_words) / len(fc_words) >= 0.65:
                        remainder = text[len(fc) :].strip()
                        remainder = re.sub(r"^[\s.!?,\-—:]+", "", remainder).strip()
                        if remainder:
                            text = remainder

    # Strip any lingering quotes after prefix/duplicate stripping
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    # Normalize bracketed stage directions (e.g. [giggles] -> [giggle], [sighs] -> [sigh])
    text = normalize_stage_directions(text)

    # 5. Ensure complete sentence termination punctuation
    text = text.strip()
    if text and not text.endswith((".", "!", "?", '"', "'", "”", "’")):
        text += "."

    return text.strip()


def is_joke_turn(text: str, conv_id: Optional[str] = None) -> bool:
    """
    Detect if the current turn is a joke, pun, or humor delivery so it can be spoken
    verbatim rather than summarized or meta-commented on.
    """
    text_clean = text.strip()
    text_lower = text_clean.lower()

    # 1. Obvious joke starters
    joke_starters = (
        "why do",
        "why did",
        "why was",
        "why don't",
        "why can't",
        "why shouldn't",
        "what do you call",
        "what's the difference",
        "what is the difference",
        "how many programmers",
        "how many developers",
        "how many software engineers",
        "how many engineers",
        "walks into a bar",
        "walked into a bar",
        "walk into a bar",
        "knock, knock",
        "knock knock",
        "there are 10 types of people",
        "there are only 10 types",
    )
    if any(
        text_lower.startswith(s) or f"\n{s}" in text_lower or f" {s}" in text_lower
        for s in joke_starters
    ):
        return True

    # 2. Q&A punchline format under 35 words: "Question? Answer."
    words = text_clean.split()
    if "?" in text_clean and len(words) <= 35:
        q_part = text_clean.split("?")[0].lower().strip()
        if any(q_part.startswith(w) for w in ("why", "what", "how", "who", "which", "where")):
            return True

    # 3. Check recent conversation context for joke request
    if conv_id:
        try:
            transcript_path = (
                Path.home()
                / ".gemini"
                / "antigravity"
                / "brain"
                / conv_id
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            )
            if transcript_path.is_file():
                with open(transcript_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines[-25:]):
                    try:
                        step = json.loads(line)
                        if step.get("type") == "USER_INPUT" or step.get("source") in (
                            "USER_EXPLICIT",
                            "USER",
                        ):
                            content = str(step.get("content", "")).lower()
                            if any(k in content for k in ("joke", "pun", "funny", "laugh", "humor")):
                                return True
                            break
                    except Exception:
                        pass
        except Exception:
            pass

    return False


class GeminiTTS(BaseTTS):
    """
    Text-to-Speech provider using Google Gemini Neural Voices.
    Supports Aoede, Puck, Charon, Kore, Fenrir with instant offline fallback.
    """

    VALID_VOICES = {
        "puck": "Puck",
        "charon": "Charon",
        "kore": "Kore",
        "fenrir": "Fenrir",
        "aoede": "Aoede",
        "zephyr": "Zephyr",
        "leda": "Leda",
        "orus": "Orus",
        "callirrhoe": "Callirrhoe",
        "autonoe": "Autonoe",
        "enceladus": "Enceladus",
        "iapetus": "Iapetus",
        "umbriel": "Umbriel",
        "algieba": "Algieba",
        "despina": "Despina",
        "erinome": "Erinome",
        "algenib": "Algenib",
        "rasalgethi": "Rasalgethi",
        "laomedeia": "Laomedeia",
        "achernar": "Achernar",
        "alnilam": "Alnilam",
        "schedar": "Schedar",
        "gacrux": "Gacrux",
        "pulcherrima": "Pulcherrima",
        "achird": "Achird",
        "zubenelgenubi": "Zubenelgenubi",
        "vindemiatrix": "Vindemiatrix",
        "sadachbia": "Sadachbia",
        "sadaltager": "Sadaltager",
        "sulafat": "Sulafat",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: str = "Puck",
        model: str = "gemini-3.8-flash-tts",
        temperature: float = 0.3,
        style: Optional[str] = None,
    ):
        super().__init__()
        from voicefi.config import resolve_gemini_api_key

        self.api_key = (
            api_key
            or resolve_gemini_api_key()
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        )
        self.voice = self._normalize_voice_name(voice)
        self.model = model or "gemini-3.8-flash-tts"
        self.temperature = temperature
        self.style = style
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def _normalize_voice_name(self, voice: str) -> str:
        """Normalize voice name to valid Gemini voice."""
        if not voice:
            return "Aoede"
        clean = voice.lower().strip()
        return self.VALID_VOICES.get(clean, "Aoede")

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        proc = self._current_process
        if proc:
            safe_terminate_process(proc)
            self._current_process = None

    def _fallback_to_microsoft_luke(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        """
        Tier 2 Failover: When Gemini Live hits an error, seamlessly fall back
        to Microsoft EdgeTTS using the designated 'Luke' voice (en-ZA-LukeNeural)
        so the user immediately recognizes by ear that a failover occurred.
        """
        if (
            not clean_text
            or not clean_text.strip()
            or self._stop_requested
            or is_speech_interrupted(turn_start_time)
        ):
            return

        from voicefi.config import load_config
        cfg = load_config()
        fallback_voice = getattr(cfg.tts, "live_fallback_voice", "en-ZA-LukeNeural") or "en-ZA-LukeNeural"

        print(
            f"[GeminiTTS] ⚠️ Gemini Live synthesis error; falling back to Microsoft voice 'Luke' ({fallback_voice})"
        )
        try:
            from voicefi.tts.edge_tts import EdgeTTS
            edge = EdgeTTS(
                voice=fallback_voice,
                streaming=True,
                agent_name=getattr(self, "agent_name", "VoiceFi"),
                persona_name="Luke (Failover)",
            )
            edge.stream_speak(clean_text, block=True)
        except Exception as edge_err:
            logger.debug("Microsoft EdgeTTS fallback failed: %s", edge_err)
            # Tier 3 Emergency: Pure local offline macOS say
            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)

    def _fallback_speak_direct(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        """Fallback speak directly using macOS say without re-acquiring lock."""
        if (
            not clean_text
            or not clean_text.strip()
            or self._stop_requested
            or is_speech_interrupted(turn_start_time)
        ):
            return
        try:
            from voicefi.tts.offline import is_voice_installed

            try:
                has_fb, exact_fb = is_voice_installed("Ava (Premium)")
                target_voice = (
                    exact_fb if (has_fb and exact_fb) else ("Ava" if has_fb else "Samantha")
                )
            except Exception:
                target_voice = "Samantha"
            print(
                f"[GeminiTTS] ⚠️ Online synthesis unavailable; falling back to offline voice '{target_voice}'"
            )
            cmd = ["say", "-v", target_voice, "--", clean_text]
            if (
                not self._stop_requested
                and not is_speech_interrupted(turn_start_time)
                and is_agent_speaking()
            ):
                set_agent_audio_playing(True)
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = proc
                proc.wait()
                was_interrupted = (
                    self._stop_requested
                    or is_speech_interrupted(turn_start_time)
                    or (proc.returncode in (-9, -15, 137, 143))
                )
                if not was_interrupted and proc.returncode != 0:
                    fallback = subprocess.Popen(
                        ["say", "--", clean_text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process = fallback
                    fallback.wait()
        except Exception as ex:
            print(f"[GeminiTTS] Offline fallback error: {ex}")
        finally:
            set_agent_audio_playing(False)
            self._current_process = None

    def _generate_audio_bytes_live(self, text: str) -> Optional[bytes]:
        """Synthesize audio using bidirectional WebSocket Live streaming."""
        if not self.api_key:
            return None
        try:
            import asyncio
            import io
            import wave
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            clean_text = normalize_stage_directions(text)
            sys_parts = [
                types.Part.from_text(
                    text=(
                        "Act out all bracketed stage directions (such as [giggle], [sigh], [laugh], [chuckle], [gasp], [whisper], [pause]) "
                        "as genuine vocal sounds, laughs, breaths, and acoustic actions. "
                        "NEVER pronounce or speak the words inside brackets."
                    )
                )
            ]
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=types.Content(parts=sys_parts),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                    )
                ),
            )

            async def _run():
                chunks = []
                async with client.aio.live.connect(model=self.model, config=config) as session:
                    await session.send_realtime_input(text=clean_text)
                    async for response in session.receive():
                        if response.server_content and response.server_content.model_turn:
                            for part in response.server_content.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    chunks.append(part.inline_data.data)
                        if response.server_content and response.server_content.turn_complete:
                            break
                if chunks:
                    raw_pcm = b"".join(chunks)
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(raw_pcm)
                    return buf.getvalue()
                return None

            return asyncio.run(_run())
        except Exception as e:
            logger.debug("Gemini Live synthesis failed: %s", e)
            return None

    def _generate_audio_bytes(
        self, text: str, style: Optional[str] = None, timeout: float = 15.0
    ) -> Optional[bytes]:
        """Request audio synthesis from Gemini API with optional style tags."""
        if not self.api_key:
            return None

        if "live" in self.model:
            live_bytes = self._generate_audio_bytes_live(text)
            if live_bytes:
                return live_bytes

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        effective_style = style or self.style
        clean_prompt_text = normalize_stage_directions(text)

        # Infer emotional style cues from inline acting tags to steer Gemini TTS
        inferred_styles = []
        if re.search(r"\[giggle\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("playful giggling")
        if re.search(r"\[laugh\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("laughing, amused")
        if re.search(r"\[sigh\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("weary sigh")
        if re.search(r"\[whisper\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("hushed whisper")
        if re.search(r"\[gasp\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("shocked gasp")
        if re.search(r"\[chuckle\]", clean_prompt_text, re.IGNORECASE):
            inferred_styles.append("gentle chuckle")

        if inferred_styles:
            inferred_str = ", ".join(inferred_styles)
            if effective_style:
                if not any(k in str(effective_style).lower() for k in ("giggle", "laugh", "sigh", "whisper", "gasp", "chuckle")):
                    effective_style = f"{effective_style}, {inferred_str}"
            else:
                effective_style = inferred_str

        part_dict: Dict[str, Any] = {"text": clean_prompt_text}
        if effective_style:
            part_dict["speech_metadata"] = {"style": str(effective_style)}

        body: Dict[str, Any] = {
            "contents": [{"parts": [part_dict]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        inline_data = part.get("inlineData", {})
                        if inline_data.get("mimeType", "").startswith("audio/") and inline_data.get(
                            "data"
                        ):
                            return base64.b64decode(inline_data["data"])
            else:
                logger.debug(
                    "Gemini TTS non-200 response [%s]: %s", resp.status_code, resp.text[:200]
                )
                try:
                    from voicefi.telemetry import capture_exception

                    capture_exception(
                        RuntimeError(f"Gemini TTS HTTP {resp.status_code}: {resp.text[:120]}"),
                        properties={
                            "component": "tts_gemini",
                            "voice": getattr(self, "voice", "unknown"),
                            "provider_status_code": resp.status_code,
                        },
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Gemini TTS synthesis request failed: %s", e)
            try:
                from voicefi.telemetry import capture_exception

                capture_exception(
                    e,
                    properties={
                        "component": "tts_gemini",
                        "voice": getattr(self, "voice", "unknown"),
                    },
                )
            except Exception:
                pass

        return None

    def generate_dialogue_bytes(
        self,
        turns: list[Dict[str, Any]],
        speakers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> Optional[bytes]:
        """Synthesize multi-speaker scripted dialogue from Gemini 3.8 Flash TTS."""
        if not self.api_key or not turns:
            return None

        # Collect unique speakers
        unique_speakers: list[str] = []
        for t in turns:
            spk = t.get("speaker", "Speaker")
            if spk not in unique_speakers:
                unique_speakers.append(spk)

        resolved_speakers: Dict[str, str] = {}
        if speakers:
            resolved_speakers = {k: self._normalize_voice_name(v) for k, v in speakers.items()}
        else:
            default_voices = [self.voice, "Charon" if self.voice != "Charon" else "Puck"]
            for i, spk in enumerate(unique_speakers):
                resolved_speakers[spk] = default_voices[i % len(default_voices)]

        # Gemini MultiSpeakerVoiceConfig requires exactly 2 speaker configurations
        speaker_configs = [
            {"speaker": spk_name, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}}
            for spk_name, voice_name in list(resolved_speakers.items())[:2]
        ]

        script_parts = []
        for turn in turns:
            spk = turn.get("speaker", unique_speakers[0] if unique_speakers else "Speaker")
            txt = normalize_tts_text(turn.get("text", ""))
            if not txt:
                continue
            meta: Dict[str, Any] = {"speaker": spk}
            if turn.get("style"):
                meta["style"] = str(turn["style"])
            script_parts.append({"text": txt, "speech_metadata": meta})

        if not script_parts:
            return None

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        body: Dict[str, Any] = {
            "contents": [{"parts": script_parts}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "multi_speaker_voice_config": {"speaker_voice_configs": speaker_configs}
                },
            },
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        inline_data = part.get("inlineData", {})
                        if inline_data.get("mimeType", "").startswith("audio/") and inline_data.get(
                            "data"
                        ):
                            return base64.b64decode(inline_data["data"])
            else:
                logger.debug(
                    "Gemini TTS dialogue non-200 response [%s]: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.debug("Gemini TTS dialogue request failed: %s", e)

        return None

    def speak_to_file(self, text: str, output_path: Path, style: Optional[str] = None) -> bool:
        """Synthesize audio directly to a file without playing through speakers."""
        if not text or not text.strip():
            return False
        clean_text = normalize_tts_text(text)
        audio_bytes = self._generate_audio_bytes(clean_text, style=style)
        if audio_bytes:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_bytes)
                return True
            except Exception:
                pass
        return False

    async def synthesize_to_file(
        self, text: str, output_path: Path, style: Optional[str] = None
    ) -> bool:
        """Asynchronously synthesize speech directly to an audio file."""
        return self.speak_to_file(text, output_path, style=style)

    def synthesize_dialogue_to_file(
        self,
        turns: list[Dict[str, Any]],
        output_path: Path,
        speakers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Synthesize multi-speaker scripted dialogue directly to audio file."""
        audio_bytes = self.generate_dialogue_bytes(turns, speakers=speakers)
        if audio_bytes:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_bytes)
                return True
            except Exception as e:
                logger.error("Failed writing dialogue audio to %s: %s", output_path, e)
        return False

    def speak(self, text: str, block: bool = True, style: Optional[str] = None) -> None:
        """Synthesize and play speech via Gemini Neural Voice with instant offline fallback."""
        if not text or not text.strip():
            return

        if is_user_on_call():
            print("[GeminiTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=self.voice,
                    app_name=getattr(self, "app_name", "Antigravity"),
                    conv_id=getattr(self, "conv_id", ""),
                    workspace_path=getattr(self, "workspace_path", ""),
                ):
                    nonlocal turn_start_time
                    turn_start_time = time.time()
                    self._stop_requested = False

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    audio_bytes = self._generate_audio_bytes(clean_text, style=style)
                    if (
                        not audio_bytes
                        or self._stop_requested
                        or is_speech_interrupted(turn_start_time)
                    ):
                        if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)
                        return

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_path = Path(f.name)
                        temp_path.write_bytes(audio_bytes)

                    try:
                        if (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and is_agent_speaking()
                        ):
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(
                                ["afplay", str(temp_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_process = proc
                            proc.wait()
                    finally:
                        set_agent_audio_playing(False)
                        self._current_process = None
                        temp_path.unlink(missing_ok=True)

            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                logger.debug("GeminiTTS speak error: %s", e)
                if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                    self._fallback_to_microsoft_luke(clean_text, turn_start_time=turn_start_time)

        if block:
            _run()
        else:
            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def speak_dialogue(
        self,
        turns: list[Dict[str, Any]],
        speakers: Optional[Dict[str, str]] = None,
        block: bool = True,
    ) -> None:
        """Synthesize and play multi-speaker dialogue with turn locking."""
        if not turns:
            return
        if is_user_on_call():
            print("[GeminiTTS] User is on a call. Skipping dialogue playback.")
            return

        full_transcript = " ".join(t.get("text", "") for t in turns)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=full_transcript,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name="Dialogue",
                    app_name=getattr(self, "app_name", "Antigravity"),
                    conv_id=getattr(self, "conv_id", ""),
                    workspace_path=getattr(self, "workspace_path", ""),
                ):
                    nonlocal turn_start_time
                    turn_start_time = time.time()
                    self._stop_requested = False

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    audio_bytes = self.generate_dialogue_bytes(turns, speakers=speakers)
                    if (
                        not audio_bytes
                        or self._stop_requested
                        or is_speech_interrupted(turn_start_time)
                    ):
                        return

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_path = Path(f.name)
                        temp_path.write_bytes(audio_bytes)

                    try:
                        if (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and is_agent_speaking()
                        ):
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(
                                ["afplay", str(temp_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_process = proc
                            proc.wait()
                    finally:
                        set_agent_audio_playing(False)
                        self._current_process = None
                        temp_path.unlink(missing_ok=True)
            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                logger.debug("GeminiTTS speak_dialogue error: %s", e)

        if block:
            _run()
        else:
            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def stream_speak(self, text: str, block: bool = True, style: Optional[str] = None) -> None:
        """Stream and speak audio with minimal latency using WebSockets and optional Character Interceptor."""
        if not text or not text.strip():
            return
            
        if is_user_on_call():
            print("[GeminiTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()
        
        # Determine if this is Live API mode vs Standard turn-end
        from voicefi.config import load_config
        cfg = load_config()
        turn_end_mode = getattr(cfg.tts, "turn_end_mode", "standard")
        is_live_mode = (
            turn_end_mode == "gemini_live"
            or getattr(self, "model", "") == "gemini-3.8-live"
            or getattr(cfg.tts, "provider", "") == "gemini_live"
        )
        character_persona = getattr(cfg.tts, "character_persona", None)
        do_summary = getattr(cfg.tts, "character_summarization", False)
        
        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=self.voice,
                    app_name=getattr(self, "app_name", "Antigravity"),
                    conv_id=getattr(self, "conv_id", ""),
                    workspace_path=getattr(self, "workspace_path", ""),
                    tag_text="● LIVE" if is_live_mode else None,
                    is_live=is_live_mode,
                ):
                    nonlocal turn_start_time
                    turn_start_time = time.time()
                    
                    # 1. Speech Structuring & Character Interceptor
                    final_text = clean_text
                    speech_structure = getattr(
                        cfg.tts, "speech_structure", "first_sentence_plus_character"
                    )
                    verbatim_jokes = getattr(cfg.tts, "verbatim_jokes", True)
                    turn_conv_id = getattr(self, "conv_id", "")
                    is_joke = verbatim_jokes and is_joke_turn(clean_text, conv_id=turn_conv_id)

                    # If this turn is a joke, deliver verbatim without summarization or meta-commentary!
                    if is_joke:
                        final_text = clean_text
                    elif do_summary and character_persona and speech_structure != "verbatim":
                        first_sentence_word_limit = getattr(cfg.tts, "max_first_sentence_words", 18)
                        first_sentence = extract_first_sentence(clean_text, max_words=first_sentence_word_limit)

                        prompt_tmpl = (
                            getattr(cfg.tts, "character_prompt_template", None)
                            or DEFAULT_CHARACTER_PROMPT_TEMPLATE
                        )
                        try:
                            summary_prompt = prompt_tmpl.format(
                                character_persona=character_persona,
                                first_sentence=first_sentence,
                                context=clean_text[:1200],
                            )
                        except (KeyError, IndexError):
                            summary_prompt = DEFAULT_CHARACTER_PROMPT_TEMPLATE.format(
                                character_persona=character_persona,
                                first_sentence=first_sentence,
                                context=clean_text[:1200],
                            )

                        character_summary = ""
                        # Primary: Google Cloud Gemini 3.5 Flash Lite (ultra-low latency ~170ms)
                        if self.api_key:
                            for m in ("gemini-3.5-flash-lite", "gemini-2.5-flash"):
                                try:
                                    from google import genai

                                    f_client = genai.Client(api_key=self.api_key)
                                    f_resp = f_client.models.generate_content(
                                        model=m,
                                        contents=f"{summary_prompt}\n\nAgent outcome:\n{clean_text[:1500]}",
                                    )
                                    if f_resp and f_resp.text:
                                        character_summary = f_resp.text.strip()
                                        break
                                except Exception as e:
                                    logger.debug(f"{m} summarization error: {e}")

                        # Fallback: Warm Local Gemma 4 2B on port 9379 (if offline)
                        if not character_summary:
                            try:
                                import urllib.request
                                import json

                                req_data = json.dumps({
                                    "model": "gemma4-2b",
                                    "messages": [
                                        {"role": "system", "content": summary_prompt},
                                        {"role": "user", "content": clean_text[:1500]},
                                    ],
                                    "max_tokens": 150,
                                }).encode("utf-8")

                                req = urllib.request.Request(
                                    "http://127.0.0.1:9379/v1/chat/completions",
                                    data=req_data,
                                    headers={"Content-Type": "application/json"},
                                )
                                with urllib.request.urlopen(req, timeout=5.0) as resp:
                                    res_json = json.loads(resp.read().decode("utf-8"))
                                    candidate = res_json["choices"][0]["message"]["content"].strip()
                                    if candidate:
                                        character_summary = candidate
                            except Exception as e:
                                logger.error("Character summarization fallback failed: %s", e)

                        if character_summary:
                            character_summary = clean_character_statement(
                                character_summary, first_sentence=first_sentence
                            )

                        if character_summary:
                            if speech_structure == "first_sentence_plus_character":
                                if first_sentence:
                                    fs = first_sentence.strip()
                                    if not fs.endswith((".", "!", "?")):
                                        fs += "."
                                    final_text = f"{fs} {character_summary}".strip()
                                else:
                                    final_text = character_summary
                            elif speech_structure == "character_only":
                                final_text = character_summary
                        else:
                            final_text = (
                                first_sentence
                                if (
                                    speech_structure == "first_sentence_plus_character"
                                    and first_sentence
                                )
                                else clean_text
                            )
                    
                    # Normalize bracketed stage directions (e.g. [giggles] -> [giggle], [sighs] -> [sigh])
                    final_text = normalize_stage_directions(final_text)

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return
                        
                    if not is_live_mode:
                        # Clean bracketed stage directions for standard flash-tts so it sounds natural without reading bracket text
                        clean_flash_text = re.sub(r"\[(?:dramatic\s+)?pause\]", "...", final_text, flags=re.IGNORECASE)
                        clean_flash_text = re.sub(r"\[[a-zA-Z\s_-]+\]", "", clean_flash_text)
                        clean_flash_text = re.sub(r"\s+", " ", clean_flash_text).strip()

                        # Synthesize via gemini-3.8-flash-tts
                        tts_model = getattr(cfg.gemini, "tts_model", "gemini-3.8-flash-tts")
                        url = f"{GEMINI_API_URL}/{tts_model}:generateContent?key={self.api_key}"

                        part_dict: Dict[str, Any] = {"text": clean_flash_text}
                        if character_persona:
                            part_dict["speech_metadata"] = {"style": str(character_persona)}

                        body = {
                            "contents": [{"parts": [part_dict]}],
                            "generationConfig": {
                                "responseModalities": ["AUDIO"],
                                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
                            },
                        }

                        set_agent_audio_playing(True)
                        resp = requests.post(url, json=body, timeout=20.0)
                        if resp.status_code == 200:
                            data = resp.json()
                            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            raw_b64 = parts[0].get("inlineData", {}).get("data", "")
                            if raw_b64:
                                audio_bytes = base64.b64decode(raw_b64)
                                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                                    temp_path = Path(f.name)
                                    temp_path.write_bytes(audio_bytes)

                                try:
                                    if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                                        proc = subprocess.Popen(
                                            ["afplay", str(temp_path)],
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                        )
                                        self._current_process = proc
                                        proc.wait()
                                finally:
                                    temp_path.unlink(missing_ok=True)
                                return

                    # 2. Live API Mode: Stream Audio via WebSockets (gemini-3.8-live)
                    import asyncio
                    from google import genai
                    from google.genai import types
                    
                    client = genai.Client(api_key=self.api_key)
                    sys_parts = []
                    if character_persona:
                        sys_parts.append(
                            types.Part.from_text(
                                text=(
                                    f"You are {character_persona}. Speak this response naturally, expressively, and fully. "
                                    "CRITICAL DIRECTIVE: You MUST read the user's line VERBATIM from the very first word. "
                                    "Do NOT summarize, do NOT skip the first sentence, and do NOT begin with only a reaction. "
                                    "Act out all bracketed stage directions (such as [sigh], [chuckle], [gasp], [pause]) "
                                    "as genuine vocal sounds, breaths, and acoustic actions. "
                                    "NEVER pronounce or speak the words inside brackets."
                                )
                            )
                        )
                        
                    config = types.LiveConnectConfig(
                        response_modalities=["AUDIO"],
                        system_instruction=types.Content(parts=sys_parts) if sys_parts else None,
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                            )
                        ),
                    )
                    
                    async def stream_audio():
                        async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
                            prompt = f"Read this line verbatim: {final_text}"
                            await session.send_realtime_input(text=prompt)
                            
                            set_agent_audio_playing(True)
                            
                            # Using ffplay to stream PCM chunks directly from stdin
                            proc = subprocess.Popen(
                                [
                                    "ffplay",
                                    "-f", "s16le",
                                    "-ar", "24000",
                                    "-ch_layout", "mono",
                                    "-nodisp",
                                    "-autoexit",
                                    "-probesize", "32",
                                    "-sync", "audio",
                                    "-i", "pipe:0",
                                ],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_process = proc
                            
                            async for response in session.receive():
                                if self._stop_requested or is_speech_interrupted(turn_start_time):
                                    try:
                                        proc.terminate()
                                        proc.kill()
                                    except Exception:
                                        pass
                                    break
                                if response.server_content and response.server_content.model_turn:
                                    for part in response.server_content.model_turn.parts:
                                        if part.inline_data and part.inline_data.data:
                                            try:
                                                proc.stdin.write(part.inline_data.data)
                                                proc.stdin.flush()
                                            except Exception:
                                                pass
                                if response.server_content and response.server_content.turn_complete:
                                    break
                                    
                            if proc.stdin:
                                try:
                                    proc.stdin.close()
                                except Exception:
                                    pass
                            proc.wait()
                            
                    asyncio.run(stream_audio())
                    
            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                logger.debug("GeminiTTS stream_speak error: %s", e)
                if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                    self._fallback_to_microsoft_luke(clean_text, turn_start_time=turn_start_time)
            finally:
                set_agent_audio_playing(False)
                self._current_process = None

        if block:
            _run()
        else:
            import threading
            t = threading.Thread(target=_run, daemon=True)
            t.start()
