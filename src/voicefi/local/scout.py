"""
VoiceFi Recon Scout Engine.
Pre-digests massive files, logs, and stack traces on-device using local Gemma 4
to eliminate context bloat, accelerate comprehension, and save thousands of cloud tokens.
"""

import os
import time
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from voicefi.local.engine import LocalModelEngine, is_litert_available

logger = logging.getLogger("voicefi.local.scout")


@dataclass
class ScoutResult:
    target: str
    query: str
    findings: str
    input_tokens_est: int
    output_tokens: int
    tokens_saved: int
    savings_pct: float
    duration_seconds: float
    model_name: str
    is_local: bool
    read_latency_ms: float = 0.0
    ingress_mode: str = "unified_ram"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """Rough estimation of token count (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class ReconScout:
    """
    On-device scout that reads large local files/logs and extracts concise,
    actionable insights for Antigravity and Claude Code.
    """

    DEFAULT_SCOUT_INSTRUCTIONS = (
        "You are the VoiceFi Recon Scout. You run on-device to pre-digest raw files, logs, and code.\n"
        "Your mission is to find the exact root cause, key symbols, or answers requested.\n"
        "Be extremely concise, technical, and precise. Avoid fluff. Include relevant line numbers and code snippets."
    )

    def __init__(self, engine: Optional[LocalModelEngine] = None):
        self.engine = engine or LocalModelEngine()

    def read_target_content(
        self,
        target_path: Union[str, Path],
        max_bytes: int = 500_000,
    ) -> tuple[str, int, bool]:
        """Read target file content safely up to max_bytes."""
        path = Path(os.path.expanduser(str(target_path)))
        if not path.exists():
            raise FileNotFoundError(f"Target path does not exist: {path}")

        if path.is_file():
            size = path.stat().st_size
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            truncated = size > max_bytes
            return content, size, truncated
        elif path.is_dir():
            # Summarize directory structure and text files
            content_parts = [f"Directory listing for: {path}"]
            total_size = 0
            file_count = 0
            for root, dirs, files in os.walk(path):
                # Ignore git and venv dirs
                dirs[:] = [
                    d for d in dirs if d not in (".git", ".venv", "__pycache__", "node_modules")
                ]
                for file in files[:30]:  # Cap at 30 files
                    fp = Path(root) / file
                    try:
                        sz = fp.stat().st_size
                        total_size += sz
                        file_count += 1
                        content_parts.append(f" - {fp.relative_to(path)} ({sz} bytes)")
                    except Exception:
                        pass
            return "\n".join(content_parts), total_size, False
        else:
            raise ValueError(f"Unsupported path type: {path}")

    async def scout(
        self,
        target_path: Union[str, Path],
        query: str = "Analyze this file, identify any errors or anomalies, and extract key functions/logic.",
        max_bytes: int = 500_000,
    ) -> ScoutResult:
        """
        Execute an on-device scout run on the target file/directory.
        """
        start_time = time.perf_counter()

        read_start = time.perf_counter()
        try:
            raw_content, file_size, truncated = self.read_target_content(
                target_path, max_bytes=max_bytes
            )
            read_latency_ms = round((time.perf_counter() - read_start) * 1000.0, 3)
        except Exception as e:
            duration = time.perf_counter() - start_time
            return ScoutResult(
                target=str(target_path),
                query=query,
                findings="",
                input_tokens_est=0,
                output_tokens=0,
                tokens_saved=0,
                savings_pct=0.0,
                duration_seconds=round(duration, 3),
                model_name=self.engine.model_name,
                is_local=False,
                read_latency_ms=0.0,
                error=str(e),
            )

        input_tokens = estimate_tokens(raw_content)

        # Formulate prompt
        truncation_note = " [Content truncated to 500KB]" if truncated else ""
        resolved_path = Path(os.path.expanduser(str(target_path))).resolve()
        prompt = (
            f"Objective: {query}\n\n"
            f"Target: {resolved_path}{truncation_note} ({file_size} bytes, ~{input_tokens} tokens)\n\n"
            f"```\n{raw_content}\n```\n\n"
            "Provide: 1) One-line Diagnosis/Summary, 2) Key Functions/Lines, 3) Actionable Fix or Findings."
        )

        # If local model weights are present and LiteRT is ready, execute on-device
        if self.engine.is_installed and self.engine.model_exists:
            try:
                findings = await self.engine.chat_text(
                    prompt=prompt,
                    system_instructions=self.DEFAULT_SCOUT_INSTRUCTIONS,
                    tools=[],
                )
                output_tokens = estimate_tokens(findings)
                tokens_saved = max(0, input_tokens - output_tokens)
                savings_pct = round((tokens_saved / max(1, input_tokens)) * 100, 1)
                duration = time.perf_counter() - start_time

                return ScoutResult(
                    target=str(target_path),
                    query=query,
                    findings=findings,
                    input_tokens_est=input_tokens,
                    output_tokens=output_tokens,
                    tokens_saved=tokens_saved,
                    savings_pct=savings_pct,
                    duration_seconds=round(duration, 2),
                    model_name=self.engine.model_name,
                    is_local=True,
                    read_latency_ms=read_latency_ms,
                    ingress_mode="unified_ram",
                )
            except Exception as e:
                logger.warning(
                    f"Local scout execution error: {e}. Falling back to heuristic extraction."
                )

        # Fallback / Fast Rule-Based Scout (if model checkpoint not yet downloaded)
        duration = time.perf_counter() - start_time
        simulated_findings = self._heuristic_extract(raw_content, str(target_path), query)
        output_tokens = estimate_tokens(simulated_findings)
        tokens_saved = max(0, input_tokens - output_tokens)
        savings_pct = round((tokens_saved / max(1, input_tokens)) * 100, 1)

        note = ""
        if not self.engine.model_exists:
            note = f" (Heuristic mode: model weights not found at {self.engine.model_path})"

        return ScoutResult(
            target=str(target_path),
            query=query,
            findings=simulated_findings + note,
            input_tokens_est=input_tokens,
            output_tokens=output_tokens,
            tokens_saved=tokens_saved,
            savings_pct=savings_pct,
            duration_seconds=round(duration, 3),
            model_name=f"{self.engine.model_name} [heuristic]",
            is_local=False,
            read_latency_ms=read_latency_ms,
            ingress_mode="unified_ram",
        )

    def _heuristic_extract(self, content: str, path: str, query: str) -> str:
        """Fast regex/keyword extractor for logs and code when model weights are not loaded."""
        lines = content.splitlines()
        errors = []
        for i, line in enumerate(lines[:1000]):
            low = line.lower()
            if any(
                k in low for k in ("error", "exception", "traceback", "fail", "critical", "panic")
            ):
                errors.append(f"Line {i + 1}: {line.strip()[:140]}")
                if len(errors) >= 8:
                    break

        if errors:
            return (
                f"### Recon Diagnosis for `{Path(path).name}`\n"
                f"- Found {len(errors)} anomalous lines/stack traces:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )
        else:
            return (
                f"### Recon Summary for `{Path(path).name}`\n"
                f"- Scanned {len(lines)} lines ({len(content)} characters).\n"
                f"- No critical errors or unhandled exceptions detected in the scanned portion.\n"
                f"- Ready for task: {query}"
            )
