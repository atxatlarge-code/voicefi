"""
VoiceFi Theatrical Director Engine.
Uses local Gemma 4 (or local model engine / Ollama fallback) on Apple Silicon Metal GPU
to analyze script subtext and inject natural language performance bracket tags, dramatic pauses,
and emotional prosody metadata for local speech actors (Fish Speech S2 Pro, CosyVoice 2, F5-TTS).
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("voicefi.tts.director")

# Canonical theatrical character profiles adapted from Gemini 3.8 Live presets
CANONICAL_PERSONAS: Dict[str, Dict[str, Any]] = {
    "drill_sergeant": {
        "name": "Military Drill Sergeant",
        "description": "Loud, harsh, barking, aggressive cadence, absolute authority, rapid-fire military discipline.",
        "primary_emotion": "aggressive_bark",
        "default_bracket": "[barking with extreme military authority, shouting discipline, rapid aggressive cadence]",
        "speed": 1.15,
        "pitch_shift": "+1st",
        "system_instruction": (
            "You are a theatrical voice director specializing in extreme military drill sergeant performances. "
            "Your job is to take raw script text and annotate it for an expressive speech actor model. "
            "Inject bracket tags like [barking aggressively], [screaming command], [breathless shout], "
            "and dramatic pauses (...) or [pause 200ms]. Capitalize shouted emphasis. Keep exact wording intact."
        ),
    },
    "shakespearean": {
        "name": "Shakespearean Tragedian",
        "description": "Grand classical tragedy, theatrical gravitas, trembling breath, heightened emotional stakes.",
        "primary_emotion": "dramatic_pathos",
        "default_bracket": "[classical stage gravitas, trembling pathos, deep poetic weight, slow deliberate breath]",
        "speed": 0.92,
        "pitch_shift": "-1st",
        "system_instruction": (
            "You are a theatrical voice director specializing in Elizabethan classical tragedy. "
            "Annotate the script with poetic gravitas, trembling breath intakes [shivering breath], [solemn whisper], "
            "[deep tragic resonance], and thoughtful pauses (...). Keep exact wording intact."
        ),
    },
    "game_show_host": {
        "name": "1980s TV Game-Show Host",
        "description": "Booming microphone projection, glossy retro enthusiasm, explosive point reveals, comedic gear shifts.",
        "primary_emotion": "energetic_host",
        "default_bracket": "[booming golden-microphone projection, explosive 1980s game-show enthusiasm]",
        "speed": 1.08,
        "pitch_shift": "+2st",
        "system_instruction": (
            "You are a theatrical voice director for a slick 1980s TV game-show host. "
            "Inject boom mic showmanship [booming with high-voltage enthusiasm], [dramatic game-show pause], "
            "[chuckles smoothly]. Capitalize explosive key phrases. Keep exact wording intact."
        ),
    },
    "conspiratorial_insider": {
        "name": "Conspiratorial Underground Insider",
        "description": "Hushed whisper, conspiratorial vocal fry, urgent secrets whispered in dark alleys.",
        "primary_emotion": "conspiratorial_whisper",
        "default_bracket": "[hushed urgent whisper, conspiratorial vocal fry, glancing over shoulder]",
        "speed": 0.95,
        "pitch_shift": "-2st",
        "system_instruction": (
            "You are a theatrical voice director for an underground hacker whispering forbidden secrets in an alley. "
            "Inject hushed whisper tags [hushed conspiratorial whisper], [urgent vocal fry], [nervous glance pause]. "
            "Keep exact wording intact."
        ),
    },
    "deadpan_ironist": {
        "name": "Deadpan Sarcastic Ironist",
        "description": "Flat monotone smirk, trailing consonants, dismissive chuckle, dry Elizabethan mockery.",
        "primary_emotion": "deadpan_irony",
        "default_bracket": "[deadpan condescension, flat monotone smirk, dry dismissive chuckle]",
        "speed": 0.94,
        "pitch_shift": "0st",
        "system_instruction": (
            "You are a theatrical voice director for a weary, sarcastic systems engineer. "
            "Inject deadpan irony tags [dry condescending chuckle], [weary sigh], [flat sarcastic smirk], "
            "and trailing ellipses (...). Keep exact wording intact."
        ),
    },
    "documentary_broadcaster": {
        "name": "BBC Nature Documentary Broadcaster",
        "description": "Intimate, contemplative, British RP wonder, slow dramatic pauses, chest warmth.",
        "primary_emotion": "contemplative_wonder",
        "default_bracket": "[intimate contemplative whisper, deep chest warmth, hushed British RP wonder]",
        "speed": 0.88,
        "pitch_shift": "-2st",
        "system_instruction": (
            "You are a theatrical voice director for a legendary BBC natural history documentary broadcaster. "
            "Replace exclamation marks with contemplative ellipses (...). Inject [intimate hushed wonder], "
            "[slow breath pause], [hushed awe]. Never rush."
        ),
    },
    "christopher_walken": {
        "name": "Christopher Walken",
        "description": "Idiosyncratic staccato rhythm, unexpected dramatic pauses, sudden pitch spikes, deadpan comedic intensity.",
        "primary_emotion": "walken_cadence",
        "default_bracket": "[unpredictable staccato rhythm, sudden mid-sentence pauses, eccentric emphasis, deadpan intensity]",
        "speed": 0.88,
        "pitch_shift": "-1st",
        "system_instruction": (
            "You are a theatrical voice director specializing in Christopher Walken's iconic speech cadence. "
            "Annotate the script with erratic dramatic pauses (...), unexpected mid-sentence pauses, "
            "eccentric emphasis on random words, and staccato cadence. Keep exact underlying words intact."
        ),
    },
    "walken": {
        "name": "Christopher Walken",
        "description": "Idiosyncratic staccato rhythm, unexpected dramatic pauses, sudden pitch spikes, deadpan comedic intensity.",
        "primary_emotion": "walken_cadence",
        "default_bracket": "[unpredictable staccato rhythm, sudden mid-sentence pauses, eccentric emphasis, deadpan intensity]",
        "speed": 0.88,
        "pitch_shift": "-1st",
        "system_instruction": (
            "You are a theatrical voice director specializing in Christopher Walken's iconic speech cadence. "
            "Annotate the script with erratic dramatic pauses (...), unexpected mid-sentence pauses, "
            "eccentric emphasis on random words, and staccato cadence. Keep exact underlying words intact."
        ),
    },
}


@dataclass
class DirectedPerformance:
    raw_text: str
    directed_text: str
    character_key: str
    primary_emotion: str
    speed: float
    pitch_shift: str
    bracket_tags: List[str]
    director_model: str
    duration_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TheatricalDirector:
    """
    On-device director engine that converts flat script lines into rich,
    affective speech directives for local models (Fish Speech, CosyVoice, F5-TTS).
    """

    def __init__(self, model_name: str = "gemma4-2b", backend: str = "gpu"):
        self.model_name = model_name
        self.backend = backend
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from voicefi.local.engine import LocalModelEngine
            self._engine = LocalModelEngine(model_name=self.model_name, backend=self.backend)
        return self._engine

    def direct_rule_based(self, text: str, persona_key: str) -> DirectedPerformance:
        """
        Ultra-fast (<1ms) heuristic director fallback if local LLM is cold or busy.
        Directly wraps lines with canonical theatrical brackets and prosody punctuation.
        """
        persona = CANONICAL_PERSONAS.get(persona_key.lower(), CANONICAL_PERSONAS["deadpan_ironist"])
        bracket = persona["default_bracket"]
        speed = persona.get("speed", 1.0)
        pitch = persona.get("pitch_shift", "0st")
        emotion = persona.get("primary_emotion", "neutral")

        cleaned = text.strip()
        # Clean markdown headers or asterisks
        cleaned = re.sub(r"^[#*`\-_—\s]+", "", cleaned).strip()

        if persona_key == "documentary_broadcaster":
            # Documentary secret: strip exclamation marks and insert ellipses
            cleaned = cleaned.replace("!", ".")
            directed_text = f"{bracket} {cleaned}"
        elif persona_key == "drill_sergeant":
            directed_text = f"{bracket} {cleaned.upper()}"
        elif persona_key in ("christopher_walken", "walken"):
            directed_text = f"{bracket} {self.direct_walken_cadence(cleaned)}"
        else:
            directed_text = f"{bracket} {cleaned}"

        tags = re.findall(r"\[(.*?)\]", directed_text)
        return DirectedPerformance(
            raw_text=text,
            directed_text=directed_text,
            character_key=persona_key,
            primary_emotion=emotion,
            speed=speed,
            pitch_shift=pitch,
            bracket_tags=tags,
            director_model="rule-based-heuristic",
        )

    @staticmethod
    def direct_walken_cadence(
        text: str, archetype: str = "standard", include_prefix: bool = False
    ) -> str:
        """
        Transforms flat text into Christopher Walken's unmistakable staccato acting cadence:
        unexpected mid-clause dramatic ellipses, pauses before key verbs, and rhythmic punch.
        Supports 'standard' (erratic staccato) and 'continental' (suave velvet robe, champagne rasp).
        When include_prefix is False (default), starts directly with the sentence without forced
        intro catchphrases ("Listen...", "Look...", "Guess what?...", "Mmm... beautiful...").
        """
        if not text or not text.strip():
            return ""
        s = text.strip()
        s = re.sub(r"^[#*`\-_—\s]+", "", s).strip()
        s = re.sub(r'["\']', '', s)

        # Strip any existing forced intro catchphrases when include_prefix is False
        if not include_prefix:
            prefix_pattern = re.compile(
                r'^(?:listen|look|guess what|mmm(?:\.\.\.|\s*beautiful)*|oh\s+my|wow\.\.\.\s*look\s+at\s+you[\.\s]*champagne\?*)\s*(?:[\.\,\!\?\:\;—\-]+|\.{2,})\s*',
                flags=re.IGNORECASE,
            )
            s = prefix_pattern.sub('', s).strip()
            if s and s[0].islower():
                s = s[0].upper() + s[1:]

        clauses = re.split(r'[,;—–]|\s-\s', s)
        processed_clauses = []
        for c in clauses:
            c = c.strip()
            if not c:
                continue
            words = c.split()
            if len(words) >= 5:
                mid = len(words) // 2
                w_first = " ".join(words[:mid])
                w_second = " ".join(words[mid:])
                c = f"{w_first}... {w_second}"
            processed_clauses.append(c)

        walkenized = "... ".join(processed_clauses)

        if include_prefix:
            arch = str(archetype).lower().strip()
            if arch in ("continental", "the_continental", "the continental"):
                if not any(
                    walkenized.lower().startswith(p)
                    for p in ("wow", "champagne", "mmm", "look at you", "does it get", "look", "listen")
                ):
                    if "error" in s.lower() or "fail" in s.lower():
                        walkenized = f"Oh my... {walkenized}"
                    elif any(
                        k in s.lower()
                        for k in ("success", "pass", "done", "complete", "ready", "built", "clean", "fixed")
                    ):
                        walkenized = f"Wow... look at you. Champagne?... {walkenized}"
                    else:
                        walkenized = f"Mmm... beautiful... {walkenized}"
            else:
                if not any(walkenized.lower().startswith(p) for p in ("look", "listen", "you see", "guess what")):
                    if "error" in s.lower() or "fail" in s.lower():
                        walkenized = f"Look... {walkenized}"
                    elif any(k in s.lower() for k in ("success", "pass", "done", "complete", "ready", "built")):
                        walkenized = f"Guess what?... {walkenized}"
                    else:
                        walkenized = f"Listen... {walkenized}"

        if not walkenized.endswith((".", "!", "?")):
            walkenized += "."

        return walkenized

    async def direct_performance(
        self,
        text: str,
        persona_key: str = "deadpan_ironist",
        custom_instructions: Optional[str] = None,
        use_llm: bool = True,
    ) -> DirectedPerformance:
        """
        Direct a performance line using local Gemma 4 on Metal GPU (falling back to rule-based).
        """
        import time
        start_t = time.perf_counter()

        persona = CANONICAL_PERSONAS.get(persona_key.lower())
        if not persona:
            # Fallback to closest match or generic
            persona = CANONICAL_PERSONAS["deadpan_ironist"]

        if not use_llm:
            res = self.direct_rule_based(text, persona_key)
            res.duration_sec = time.perf_counter() - start_t
            return res

        system_instruction = custom_instructions or persona["system_instruction"]
        prompt = (
            f"Character: {persona['name']}\n"
            f"Vocal Tone: {persona['description']}\n\n"
            f"Raw Script Line:\n\"{text.strip()}\"\n\n"
            "Produce the directed version for the speech model. "
            "Wrap performance instructions in square brackets [like this] and insert dramatic ellipses (...) for pauses. "
            "Do NOT alter the underlying spoken words. Output ONLY the directed text line."
        )

        # Attempt query via warm local model server or LocalModelEngine
        directed_line = ""
        engine_name = self.model_name
        try:
            # Check if litert-lm server or ollama is reachable
            import urllib.request
            ollama_url = "http://127.0.0.1:11434/api/generate"
            litert_url = "http://127.0.0.1:9379/v1/chat/completions"

            # 1. Try warm LiteRT HTTP server
            req = urllib.request.Request(
                litert_url,
                data=json.dumps({
                    "model": self.model_name,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 256,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=1.5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    directed_line = data["choices"][0]["message"]["content"].strip()
                    engine_name = f"litert-lm-{self.model_name}"
            except Exception:
                pass

            # 2. Try Ollama (e.g. gemma2:2b / llama3.2) if LiteRT HTTP wasn't up
            if not directed_line:
                req_ollama = urllib.request.Request(
                    ollama_url,
                    data=json.dumps({
                        "model": "gemma2:2b",
                        "prompt": f"{system_instruction}\n\n{prompt}",
                        "stream": False,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req_ollama, timeout=2.5) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        directed_line = res_data.get("response", "").strip()
                        engine_name = "ollama-gemma2:2b"
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Directing via HTTP server failed: {e}")

        # Fallback to rule-based if network/server failed
        if not directed_line:
            res = self.direct_rule_based(text, persona_key)
            res.duration_sec = time.perf_counter() - start_t
            return res

        # Strip any extraneous quotes wrapping the output
        directed_line = re.sub(r'^["\']|["\']$', "", directed_line).strip()
        tags = re.findall(r"\[(.*?)\]", directed_line)

        # Dynamic emotion & prosody classification via Ollama structured outputs
        dynamic_prosody = self.classify_emotion_prosody(text)
        detected_emotion = dynamic_prosody.get("emotion") or persona.get("primary_emotion", "neutral")
        detected_speed = float(dynamic_prosody.get("speed") or persona.get("speed", 1.0))
        detected_pitch = dynamic_prosody.get("pitch_shift") or persona.get("pitch_shift", "0st")

        return DirectedPerformance(
            raw_text=text,
            directed_text=directed_line,
            character_key=persona_key,
            primary_emotion=detected_emotion,
            speed=detected_speed,
            pitch_shift=detected_pitch,
            bracket_tags=tags,
            director_model=engine_name,
            duration_sec=time.perf_counter() - start_t,
        )

    @classmethod
    def classify_emotion_prosody(cls, text: str) -> Dict[str, Any]:
        """
        Classifies emotional prosody and pitch/speed adjustments using local Ollama structured output.
        """
        import urllib.request
        import json

        system_prompt = (
            "You are VoiceFi's real-time acoustic theatrical director. "
            "Analyze the response text and select the most appropriate emotional prosody tone and style.\n"
            "Emotions:\n"
            "- cheerful: upbeat, optimistic, friendly greetings, successful outcomes.\n"
            "- serious: critical alerts, architectural decisions, security warnings.\n"
            "- apologetic: acknowledging errors, failures, timeouts, apologies.\n"
            "- excited: major accomplishments, breakthrough milestones, celebrations.\n"
            "- deadpan: sarcastic remarks, dry technical statements, matter-of-fact observations."
        )

        payload = {
            "model": "gemma2:2b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Text to speak: {text}"}
            ],
            "format": {
                "type": "object",
                "properties": {
                    "emotion": {
                        "type": "string",
                        "enum": ["cheerful", "serious", "apologetic", "excited", "deadpan"]
                    },
                    "pitch_shift": {
                        "type": "string",
                        "enum": ["-2st", "-1st", "0st", "+1st", "+2st"]
                    },
                    "speed": {
                        "type": "number",
                        "description": "Recommended speaking rate multiplier (e.g. 0.9 to 1.2)"
                    }
                },
                "required": ["emotion", "pitch_shift", "speed"]
            },
            "stream": False,
            "options": {"temperature": 0.0}
        }

        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                res = json.loads(resp.read().decode())
                return json.loads(res["message"]["content"])
        except Exception:
            return {}
