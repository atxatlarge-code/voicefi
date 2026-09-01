"""
Google Gemini & Local Intelligence Engine for VoiceFi.
Provides LLM-assisted turn summarization, structured voice memo synthesis,
phonetic code disambiguation, and proactive intent triage via Gemini 2.5/2.0 Flash
or local zero-cost models (Ollama / Llama.cpp) with instant heuristic fallback.
"""

import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Optional, Tuple
import requests

from voicefi.config import VoiceFiConfig, load_config

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiIntelligenceEngine:
    """
    Client for Google Gemini Flash and Local LLM (Ollama) intelligence tasks in VoiceFi.
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
        self.provider_setting = (
            getattr(self.config.gemini, "provider", "auto")
            if hasattr(self.config, "gemini")
            else "auto"
        )
        self.local_llm_url = (
            getattr(self.config.gemini, "local_llm_url", "http://localhost:11434/v1")
            if hasattr(self.config, "gemini")
            else "http://localhost:11434/v1"
        )
        self.local_llm_model = (
            getattr(self.config.gemini, "local_llm_model", "qwen2.5:0.5b")
            if hasattr(self.config, "gemini")
            else "qwen2.5:0.5b"
        )
        self.enable_auto_learning = (
            getattr(self.config.gemini, "enable_auto_learning", True)
            if hasattr(self.config, "gemini")
            else True
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

    def get_active_provider(self) -> str:
        """
        Determine which provider to route to: 'gemini', 'ollama', or 'heuristic'.
        """
        if hasattr(self.config, "gemini") and not self.config.gemini.enabled:
            return "heuristic"

        if self.provider_setting == "heuristic":
            return "heuristic"
        elif self.provider_setting == "gemini":
            return "gemini" if bool(self._api_key) else "heuristic"
        elif self.provider_setting == "ollama":
            return "ollama"

        # Auto mode: prefer Gemini if API key is present, otherwise check Ollama
        if self._api_key:
            return "gemini"

        # Check if local Ollama endpoint is reachable
        if self._is_local_endpoint_alive():
            return "ollama"

        return "heuristic"

    def _is_local_endpoint_alive(self) -> bool:
        """Quick probe to check if local Ollama / OpenAI endpoint is running."""
        try:
            url = self.local_llm_url.rstrip("/")
            test_url = f"{url}/models" if url.endswith("/v1") else url
            resp = requests.get(test_url, timeout=0.15)
            return resp.status_code in (200, 401, 403, 404)
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check if Gemini or Local LLM intelligence is configured and enabled."""
        if hasattr(self.config, "gemini") and not self.config.gemini.enabled:
            return False
        return self.get_active_provider() in ("gemini", "ollama")

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
        if not self._api_key:
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

    def _call_local_llm(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: int = 250,
        temperature: Optional[float] = None,
        timeout: float = 1.0,
    ) -> Optional[str]:
        """Execute a low-latency text completion request to local Ollama / OpenAI-compatible endpoint."""
        url = self.local_llm_url.rstrip("/")
        endpoint = f"{url}/chat/completions" if not url.endswith("/chat/completions") else url
        headers = {"Content-Type": "application/json"}

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": self.local_llm_model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": False,
        }

        try:
            resp = requests.post(endpoint, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")
                    if content:
                        return content.strip()
            else:
                logger.debug(
                    "Local LLM non-200 response [%s]: %s", resp.status_code, resp.text[:200]
                )
        except Exception as e:
            logger.debug("Local LLM request exception: %s", e)

        return None

    def generate_completion(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: int = 250,
        temperature: Optional[float] = None,
        timeout: float = 0.8,
    ) -> Optional[str]:
        """Unified text completion router across Gemini and Local LLM with fallback."""
        provider = self.get_active_provider()
        if provider == "gemini":
            result = self._call_gemini(
                prompt=prompt,
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            if result:
                return result
            # Secondary fallback to local LLM if available
            if self._is_local_endpoint_alive():
                return self._call_local_llm(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
        elif provider == "ollama":
            return self._call_local_llm(
                prompt=prompt,
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                timeout=timeout,
            )

        return None

    def distill_spoken_soundbite(
        self,
        agent_output: str,
        max_words: Optional[int] = None,
        timeout: float = 0.8,
        fallback_to_heuristics: bool = False,
    ) -> Optional[str]:
        """
        Condense long agent terminal / markdown output into a punchy spoken soundbite.
        Dynamically adapts word budget based on BrevityLearner cognitive memory.
        Prioritizes completion status, key outcomes, or trailing confirmation questions.
        """
        if not agent_output or not agent_output.strip():
            return None

        # Dynamically query BrevityLearner if max_words not explicitly pinned
        effective_max_words = max_words
        if effective_max_words is None or effective_max_words <= 0:
            try:
                from voicefi.learning.brevity import BrevityLearner

                effective_max_words = BrevityLearner.get_instance().get_optimal_max_words()
            except Exception:
                effective_max_words = 24

        # Truncate input if excessively massive to guarantee sub-second latency
        bounded_text = agent_output.strip()
        if len(bounded_text) > 3000:
            bounded_text = bounded_text[:1000] + "\n...\n" + bounded_text[-1500:]

        system_prompt = (
            "You are VoiceFi's spoken voice synthesizer for AI coding agents. "
            f"Your job is to read the agent's output and condense it into a single punchy spoken sentence (under {effective_max_words} words). "
            "Do NOT include markdown, asterisks, backticks, emojis, bullet points, or raw code blocks. "
            "If the agent asked the developer a question or is waiting for confirmation, end with that clear question. "
            "Speak directly to the developer (e.g. 'I refactored the auth middleware and all 14 unit tests are passing.')."
        )

        prompt = f"Agent Output:\n{bounded_text}\n\nSpoken soundbite:"
        result = self.generate_completion(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=effective_max_words * 3,
            temperature=0.1,
            timeout=timeout,
        )

        if result:
            # Clean any stray formatting or quotes
            clean = re.sub(r"^[\"']|[\"']$", "", result.strip())
            clean = re.sub(r"[`*#_]", "", clean)
            clean = " ".join(clean.split()).strip()
            words = clean.split()
            if len(words) > effective_max_words:
                clean = " ".join(words[:effective_max_words]) + "."
            return clean

        if fallback_to_heuristics:
            try:
                from voicefi.integrations.antigravity import clean_markdown_for_speech

                return clean_markdown_for_speech(agent_output, max_words=effective_max_words)
            except Exception:
                pass

        return None

    def structure_voice_memo(
        self,
        raw_transcript: str,
        timeout: float = 3.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Synthesize a raw spoken brain dump into structured architecture decisions and tasks.
        """
        if not raw_transcript or not raw_transcript.strip():
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
        result = self.generate_completion(
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
                logger.debug("Failed to parse voice memo JSON: %s", e)

        return None

    def resolve_phonetic_code(
        self,
        spoken_phrase: str,
        candidate_symbols: List[str],
        timeout: float = 0.8,
    ) -> Optional[str]:
        """
        Disambiguate ambiguous spoken words into exact repository symbols.
        Auto-persists newly resolved rules to PhoneticLearner memory.
        """
        if not spoken_phrase or not candidate_symbols:
            return None

        system_prompt = (
            "You are a developer speech-to-text normalizer. "
            "Given a spoken developer phrase and a list of candidate codebase symbols/files, "
            "return the exact matching symbol or filename. Output ONLY the matching symbol string, with no quotes or extra text."
        )

        candidates_str = ", ".join(candidate_symbols[:35])
        prompt = f"Spoken phrase: '{spoken_phrase}'\nCandidate symbols: [{candidates_str}]\nBest matching symbol:"

        result = self.generate_completion(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=30,
            temperature=0.0,
            timeout=timeout,
        )

        if result:
            symbol = result.strip().strip("'\"`")
            for cand in candidate_symbols:
                if cand.lower() == symbol.lower():
                    # Auto-persist to phonetic self-learning memory for future 0ms lookups
                    if self.enable_auto_learning:
                        try:
                            from voicefi.learning.phonetic import PhoneticLearner

                            PhoneticLearner.get_instance().record_correction(
                                spoken_phrase, cand, confidence=0.9
                            )
                        except Exception:
                            pass
                    return cand

        return None

    def classify_spoken_intent(
        self,
        spoken_text: str,
        timeout: float = 0.6,
    ) -> Optional[Dict[str, Any]]:
        """
        Classify conversational speech into structured routing intents.
        Returns dict with 'target' ('antigravity', 'claude', 'linear', 'slack'), 'prompt', and 'confidence'.
        """
        if not spoken_text or not spoken_text.strip():
            return None

        system_prompt = (
            "You are a developer intent classifier for a voice layer. "
            "Classify the spoken developer request into structured JSON with keys: "
            "'target' ('antigravity', 'claude', 'linear', 'slack', or 'general'), "
            "'prompt' (the clean instruction to send to that tool/agent), "
            "'confidence' (0.0 to 1.0). "
            "Output ONLY valid JSON."
        )

        prompt = f"Developer utterance: '{spoken_text}'\nJSON Intent:"
        result = self.generate_completion(
            prompt=prompt,
            system_instruction=system_prompt,
            max_output_tokens=150,
            temperature=0.0,
            timeout=timeout,
        )

        if result:
            try:
                clean_json = re.sub(r"^```json\s*", "", result.strip(), flags=re.IGNORECASE)
                clean_json = re.sub(r"```$", "", clean_json.strip())
                data = json.loads(clean_json)
                if isinstance(data, dict) and "target" in data:
                    return data
            except Exception:
                pass

        return None

    def test_connection(self) -> Dict[str, Any]:
        """
        Benchmark latency and connection health to active intelligence provider.
        """
        start = time.time()
        provider = self.get_active_provider()

        if provider == "heuristic":
            return {
                "provider": "heuristic",
                "status": "active",
                "latency_ms": 0.1,
                "model": "deterministic_regex",
                "message": "Local regex & heuristic extractor active (0ms, 0 API cost)",
            }

        test_prompt = "Reply with 'ready'."
        res = self.generate_completion(
            prompt=test_prompt,
            system_instruction="You are a health checker. Reply with 'ready'.",
            max_output_tokens=10,
            timeout=2.0,
        )
        elapsed_ms = round((time.time() - start) * 1000, 1)

        if res:
            model_name = self.model if provider == "gemini" else self.local_llm_model
            return {
                "provider": provider,
                "status": "connected",
                "latency_ms": elapsed_ms,
                "model": model_name,
                "sample_response": res,
                "message": f"Successfully connected to {provider} ({model_name}) in {elapsed_ms}ms",
            }

        return {
            "provider": provider,
            "status": "error",
            "latency_ms": elapsed_ms,
            "model": self.model if provider == "gemini" else self.local_llm_model,
            "message": f"Could not reach {provider} endpoint. Falling back to local heuristics.",
        }
