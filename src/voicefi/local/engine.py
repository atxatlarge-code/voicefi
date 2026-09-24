"""
VoiceFi Local Model Engine.
Manages the lifecycle of on-device LiteRT models and provides a high-level
interface to Google Antigravity SDK's LiteRTAgentConfig.
"""

import os
import sys
import json
import logging
import platform
import re
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("voicefi.local.engine")


def is_litert_available() -> bool:
    """Check if LiteRT and Google Antigravity SDK are available in the Python environment."""
    try:
        import litert_lm  # noqa: F401
        from google.antigravity import LiteRTAgentConfig  # noqa: F401

        return True
    except (ImportError, ModuleNotFoundError):
        return False


def detect_hardware_backend() -> Tuple[str, str]:
    """
    Detect the optimal hardware backend for the current host.
    Returns: (backend_code, human_readable_description)
    """
    system = platform.system()
    machine = platform.machine()

    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return ("gpu", "Apple Silicon Metal GPU (Metal 4)")
    elif system == "Linux":
        # Check for CUDA
        if os.path.exists("/proc/driver/nvidia/version") or os.environ.get("CUDA_VISIBLE_DEVICES"):
            return ("gpu", "NVIDIA CUDA GPU")
        return ("cpu", "CPU (Host x86_64/ARM)")
    elif system == "Windows":
        return ("gpu", "DirectX/CUDA GPU")
    return ("cpu", "CPU Fallback")


def get_default_models_dir() -> Path:
    """Return the default storage directory for LiteRT models."""
    return Path(os.path.expanduser("~/.litert-lm/models"))


def list_imported_models() -> List[Dict[str, Any]]:
    """List all models currently imported into ~/.litert-lm/models."""
    models_dir = get_default_models_dir()
    if not models_dir.exists():
        return []

    results = []
    try:
        for entry in models_dir.iterdir():
            if entry.is_dir():
                model_file = entry / "model.litertlm"
                if not model_file.exists():
                    # Check for any .litertlm file
                    litertlm_files = list(entry.glob("*.litertlm"))
                    model_file = litertlm_files[0] if litertlm_files else None

                if model_file and model_file.exists():
                    stat = model_file.stat()
                    results.append(
                        {
                            "name": entry.name,
                            "path": str(model_file.resolve()),
                            "size_bytes": stat.st_size,
                            "size_mb": round(stat.st_size / (1024 * 1024), 1),
                            "size_gb": round(stat.st_size / (1024 * 1024 * 1024), 2),
                            "modified_at": stat.st_mtime,
                        }
                    )
    except Exception as e:
        logger.warning(f"Error scanning LiteRT models directory: {e}")

    return sorted(results, key=lambda x: x["name"])


class LocalModelEngine:
    """
    On-device execution engine for Gemma and open-weights models
    powered by Google AI Edge LiteRT and the Google Antigravity SDK.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_name: str = "gemma4-26b",
        backend: Optional[str] = None,
        max_context_tokens: int = 65536,
        enable_speculative_decoding: bool = True,
        system_instructions: Optional[str] = None,
    ):
        if not model_path:
            target_path = os.path.expanduser(f"~/.litert-lm/models/{model_name}/model.litertlm")
            if not os.path.exists(target_path):
                imported = list_imported_models()
                if imported:
                    target_path = imported[0]["path"]
                    model_name = imported[0]["name"]
            self.model_path = target_path
            self.model_name = model_name
        else:
            self.model_path = os.path.expanduser(model_path)
            self.model_name = model_name
        detected_backend, _ = detect_hardware_backend()
        self.backend = backend or detected_backend
        self.max_context_tokens = max_context_tokens
        self.enable_speculative_decoding = enable_speculative_decoding
        self.system_instructions = system_instructions

    @property
    def is_installed(self) -> bool:
        return is_litert_available()

    @property
    def model_exists(self) -> bool:
        return os.path.exists(self.model_path)

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of the local model engine."""
        backend_code, backend_desc = detect_hardware_backend()
        model_file = Path(self.model_path)
        size_gb = 0.0
        if model_file.exists():
            size_gb = round(model_file.stat().st_size / (1024 * 1024 * 1024), 2)

        return {
            "litert_available": self.is_installed,
            "backend": self.backend,
            "backend_desc": backend_desc,
            "model_name": self.model_name,
            "model_path": self.model_path,
            "model_exists": self.model_exists,
            "model_size_gb": size_gb,
            "max_context_tokens": self.max_context_tokens,
            "speculative_decoding": self.enable_speculative_decoding,
            "imported_models": list_imported_models(),
        }

    def build_agent_config(
        self,
        tools: Optional[List[Any]] = None,
        system_instructions: Optional[str] = None,
        capabilities: Optional[Any] = None,
    ) -> Any:
        """
        Build a LiteRTAgentConfig instance for use with google.antigravity.Agent.
        """
        if not self.is_installed:
            raise RuntimeError(
                "LiteRT or Google Antigravity SDK is not installed. "
                "Run `uv pip install google-antigravity litert-lm` or `pip install voicefi[local]`."
            )

        from google.antigravity import LiteRTAgentConfig

        si = system_instructions or self.system_instructions

        kwargs: Dict[str, Any] = {
            "model_path": self.model_path,
            "backend": self.backend,
            "enable_speculative_decoding": self.enable_speculative_decoding,
        }

        if si:
            kwargs["system_instructions"] = si
        if tools is not None:
            kwargs["tools"] = tools
        else:
            kwargs["tools"] = []
        if capabilities:
            kwargs["capabilities"] = capabilities

        return LiteRTAgentConfig(**kwargs)

    async def chat_stream(
        self,
        prompt: str,
        system_instructions: Optional[str] = None,
        tools: Optional[List[Any]] = None,
    ) -> AsyncIterator[str]:
        """
        Stream tokens directly from the local LiteRT model.
        """
        from google.antigravity import Agent

        config = self.build_agent_config(
            tools=tools,
            system_instructions=system_instructions,
        )

        async with Agent(config=config) as agent:
            response = await agent.chat(prompt)
            async for token in response:
                yield token

    async def chat_text(
        self,
        prompt: str,
        system_instructions: Optional[str] = None,
        tools: Optional[List[Any]] = None,
    ) -> str:
        """
        Execute a prompt on the local model and return the full completed response text.
        """
        tokens = []
        async for token in self.chat_stream(
            prompt=prompt,
            system_instructions=system_instructions,
            tools=tools,
        ):
            tokens.append(token)
        return "".join(tokens)

    async def distill_turn(
        self,
        agent_output: str,
        max_words: int = 24,
        telegraphic: bool = False,
        measure: bool = True,
    ) -> Tuple[str, Optional[Any]]:
        """
        Distill agent turn output into a punchy spoken soundbite or telegraphic summary.
        Measures TTFB and throughput and appends to ~/.voicefi/benchmarks.json if measure=True.
        """
        import time
        from voicefi.local.benchmark import record_inference_metrics

        if not agent_output or not agent_output.strip():
            return "", None

        # Truncate overly long context for sub-second turn distillation
        bounded = agent_output.strip()
        if len(bounded) > 3000:
            bounded = bounded[:1000] + "\n...\n" + bounded[-1500:]

        if telegraphic:
            system_prompt = (
                "You are VoiceFi's Telegraphic Speed-Talking Distiller. "
                f"Condense the agent's output into an ultra-dense, telegraphic spoken soundbite under {max_words} words. "
                "Cut all conversational filler, greetings, pleasantries, and markdown. "
                "Deliver pure signal, key metrics, and completion outcomes."
            )
            test_name = "Telegraphic Distillation"
        else:
            system_prompt = (
                "You are VoiceFi's spoken voice synthesizer for AI coding agents. "
                f"Condense the agent's output into a single punchy spoken sentence under {max_words} words. "
                "Do NOT include markdown, asterisks, backticks, emojis, bullet points, or raw code blocks. "
                "Speak directly to the developer (e.g. 'I refactored the auth middleware and all tests pass.')."
            )
            test_name = "Spoken Turn Distillation"

        prompt = f"Agent Output:\n{bounded}\n\nSpoken soundbite:"

        start_time = time.perf_counter()
        first_token_time = None
        tokens = []

        try:
            async for token in self.chat_stream(
                prompt=prompt,
                system_instructions=system_prompt,
                tools=[],
            ):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                tokens.append(token)
        except Exception as e:
            logger.warning(f"Local distill_turn execution error: {e}")
            return "", None

        total_time = max(0.001, time.perf_counter() - start_time)
        ttfb = (first_token_time - start_time) if first_token_time else total_time
        ttfb_ms = ttfb * 1000.0

        raw_result = "".join(tokens).strip()
        clean = re.sub(r"^[\"']|[\"']$", "", raw_result)
        clean = re.sub(r"[`*#_]", "", clean)
        clean = " ".join(clean.split()).strip()
        words = clean.split()
        if len(words) > max_words:
            clean = " ".join(words[:max_words]) + "."

        prompt_tokens = max(1, len(prompt) // 4)
        output_tokens = max(1, len(tokens))
        gen_time = max(0.001, total_time - ttfb)
        tok_per_sec = output_tokens / gen_time

        bench_res = None
        if measure:
            _, backend_desc = detect_hardware_backend()
            bench_res = record_inference_metrics(
                test_name=test_name,
                target_engine=f"Local ({self.model_name})",
                backend_desc=backend_desc,
                ttfb_ms=ttfb_ms,
                total_seconds=total_time,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                tok_per_sec=tok_per_sec,
                cost_usd=0.0,
                notes=f"{len(words)} words spoken soundbite",
            )

        return clean, bench_res

    async def classify_intent(
        self,
        prompt: str,
        measure: bool = True,
    ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """
        Classify a spoken prompt into target destinations:
        - local_command (battery, git branch/status, time, pause, stop)
        - antigravity (IDE, multi-file code editing, architecture)
        - claude (terminal CLI, shell scripts)
        - codex (ChatGPT / Codex desktop prompt)
        - obsidian (notes, daily journal entry, bookmarks)
        - memo (private voice memo / brain dump)
        """
        import time
        from voicefi.local.benchmark import record_inference_metrics

        system_prompt = (
            "You are VoiceFi's on-device intent classifier for AI coding agents and macOS desktop actions. "
            "Analyze the developer's spoken prompt and classify the intended routing target into JSON with two keys: "
            "'target': exactly one of ['local_command', 'antigravity', 'claude', 'codex', 'obsidian', 'memo'], "
            "'action': a concise summary or specific command to run. "
            "Categories:\n"
            "- 'local_command': questions about battery, time, git branch, git status, system volume, pause/stop audio.\n"
            "- 'antigravity': general code editing, file changes, project refactoring, IDE commands.\n"
            "- 'claude': CLI commands, terminal scripts, running bash pipelines.\n"
            "- 'codex': ChatGPT / Codex desktop assistance.\n"
            "- 'obsidian': notes, thoughts to save to daily journal, wiki entries.\n"
            "- 'memo': long voice brain dumps or stream-of-consciousness.\n"
            "Output ONLY valid JSON."
        )

        user_msg = f"Developer Spoken Prompt: {prompt}\n\nJSON Output:"

        start_time = time.perf_counter()
        first_token_time = None
        tokens = []

        try:
            async for token in self.chat_stream(
                prompt=user_msg,
                system_instructions=system_prompt,
                tools=[],
            ):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                tokens.append(token)
        except Exception as e:
            logger.warning(f"Local classify_intent execution error: {e}")

        total_time = max(0.001, time.perf_counter() - start_time)
        ttfb = (first_token_time - start_time) if first_token_time else total_time
        ttfb_ms = ttfb * 1000.0

        raw_result = "".join(tokens).strip()
        parsed = {}
        try:
            clean_json = re.sub(r"^```json\s*", "", raw_result, flags=re.IGNORECASE)
            clean_json = re.sub(r"```$", "", clean_json.strip())
            parsed = json.loads(clean_json)
        except Exception:
            # Fallback heuristic
            target = "antigravity"
            low = prompt.lower()
            if any(
                w in low for w in ("battery", "time", "branch", "volume", "pause", "stop audio")
            ):
                target = "local_command"
            elif "claude" in low:
                target = "claude"
            elif "codex" in low or "chatgpt" in low:
                target = "codex"
            elif "obsidian" in low or "note" in low or "journal" in low:
                target = "obsidian"
            elif "memo" in low:
                target = "memo"
            parsed = {"target": target, "action": prompt}

        prompt_tokens = max(1, len(user_msg) // 4)
        output_tokens = max(1, len(tokens))
        gen_time = max(0.001, total_time - ttfb)
        tok_per_sec = output_tokens / gen_time

        bench_res = None
        if measure:
            _, backend_desc = detect_hardware_backend()
            bench_res = record_inference_metrics(
                test_name="Intent Routing",
                target_engine=f"Local ({self.model_name})",
                backend_desc=backend_desc,
                ttfb_ms=ttfb_ms,
                total_seconds=total_time,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                tok_per_sec=tok_per_sec,
                cost_usd=0.0,
                notes=f"Target: {parsed.get('target', 'unknown')}",
            )

        return parsed, bench_res

    async def structure_memo(
        self,
        raw_transcript: str,
        measure: bool = True,
    ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """
        Synthesize a raw spoken brain dump into structured architecture decisions and tasks.
        """
        import time
        from voicefi.local.benchmark import record_inference_metrics

        system_prompt = (
            "You are an expert software architect analyzing a developer's voice memo brain dump. "
            "Extract the core technical vision into structured JSON with these exact keys: "
            "'title' (short punchy title, 3-6 words), "
            "'summary' (2-3 sentence overview), "
            "'decisions' (list of key architectural decisions), "
            "'action_items' (list of concrete implementation steps). "
            "Output ONLY valid JSON."
        )

        user_msg = f"Developer Voice Memo Transcript:\n{raw_transcript}\n\nJSON Output:"

        start_time = time.perf_counter()
        first_token_time = None
        tokens = []

        try:
            async for token in self.chat_stream(
                prompt=user_msg,
                system_instructions=system_prompt,
                tools=[],
            ):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                tokens.append(token)
        except Exception as e:
            logger.warning(f"Local structure_memo execution error: {e}")

        total_time = max(0.001, time.perf_counter() - start_time)
        ttfb = (first_token_time - start_time) if first_token_time else total_time
        ttfb_ms = ttfb * 1000.0

        raw_result = "".join(tokens).strip()
        parsed = {}
        try:
            clean_json = re.sub(r"^```json\s*", "", raw_result, flags=re.IGNORECASE)
            clean_json = re.sub(r"```$", "", clean_json.strip())
            parsed = json.loads(clean_json)
        except Exception:
            parsed = {
                "title": "Voice Memo",
                "summary": raw_transcript[:200],
                "decisions": [],
                "action_items": [],
            }

        prompt_tokens = max(1, len(user_msg) // 4)
        output_tokens = max(1, len(tokens))
        gen_time = max(0.001, total_time - ttfb)
        tok_per_sec = output_tokens / gen_time

        bench_res = None
        if measure:
            _, backend_desc = detect_hardware_backend()
            bench_res = record_inference_metrics(
                test_name="Air-Gapped Memo Scribing",
                target_engine=f"Local ({self.model_name})",
                backend_desc=backend_desc,
                ttfb_ms=ttfb_ms,
                total_seconds=total_time,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                tok_per_sec=tok_per_sec,
                cost_usd=0.0,
                notes=f"Title: {parsed.get('title', 'Voice Memo')}",
            )

        return parsed, bench_res
