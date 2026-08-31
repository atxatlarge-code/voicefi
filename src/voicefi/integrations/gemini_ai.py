"""
Google Gemini Intelligence Engine for VoiceFi.
Provides LLM-assisted turn summarization, structured voice memo synthesis,
and phonetic code disambiguation via Gemini 2.5/2.0 Flash with zero-latency fallback.
"""

import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Optional
import requests

from voicefi.config import VoiceFiConfig, load_config

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiIntelligenceEngine:
    """
    Client for Google Gemini Flash intelligence tasks in VoiceFi.
    Resilient design: silently falls back if offline, unconfigured, or rate-limited.
    """

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        self.config = config or load_config()
        self._api_key = self._resolve_api_key()
        self.model = (
            getattr(self.config.gemini, "model", "gemini-2.5-flash")
            if hasattr(self.config, "gemini")
            else "gemini-2.5-flash"
        )
        self.temperature = (
            getattr(self.config.gemini, "temperature", 0.2)
            if hasattr(self.config, "gemini")
            else 0.2
        )

    def _resolve_api_key(self) -> str:
        """Resolve API key from VoiceFi config or standard environment variables."""
        if hasattr(self.config, "gemini") and self.config.gemini.api_key:
            return self.config.gemini.api_key.strip()
        if hasattr(self.config, "tts") and getattr(self.config.tts, "gemini_api_key", None):
            return self.config.tts.gemini_api_key.strip()
        for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            val = os.environ.get(env_var, "").strip()
            if val:
                return val
        return ""

    def is_available(self) -> bool:
        """Check if Gemini intelligence is configured and enabled."""
        if not self._api_key:
            return False
        if hasattr(self.config, "gemini") and not self.config.gemini.enabled:
            return False
        return True

    def get_api_key(self) -> str:
        """Return resolved API key."""
        return self._api_key

    def _call_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: int = 250,
        temperature: Optional[float] = None,
        timeout: float = 1.0,
    ) -> Optional[str]:
        """Execute a low-latency text completion request to Gemini REST API."""
        if not self.is_available():
            return None

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self._api_key}"
        headers = {"Content-Type": "application/json"}

        contents = [{"parts": [{"text": prompt}]}]
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature if temperature is not None else self.temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
            else:
                logger.debug(
                    "Gemini API non-200 response [%s]: %s", resp.status_code, resp.text[:200]
                )
        except Exception as e:
            logger.debug("Gemini API request exception: %s", e)

        return None

    def distill_spoken_soundbite(
        self,
        agent_output: str,
        max_words: int = 40,
        timeout: float = 0.8,
    ) -> Optional[str]:
        """
        Condense long agent terminal / markdown output into a punchy 1-2 sentence spoken soundbite.
        Prioritizes completion status, key changes, or trailing questions.
        """
        if not self.is_available() or not agent_output or not agent_output.strip():
            return None

        # Truncate input if excessively massive to guarantee sub-second latency
        bounded_text = agent_output
        if len(bounded_text) > 3000:
            bounded_text = bounded_text[:1000] + "\n...\n" + bounded_text[-1500:]

        system_prompt = (
            "You are VoiceFi's spoken voice synthesizer for AI coding agents. "
            "Your job is to read the agent's output and condense it into a single, punchy, spoken sentence (under 30 words). "
            "Do NOT include markdown, asterisks, backticks, emojis, or code snippets. "
            "If the agent asked the developer a question or is waiting for confirmation, end with that clear question. "
            "Speak directly to the developer (e.g. 'I refactored the auth middleware and all 14 unit tests are passing.')."
        )

        prompt = f"Agent Output:\n{bounded_text}\n\nSpoken soundbite:"
        result = self._call_gemini(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=80,
            temperature=0.1,
            timeout=timeout,
        )

        if result:
            # Clean any stray formatting or quotes
            clean = re.sub(r"^[\"']|[\"']$", "", result.strip())
            clean = re.sub(r"[`*#_]", "", clean)
            words = clean.split()
            if len(words) > max_words:
                clean = " ".join(words[:max_words]) + "."
            return clean

        return None

    def structure_voice_memo(
        self,
        raw_transcript: str,
        timeout: float = 3.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Synthesize a raw spoken brain dump into structured architecture decisions and tasks.
        """
        if not self.is_available() or not raw_transcript or not raw_transcript.strip():
            return None

        system_prompt = (
            "You are an expert software architect analyzing a developer's voice memo brain dump. "
            "Extract the core technical vision into structured JSON with these exact keys: "
            "'title' (short punchy title, 3-6 words), "
            "'summary' (2-3 sentence overview), "
            "'decisions' (list of key architectural decisions), "
            "'action_items' (list of concrete implementation steps). "
            "Output ONLY valid JSON."
        )

        prompt = f"Developer Voice Memo Transcript:\n{raw_transcript}\n\nJSON Output:"
        result = self._call_gemini(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=600,
            temperature=0.2,
            timeout=timeout,
        )

        if result:
            try:
                # Strip json markdown code blocks if present
                clean_json = re.sub(r"^```json\s*", "", result.strip(), flags=re.IGNORECASE)
                clean_json = re.sub(r"```$", "", clean_json.strip())
                data = json.loads(clean_json)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.debug("Failed to parse Gemini voice memo JSON: %s", e)

        return None

    def resolve_phonetic_code(
        self,
        spoken_phrase: str,
        candidate_symbols: List[str],
        timeout: float = 1.0,
    ) -> Optional[str]:
        """
        Disambiguate ambiguous spoken words into exact repository symbols.
        """
        if not self.is_available() or not spoken_phrase or not candidate_symbols:
            return None

        system_prompt = (
            "You are a developer speech-to-text normalizer. "
            "Given a spoken developer phrase and a list of candidate codebase symbols/files, "
            "return the exact matching symbol or filename. Output ONLY the matching symbol string."
        )

        candidates_str = ", ".join(candidate_symbols[:30])
        prompt = f"Spoken phrase: '{spoken_phrase}'\nCandidate symbols: [{candidates_str}]\nBest matching symbol:"

        result = self._call_gemini(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=30,
            temperature=0.0,
            timeout=timeout,
        )

        if result:
            symbol = result.strip().strip("'\"`")
            if symbol in candidate_symbols:
                return symbol

        return None
