"""
VoiceFi Recon Implementer Engine.
Executes an on-device 2-tier cascade (Gemma 4 2B Scout -> Gemma 4 26B Coder)
to surgically modify code and output clean unified diffs, saving >90% of cloud tokens.
"""

import os
import re
import time
import difflib
import logging
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from voicefi.local.engine import LocalModelEngine, is_litert_available
from voicefi.local.scout import ReconScout, estimate_tokens

logger = logging.getLogger("voicefi.local.implementer")

LOCAL_SERVER_URL = "http://127.0.0.1:9379/v1/chat/completions"


@dataclass
class ImplementResult:
    target_path: str
    instruction: str
    diff: str
    applied: bool
    scout_duration: float
    coder_duration: float
    total_duration: float
    tokens_saved: int
    savings_pct: float
    input_tokens_est: int
    diff_tokens_est: int
    model_scout: str
    model_coder: str
    scout_findings: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def apply_search_replace(content: str, search: str, replace: str) -> Tuple[str, bool]:
    """Apply a SEARCH/REPLACE block to text content."""
    # Normalize line endings
    search_clean = search.replace("\r\n", "\n")
    content_clean = content.replace("\r\n", "\n")

    if search_clean in content_clean:
        return content_clean.replace(search_clean, replace.replace("\r\n", "\n"), 1), True

    # Fallback: strip leading/trailing blank lines in search block
    search_stripped = search_clean.strip("\n")
    if search_stripped and search_stripped in content_clean:
        return content_clean.replace(
            search_stripped, replace.replace("\r\n", "\n").strip("\n"), 1
        ), True

    # Fallback: line-by-line whitespace-tolerant match
    search_lines = [l.strip() for l in search_clean.splitlines() if l.strip()]
    content_lines = content_clean.splitlines()
    for i in range(len(content_lines) - len(search_lines) + 1):
        window = [content_lines[i + j].strip() for j in range(len(search_lines))]
        if window == search_lines:
            # Found match
            new_lines = (
                content_lines[:i]
                + replace.replace("\r\n", "\n").splitlines()
                + content_lines[i + len(search_lines) :]
            )
            return "\n".join(new_lines), True

    return content, False


def parse_search_replace_blocks(text: str) -> List[Tuple[str, str]]:
    """Parse <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE blocks."""
    pattern = re.compile(r"<<<<<<<\s*SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE", re.DOTALL)
    blocks = []
    for match in pattern.finditer(text):
        blocks.append((match.group(1), match.group(2)))
    return blocks


async def query_model(
    model_name: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """
    Query local model via warm litert-lm HTTP server if available,
    falling back to direct LocalModelEngine.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # Query dedicated warm local HTTP servers (9379 for 2b, 9380 for 26b)
    if model_name in ("gemma4-2b", "gemma4-26b"):
        server_url = (
            "http://127.0.0.1:9380/v1/chat/completions"
            if model_name == "gemma4-26b"
            else "http://127.0.0.1:9379/v1/chat/completions"
        )
        try:
            req = urllib.request.Request(
                server_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"].get("content", "")
        except Exception as e:
            logger.debug(
                f"HTTP litert-lm server query failed ({e}), falling back to direct engine."
            )

    # For larger coder models (gemma4-26b) or if HTTP server is unavailable, run direct in-process LocalModelEngine
    engine = LocalModelEngine(model_name=model_name)
    return await engine.chat_text(prompt=prompt, system_instructions=system_prompt)


class ReconImplementer:
    """
    On-device 2-tier implementation pipeline:
    - Tier 1: Gemma 4 2B extracts the target slice and line coordinates.
    - Tier 2: Gemma 4 26B generates the precise code edit.
    - Applies the edit locally and outputs only the clean unified git diff.
    """

    DEFAULT_SCOUT_PROMPT = (
        "You are the VoiceFi Recon Scout. Your job is to locate the exact functions, "
        "classes, or lines in the provided code that need to be modified for the user's task.\n"
        "Return ONLY the relevant code slice with line context, plus a 1-sentence note of what needs editing. "
        "Do NOT write the implementation yourself."
    )

    DEFAULT_CODER_PROMPT = (
        "You are an expert systems programmer. Implement the requested code changes accurately.\n"
        "Format your output strictly using one or more SEARCH/REPLACE blocks like this:\n\n"
        "<<<<<<< SEARCH\n"
        "[exact lines from the original file to replace]\n"
        "=======\n"
        "[new replacement lines]\n"
        ">>>>>>> REPLACE\n\n"
        "Maintain identical indentation and coding conventions. Avoid unnecessary conversational fluff."
    )

    def __init__(
        self,
        model_scout: str = "gemma4-2b",
        model_coder: str = "gemma4-26b",
    ):
        self.model_scout = model_scout
        self.model_coder = model_coder

    async def implement(
        self,
        target_path: Union[str, Path],
        instruction: str,
        apply: bool = True,
        diff_only: bool = True,
        max_file_bytes: int = 500_000,
    ) -> ImplementResult:
        """
        Execute full on-device scout -> implement -> diff workflow.
        """
        start_total = time.perf_counter()
        path = Path(os.path.expanduser(str(target_path))).resolve()

        if not path.exists() or not path.is_file():
            return ImplementResult(
                target_path=str(path),
                instruction=instruction,
                diff="",
                applied=False,
                scout_duration=0.0,
                coder_duration=0.0,
                total_duration=0.0,
                tokens_saved=0,
                savings_pct=0.0,
                input_tokens_est=0,
                diff_tokens_est=0,
                model_scout=self.model_scout,
                model_coder=self.model_coder,
                error=f"File not found: {path}",
            )

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            original_content = f.read(max_file_bytes)

        input_tokens = estimate_tokens(original_content)
        lines = original_content.splitlines()
        total_lines = len(lines)

        # -------------------------------------------------------------
        # Phase 1: Scout (Gemma 4 2B) for files > 80 lines
        # -------------------------------------------------------------
        scout_start = time.perf_counter()
        scout_slice = original_content
        scout_findings = ""

        if total_lines > 80:
            scout_query = (
                f"Task: {instruction}\n\n"
                f"File: {path.name} ({total_lines} lines)\n\n"
                f"```\n{original_content}\n```\n\n"
                "Identify the exact section or lines to edit for this task."
            )
            try:
                scout_findings = await query_model(
                    model_name=self.model_scout,
                    prompt=scout_query,
                    system_prompt=self.DEFAULT_SCOUT_PROMPT,
                    max_tokens=1024,
                )
                scout_slice = scout_findings
            except Exception as e:
                logger.warning(f"Scout tier failed ({e}), using full file for coder tier.")
                scout_slice = original_content

        scout_duration = round(time.perf_counter() - scout_start, 3)

        # -------------------------------------------------------------
        # Phase 2: Coder (Gemma 4 26B)
        # -------------------------------------------------------------
        coder_start = time.perf_counter()
        coder_prompt = (
            f"File: {path.name}\n"
            f"Task: {instruction}\n\n"
            f"Relevant Context / Scout Findings:\n"
            f"```\n{scout_slice}\n```\n\n"
            f"Original File Content:\n"
            f"```\n{original_content}\n```\n\n"
            "Produce the exact SEARCH/REPLACE block(s) to achieve this task."
        )

        try:
            coder_output = await query_model(
                model_name=self.model_coder,
                prompt=coder_prompt,
                system_prompt=self.DEFAULT_CODER_PROMPT,
                max_tokens=3000,
            )
        except Exception as e:
            return ImplementResult(
                target_path=str(path),
                instruction=instruction,
                diff="",
                applied=False,
                scout_duration=scout_duration,
                coder_duration=0.0,
                total_duration=round(time.perf_counter() - start_total, 3),
                tokens_saved=0,
                savings_pct=0.0,
                input_tokens_est=input_tokens,
                diff_tokens_est=0,
                model_scout=self.model_scout,
                model_coder=self.model_coder,
                scout_findings=scout_findings,
                error=f"Coder tier execution failed: {e}",
            )

        coder_duration = round(time.perf_counter() - coder_start, 3)

        # -------------------------------------------------------------
        # Phase 3: Apply Changes & Generate Unified Diff
        # -------------------------------------------------------------
        blocks = parse_search_replace_blocks(coder_output)
        updated_content = original_content
        applied_any = False

        if blocks:
            for search_chunk, replace_chunk in blocks:
                updated_content, matched = apply_search_replace(
                    updated_content, search_chunk, replace_chunk
                )
                if matched:
                    applied_any = True
        else:
            # If coder output was a raw markdown block matching the code
            code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", coder_output, re.DOTALL)
            if code_blocks and len(code_blocks) == 1 and len(code_blocks[0].strip()) > 10:
                # If coder returned replacement snippet
                pass

        # Generate unified diff
        diff_lines = list(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                updated_content.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )
        diff_text = "".join(diff_lines)

        # If git repo exists, run git diff if applied to disk
        if apply and applied_any and diff_text.strip():
            # Backup original
            bak_path = path.with_suffix(f"{path.suffix}.vifi_bak")
            try:
                with open(bak_path, "w", encoding="utf-8") as f:
                    f.write(original_content)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(updated_content)
            except Exception as e:
                logger.error(f"Failed to write file {path}: {e}")

        diff_tokens = estimate_tokens(diff_text)
        tokens_saved = max(0, input_tokens - diff_tokens)
        savings_pct = round((tokens_saved / max(1, input_tokens)) * 100, 1)
        total_duration = round(time.perf_counter() - start_total, 3)

        return ImplementResult(
            target_path=str(path),
            instruction=instruction,
            diff=diff_text if diff_text.strip() else coder_output,
            applied=applied_any if apply else False,
            scout_duration=scout_duration,
            coder_duration=coder_duration,
            total_duration=total_duration,
            tokens_saved=tokens_saved,
            savings_pct=savings_pct,
            input_tokens_est=input_tokens,
            diff_tokens_est=diff_tokens,
            model_scout=self.model_scout,
            model_coder=self.model_coder,
            scout_findings=scout_findings,
            error=None
            if applied_any
            else "No matching SEARCH/REPLACE blocks could be applied automatically.",
        )
