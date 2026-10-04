"""
voicefi/factory/generator.py
Local AI Script & Dialogue Generator for Content Creation Factory.
Powered by on-device Gemma 4 (LiteRT on Apple Silicon Metal GPU) & MLX specialists.
Generates declarative reel manifests in 1-3 seconds with zero cloud latency and $0 token cost.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from voicefi.factory.models import ContentJob, ContentManifest, ScriptDialogueTurn

logger = logging.getLogger("voicefi.factory.generator")

# Local Inference Endpoints
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
LITERT_ENDPOINTS = [
    OLLAMA_ENDPOINT,
    os.environ.get("LITERT_BASE_URL", "http://127.0.0.1:9380/v1"),
    "http://127.0.0.1:9379/v1",
    "http://127.0.0.1:8085/v1",
]

PREFERRED_CREATIVE_MODELS = [
    "gemma2:2b",
    "llama3.2:1b",
    "qwen2.5-coder:1.5b",
    "tev1:latest",
    "dolphin-llama3:latest",
    "nimble:latest",
]

DEFAULT_CHARACTERS = {
    "Viv": {"voice_id": "en-US-AvaNeural", "tag_color": "#3186FF", "role": "Google Antigravity Planner", "speed": "-2%"},
    "Stefan": {"voice_id": "en-US-SteffanNeural", "tag_color": "#D97757", "role": "Claude Code Architect", "speed": "0%"},
    "Christopher": {"voice_id": "en-US-ChristopherNeural", "tag_color": "#00E5FF", "role": "Cursor Engineer", "speed": "+2%"},
    "Jake": {"voice_id": "en-US-AndrewNeural", "tag_color": "#10B981", "role": "VoiceFi Founder", "speed": "-3%"},
}


def discover_ollama_model(base_url: str = OLLAMA_ENDPOINT) -> Optional[str]:
    """Query local Ollama to find the best available model for scriptwriting."""
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", headers={"User-Agent": "VoiceFi"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                installed = [m.get("name", "") for m in data.get("models", [])]
                for pref in PREFERRED_CREATIVE_MODELS:
                    if pref in installed:
                        return pref
                if installed:
                    return installed[0]
    except Exception as e:
        logger.debug(f"Ollama discovery skipped ({e})")
    return None


class LocalContentGenerator:
    """Generates structured conversational scripts using local on-device models."""

    def __init__(self, preferred_endpoint: Optional[str] = None):
        self.endpoints = [preferred_endpoint] if preferred_endpoint else LITERT_ENDPOINTS
        self._discovered_ollama_model: Optional[str] = None

    def _query_local_llm(self, prompt: str, system_prompt: str) -> Optional[str]:
        """Attempt to query local model: first Ollama with JSON mode, then in-process LiteRT, then standard endpoints."""
        # 0. Hardware Guardrail check
        try:
            from voicefi.local.supervisor import default_supervisor
            default_supervisor.wait_if_throttled(poll_interval=2.0, max_wait=10.0)
        except Exception:
            pass

        # 1. Native Ollama with JSON mode
        if not self._discovered_ollama_model:
            self._discovered_ollama_model = discover_ollama_model()

        if self._discovered_ollama_model:
            ollama_url = f"{OLLAMA_ENDPOINT.rstrip('/')}/api/chat"
            payload = {
                "model": self._discovered_ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 600,
                },
            }
            try:
                req = urllib.request.Request(
                    ollama_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        msg = res_json.get("message", {}).get("content", "")
                        if msg:
                            logger.info(f"Generated script via Ollama model '{self._discovered_ollama_model}'")
                            return msg
            except Exception as e:
                logger.debug(f"Ollama native generation failed: {e}")

        # 2. Direct in-process LiteRT engine on Apple Silicon Metal GPU
        try:
            from voicefi.local import LocalModelEngine
            engine = LocalModelEngine(model_name="gemma4-2b")
            if not engine.model_exists:
                engine = LocalModelEngine()
            if engine.is_installed and engine.model_exists:
                import asyncio
                coro = engine.chat_text(prompt=prompt, system_instructions=system_prompt)
                try:
                    res = asyncio.run(coro)
                    if res and res.strip():
                        return res.strip()
                except Exception as ex:
                    coro.close()
                    logger.debug(f"Direct LocalModelEngine inference notice: {ex}")
        except Exception:
            pass

        # 3. Standard OpenAI-compatible HTTP endpoints
        payload = {
            "model": self._discovered_ollama_model or "gemma2:2b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1200,
        }
        data = json.dumps(payload).encode("utf-8")

        for endpoint in self.endpoints:
            url = f"{endpoint.rstrip('/')}/chat/completions"
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        choices = res_json.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
            except Exception as e:
                logger.debug(f"Local LLM endpoint {url} unreachable or error: {e}")
                continue
        return None

    def generate_manifest(self, job: ContentJob) -> Tuple[ContentManifest, int, float]:
        """
        Generates ContentManifest for the job.
        Returns: (manifest, tokens_saved, elapsed_seconds)
        """
        start_time = time.time()
        system_prompt = (
            "You are an elite reel scriptwriter for tech shorts and viral engineering reels. "
            "Output strictly a JSON object with keys 'title' (string) and 'turns' (list of objects with "
            "'speaker', 'text', 'emotion', 'speed'). Keep total word count around 50-90 words for punchy 30s delivery."
        )
        user_prompt = (
            f"Write a dialogue reel about: {job.prompt}\n"
            f"Characters available: {', '.join(job.characters)}\n"
            f"Target duration: {job.target_duration_s} seconds.\n"
            f"Return ONLY valid JSON."
        )

        content_raw = self._query_local_llm(user_prompt, system_prompt)
        tokens_saved = 0

        if content_raw:
            # Parse JSON from model output
            manifest = self._parse_json_to_manifest(content_raw, job)
            tokens_saved = len(user_prompt.split()) + len(content_raw.split()) + 400
        else:
            # High-speed deterministic fallback generator
            manifest = self._generate_fallback_manifest(job)
            tokens_saved = 350

        elapsed = time.time() - start_time
        return manifest, tokens_saved, elapsed

    def _parse_json_to_manifest(self, raw_text: str, job: ContentJob) -> ContentManifest:
        # Extract JSON substring
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                turns_data = data.get("turns", [])
                turns = []
                total_words = 0
                for td in turns_data:
                    spk = td.get("speaker", "Viv")
                    txt = td.get("text", "")
                    total_words += len(txt.split())
                    char_info = DEFAULT_CHARACTERS.get(spk, {})
                    turns.append(
                        ScriptDialogueTurn(
                            speaker=spk,
                            text=txt,
                            emotion=td.get("emotion", "neutral"),
                            voice_id=char_info.get("voice_id", "en-US-AvaNeural"),
                            speed=td.get("speed", char_info.get("speed", "-2%")),
                        )
                    )
                # Word-budget duration estimate (approx 2.5 words/sec at conversational speed)
                calc_dur = round(total_words / 2.5 + (len(turns) * 0.4), 2)
                return ContentManifest(
                    title=data.get("title", job.title or "Generated Reel"),
                    content_type=job.content_type,
                    target_duration_s=job.target_duration_s,
                    turns=turns,
                    total_words=total_words,
                    calculated_duration_s=calc_dur,
                )
            except Exception as e:
                logger.warning(f"Failed parsing local model JSON: {e}. Using structured fallback.")

        return self._generate_fallback_manifest(job)

    def _generate_fallback_manifest(self, job: ContentJob) -> ContentManifest:
        chars = job.characters if job.characters else ["Viv", "Stefan"]
        char1 = chars[0]
        char2 = chars[1] if len(chars) > 1 else "Stefan"

        c1_info = DEFAULT_CHARACTERS.get(char1, {"voice_id": "en-US-AvaNeural", "speed": "-2%"})
        c2_info = DEFAULT_CHARACTERS.get(char2, {"voice_id": "en-US-SteffanNeural", "speed": "0%"})

        turns = [
            ScriptDialogueTurn(
                speaker=char1,
                text=f"Did you see the latest update for {job.prompt}?",
                emotion="curious",
                voice_id=c1_info.get("voice_id"),
                speed=c1_info.get("speed"),
                pause_after_ms=200,
            ),
            ScriptDialogueTurn(
                speaker=char2,
                text="Yeah, running this through the factory queue cut our turnaround from hours down to seconds.",
                emotion="confident",
                voice_id=c2_info.get("voice_id"),
                speed=c2_info.get("speed"),
                pause_after_ms=250,
            ),
            ScriptDialogueTurn(
                speaker=char1,
                text="Zero cloud API roundtrips. Everything stays local on Apple Silicon.",
                emotion="excited",
                voice_id=c1_info.get("voice_id"),
                speed=c1_info.get("speed"),
                pause_after_ms=300,
            ),
            ScriptDialogueTurn(
                speaker=char2,
                text="Exactly. That's the power of the autonomous factory pattern.",
                emotion="satisfied",
                voice_id=c2_info.get("voice_id"),
                speed=c2_info.get("speed"),
                pause_after_ms=400,
            ),
        ]
        total_words = sum(len(t.text.split()) for t in turns)
        calc_dur = round(total_words / 2.5 + (len(turns) * 0.4), 2)

        return ContentManifest(
            title=job.title or f"Reel: {job.prompt[:30]}",
            content_type=job.content_type,
            target_duration_s=job.target_duration_s,
            turns=turns,
            total_words=total_words,
            calculated_duration_s=calc_dur,
        )
