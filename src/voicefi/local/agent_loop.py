"""
VoiceFi Local Autonomous Agent Loop.
Executes multi-turn tool-calling loops completely on-device using local models
(Gemma 4 26B/2B, Qwen 2.5 Coder, Llama 3.3 70B on Metal GPU) with zero cloud roundtrips.
"""

import os
import sys
import re
import time
import json
import logging
import subprocess
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union

from voicefi.local.symbols import LocalSymbolIndex, SymbolRecord
from voicefi.local.implementer import apply_search_replace, parse_search_replace_blocks

logger = logging.getLogger("voicefi.local.agent_loop")


@dataclass
class LoopStep:
    turn: int
    thought: str
    tool: str
    arguments: Dict[str, Any]
    observation: str
    duration: float


@dataclass
class AutonomousLoopResult:
    goal: str
    completed: bool
    summary: str
    steps: List[LoopStep]
    modified_files: List[str]
    total_duration: float
    model: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "completed": self.completed,
            "summary": self.summary,
            "total_duration": self.total_duration,
            "model": self.model,
            "modified_files": self.modified_files,
            "error": self.error,
            "steps": [
                {
                    "turn": s.turn,
                    "thought": s.thought,
                    "tool": s.tool,
                    "arguments": s.arguments,
                    "observation": s.observation[:300] + "..." if len(s.observation) > 300 else s.observation,
                    "duration": s.duration,
                }
                for s in self.steps
            ],
        }


class LocalAutonomousLoop:
    """
    On-device agent loop orchestrating local models and system tools.
    """

    SYSTEM_PROMPT = (
        "You are the VoiceFi Autonomous Local Engineering Agent running directly on Apple Silicon Metal GPU.\n"
        "Your goal is to inspect code, execute surgical refactors, verify with tests, and resolve issues locally.\n\n"
        "You have access to the following local tools:\n"
        "1. read_slice(path: str, start_line: int, end_line: int) -> view specific lines of a file\n"
        "2. find_symbol(name: str) -> look up class, function, or method definitions in the SQLite AST index\n"
        "3. search_code(query: str, path: str = '.') -> search for text/regex across files\n"
        "4. apply_diff(path: str, search: str, replace: str) -> apply exact SEARCH/REPLACE block to a file\n"
        "5. run_command(command: str) -> execute a shell/test command (e.g. pytest, git status)\n"
        "6. finish(summary: str) -> declare the task completed\n\n"
        "Strategy:\n"
        "- ALWAYS use read_slice or find_symbol first to inspect the real code lines and exact variable names before applying diffs. Never guess.\n"
        "- In apply_diff, provide complete lines in 'search' (including exact leading indentation, e.g. '    return price - discount_percent'), and complete lines in 'replace'. Never replace just a function name.\n"
        "- Use run_command to run test suites and verify your changes before finishing.\n"
        "- Once tests pass, call finish(summary='...').\n\n"
        "Output Format:\n"
        "Respond with a brief THOUGHT followed by a single tool call formatted as JSON:\n"
        "THOUGHT: [Reasoning for next action]\n"
        "```json\n"
        "{\"tool\": \"[tool_name]\", \"arguments\": {[args]}}\n"
        "```\n"
        "Do not include conversational preamble."
    )

    def __init__(
        self,
        model_name: str = "qwen2.5-coder:1.5b",
        max_turns: int = 5,
        repo_root: Optional[Union[str, Path]] = None,
    ):
        self.model_name = model_name
        self.max_turns = max_turns
        self.repo_root = Path(repo_root or ".").resolve()
        self.symbol_index = LocalSymbolIndex()
        # Ensure symbols are indexed
        try:
            self.symbol_index.index_repo(self.repo_root)
        except Exception:
            pass

    async def execute(self, goal: str, context: Optional[str] = None) -> AutonomousLoopResult:
        """Run the autonomous local loop until finish() or max_turns."""
        start_time = time.perf_counter()
        steps: List[LoopStep] = []
        modified_files: List[str] = []
        conversation_history: List[Dict[str, str]] = []

        # Pre-seed relevant AST symbols from goal if matched
        words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", goal))
        symbol_hints = []
        for w in words:
            records = self.symbol_index.find_symbol(w, root_dir=self.repo_root, auto_refresh=False)
            for r in records[:2]:
                symbol_hints.append(f"• `{r.name}` ({r.kind}) in `{r.file_path}` (lines {r.start_line}-{r.end_line})")

        initial_user_msg = f"GOAL: {goal}"
        if symbol_hints:
            initial_user_msg += f"\n\nKNOWN AST SYMBOLS:\n" + "\n".join(symbol_hints)
        if context:
            initial_user_msg += f"\n\nCONTEXT:\n{context}"

        conversation_history.append({"role": "user", "content": initial_user_msg})

        completed = False
        final_summary = ""

        for turn in range(1, self.max_turns + 1):
            turn_start = time.perf_counter()

            # Query local model
            model_resp = await self._query_model(conversation_history)
            if not model_resp:
                steps.append(
                    LoopStep(
                        turn=turn,
                        thought="Local model did not produce an output.",
                        tool="error",
                        arguments={},
                        observation="Empty model response",
                        duration=round(time.perf_counter() - turn_start, 3),
                    )
                )
                break

            tool_calls = self._parse_tool_calls(model_resp)
            if not tool_calls:
                # If model attempted a tool call with invalid JSON syntax:
                if "tool" in model_resp.lower() and ("{" in model_resp or "```" in model_resp):
                    conversation_history.append({"role": "assistant", "content": model_resp})
                    conversation_history.append(
                        {
                            "role": "user",
                            "content": (
                                "JSON parse error in your tool call. Please output tool calls in valid JSON format: "
                                "```json\n{\"tool\": \"[tool_name]\", \"arguments\": {[args]}}\n```\n"
                                "Ensure internal quotes are escaped or use single quotes inside Python code strings."
                            ),
                        }
                    )
                    continue

                # Only finish if explicitly declared without tool syntax:
                if (
                    "task completed" in model_resp.lower()
                    or "task is complete" in model_resp.lower()
                    or "finished the task" in model_resp.lower()
                ):
                    completed = True
                    final_summary = model_resp.strip()
                    break

                # Nudge model
                conversation_history.append({"role": "assistant", "content": model_resp})
                conversation_history.append(
                    {
                        "role": "user",
                        "content": "Please specify your tool call in ```json {\"tool\": \"...\", \"arguments\": {...}} ``` format, or finish(summary).",
                    }
                )
                continue

            last_observation = ""
            last_tool_name = ""
            for thought, tool_call in tool_calls:
                tool_name = tool_call.get("tool", "")
                args = tool_call.get("arguments", {})

                if tool_name == "finish":
                    completed = True
                    final_summary = args.get("summary", "Task completed.")
                    steps.append(
                        LoopStep(
                            turn=turn,
                            thought=thought,
                            tool=tool_name,
                            arguments=args,
                            observation="Task finished.",
                            duration=round(time.perf_counter() - turn_start, 3),
                        )
                    )
                    break

                observation = self._execute_tool(tool_name, args)
                if tool_name == "apply_diff" and "Successfully applied" in observation:
                    target_p = str(args.get("path", ""))
                    if target_p and target_p not in modified_files:
                        modified_files.append(target_p)

                step_duration = round(time.perf_counter() - turn_start, 3)
                steps.append(
                    LoopStep(
                        turn=turn,
                        thought=thought,
                        tool=tool_name,
                        arguments=args,
                        observation=observation,
                        duration=step_duration,
                    )
                )
                last_observation = observation
                last_tool_name = tool_name

                # If a step failed in a pipeline, stop sequential execution and let the model re-think
                if ("Error:" in observation or "FAILED" in observation) and len(tool_calls) > 1:
                    break

            if completed:
                break

            # Provide actionable next-step guidance for local models
            guidance = ""
            if last_tool_name == "find_symbol":
                guidance = "\n\nNEXT ACTION: Symbol location found above. Now call read_slice(path=..., start_line=..., end_line=...) to inspect the code lines."
            elif last_tool_name == "read_slice":
                guidance = "\n\nNEXT ACTION: Code lines retrieved above. Now call apply_diff(path=..., search=..., replace=...) to apply your fix."
            elif last_tool_name == "apply_diff":
                if "Successfully applied" in last_observation:
                    guidance = "\n\nNEXT ACTION: The diff has been applied. Now call run_command(command=...) to run your verification tests."
                else:
                    guidance = "\n\nNEXT ACTION: Check the error above, read the file lines if needed, and try apply_diff with the exact lines."
            elif last_tool_name == "run_command":
                if "[SUCCESS]" in last_observation:
                    guidance = "\n\nNEXT ACTION: All tests passed! Call finish(summary='...') to complete the goal."
                else:
                    guidance = "\n\nNEXT ACTION: The test command failed. Inspect the output and call apply_diff to correct the code."

            # Append to history
            conversation_history.append({"role": "assistant", "content": model_resp})
            conversation_history.append(
                {
                    "role": "user",
                    "content": f"OBSERVATION for {last_tool_name}:\n{last_observation}{guidance}",
                }
            )

        total_duration = round(time.perf_counter() - start_time, 3)
        return AutonomousLoopResult(
            goal=goal,
            completed=completed,
            summary=final_summary or ("Loop completed maximum turns." if not completed else "Done."),
            steps=steps,
            modified_files=modified_files,
            total_duration=total_duration,
            model=self.model_name,
            error=None if completed else "Exceeded max turn budget without explicit finish.",
        )

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Run requested tool locally on macOS."""
        try:
            if tool_name == "search_code":
                query = args.get("query", "")
                path_prefix = args.get("path", ".")
                lines = []
                # Try ripgrep first (handles untracked files and fast search)
                try:
                    res = subprocess.run(
                        ["rg", "-n", "-i", "--no-heading", "--max-count", "15", query, path_prefix],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if res.stdout.strip():
                        lines = res.stdout.strip().splitlines()[:15]
                except Exception:
                    pass

                # Fallback to git grep
                if not lines:
                    cmd = ["git", "grep", "-n", "-I", "-i", query, "--", path_prefix]
                    res = subprocess.run(
                        cmd,
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if res.stdout.strip():
                        lines = res.stdout.strip().splitlines()[:15]

                return "\n".join(lines) if lines else "No matching references found."

            elif tool_name == "find_symbol":
                name = args.get("name", "")
                records = self.symbol_index.find_symbol(name, root_dir=self.repo_root)
                if not records:
                    records = self.symbol_index.search_symbols(name, limit=5, root_dir=self.repo_root)
                if not records:
                    return f"Symbol '{name}' not found in index."
                out = []
                for r in records:
                    out.append(f"{r.kind} {r.name}{r.signature} in {r.file_path} (L{r.start_line}-L{r.end_line})")
                return "\n".join(out)

            elif tool_name == "read_slice":
                rel_path = args.get("path", "")
                full_path = (self.repo_root / rel_path).resolve()
                if not full_path.is_file():
                    return f"Error: File not found: {rel_path}"
                start_l = max(1, int(args.get("start_line", 1)))
                end_l = max(start_l, int(args.get("end_line", start_l + 50)))
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                slice_lines = lines[start_l - 1 : end_l]
                numbered = [f"{start_l + i:4d}: {l}" for i, l in enumerate(slice_lines)]
                return "".join(numbered)

            elif tool_name == "apply_diff":
                rel_path = args.get("path", "")
                full_path = (self.repo_root / rel_path).resolve()
                if not full_path.is_file():
                    return f"Error: File not found: {rel_path}"
                search_block = args.get("search", "")
                replace_block = args.get("replace", "")
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                updated, matched = apply_search_replace(content, search_block, replace_block)
                if not matched:
                    return f"Error: Could not locate exact search block in {rel_path}. TIP: Call read_slice(path='{rel_path}', start_line=1, end_line=50) to see exact code lines."
                # Write backup and updated
                bak = full_path.with_suffix(full_path.suffix + ".vifi_bak")
                with open(bak, "w", encoding="utf-8") as f:
                    f.write(content)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(updated)
                return f"Successfully applied changes to {rel_path}."

            elif tool_name == "run_command":
                cmd = args.get("command", "")
                if not cmd:
                    return "Error: No command provided."
                # Security boundary: disallow destructive root commands
                if any(k in cmd for k in ("rm -rf /", "sudo", ":(){", "mkfs")):
                    return "Error: Disallowed destructive command."
                sub_env = os.environ.copy()
                py_bin = os.path.dirname(sys.executable)
                sub_env["PATH"] = f"{py_bin}:{sub_env.get('PATH', '')}"
                res = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=sub_env,
                )
                combined = (res.stdout + "\n" + res.stderr).strip()
                status_str = "SUCCESS" if res.returncode == 0 else f"FAILED (code {res.returncode})"
                return f"[{status_str}]\n{combined[:1000]}"

            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            return f"Tool execution exception: {e}"

    def _parse_tool_calls(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract thought and JSON tool calls (supports multi-tool execution pipelines)."""
        calls: List[Tuple[str, Dict[str, Any]]] = []

        # Find all JSON code blocks with preceding thoughts
        pattern = r"(?:THOUGHT:\s*(.*?)\s*)?```(?:json)?\s*(\{.*?\})\s*```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        for thought_txt, json_txt in matches:
            try:
                data = json.loads(json_txt)
                if isinstance(data, dict) and "tool" in data:
                    calls.append((thought_txt.strip(), data))
                    continue
            except Exception:
                pass
            try:
                import ast
                data = ast.literal_eval(json_txt)
                if isinstance(data, dict) and "tool" in data:
                    calls.append((thought_txt.strip(), data))
            except Exception:
                pass

        if not calls:
            t, single = self._parse_tool_call(text)
            if single:
                calls.append((t, single))

        return calls

    def _parse_tool_call(self, text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Extract thought and JSON tool call."""
        thought_match = re.search(r"THOUGHT:\s*(.*?)(?=```|\Z)", text, re.DOTALL | re.IGNORECASE)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 1. Search all markdown json blocks
        blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        for b in blocks:
            try:
                data = json.loads(b)
                if isinstance(data, dict) and "tool" in data:
                    return thought, data
            except Exception:
                pass
            try:
                import ast
                data = ast.literal_eval(b)
                if isinstance(data, dict) and "tool" in data:
                    return thought, data
            except Exception:
                pass

        # 2. Try raw json objects with "tool"
        raw_matches = re.findall(r"(\{\s*\"tool\"\s*:\s*\"[^\"]+\".*?\})", text, re.DOTALL)
        for m in raw_matches:
            try:
                data = json.loads(m)
                if isinstance(data, dict) and "tool" in data:
                    return thought, data
            except Exception:
                pass
            try:
                import ast
                data = ast.literal_eval(m)
                if isinstance(data, dict) and "tool" in data:
                    return thought, data
            except Exception:
                pass

        return thought, None

    async def _query_model(self, messages: List[Dict[str, str]]) -> str:
        """Send chat messages to warm local model server (LiteRT or Ollama)."""
        # 1. Check Ollama API first
        ollama_url = "http://127.0.0.1:11434/api/chat"
        try:
            req_data = {
                "model": self.model_name,
                "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 2048},
            }
            req = urllib.request.Request(
                ollama_url,
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "").strip()
        except Exception:
            pass

        # 2. Check LiteRT warm HTTP server (port 9379/9380)
        litert_url = (
            "http://127.0.0.1:9380/v1/chat/completions"
            if "26b" in self.model_name
            else "http://127.0.0.1:9379/v1/chat/completions"
        )
        try:
            req_data = {
                "model": self.model_name,
                "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages,
                "temperature": 0.2,
                "max_tokens": 2048,
            }
            req = urllib.request.Request(
                litert_url,
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        # 3. Fallback to in-process LocalModelEngine
        from voicefi.local.engine import LocalModelEngine

        engine = LocalModelEngine(model_name=self.model_name)
        full_p = "\n\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages])
        return await engine.chat_text(prompt=full_p, system_instructions=self.SYSTEM_PROMPT)
