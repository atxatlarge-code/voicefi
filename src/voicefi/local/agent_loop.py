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
import shlex
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
                    "observation": s.observation[:300] + "..."
                    if len(s.observation) > 300
                    else s.observation,
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
        '{"tool": "[tool_name]", "arguments": {[args]}}\n'
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

        # Check resource headroom for local model
        from voicefi.local.supervisor import default_supervisor

        approved, reason, alert = default_supervisor.can_load_model(self.model_name)
        if not approved:
            alert_box = default_supervisor.format_resource_alert(alert) if alert else reason
            logger.warning(
                f"[LocalAutonomousLoop] Model '{self.model_name}' blocked by ResourceGate: {reason}"
            )
            return AutonomousLoopResult(
                goal=goal,
                completed=False,
                summary=f"ResourceGate Blocked: Insufficient hardware headroom for '{self.model_name}'.\n\n{alert_box}",
                steps=[],
                modified_files=[],
                total_duration=0.0,
                model=self.model_name,
                error=reason,
            )

        steps: List[LoopStep] = []
        modified_files: List[str] = []
        conversation_history: List[Dict[str, str]] = []

        # Pre-seed relevant AST symbols from goal if matched
        words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", goal))
        symbol_hints = []
        for w in words:
            records = self.symbol_index.find_symbol(w, root_dir=self.repo_root, auto_refresh=False)
            for r in records[:2]:
                symbol_hints.append(
                    f"• `{r.name}` ({r.kind}) in `{r.file_path}` (lines {r.start_line}-{r.end_line})"
                )

        initial_user_msg = f"GOAL: {goal}"
        if symbol_hints:
            initial_user_msg += "\n\nKNOWN AST SYMBOLS:\n" + "\n".join(symbol_hints)
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
                                '```json\n{"tool": "[tool_name]", "arguments": {[args]}}\n```\n'
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
                        "content": 'Please specify your tool call in ```json {"tool": "...", "arguments": {...}} ``` format, or finish(summary).',
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
        total_dur = total_duration
        self.steps = steps
        try:
            from voicefi.local.telemetry import record_hybrid_step

            record_hybrid_step(
                stage="local_loop",
                model_name=self.model_name,
                is_local=True,
                duration_ms=int(total_dur * 1000),
                input_tokens=len(self.steps) * 800,
                output_tokens=len(self.steps) * 180,
                success=completed,
                notes=f"{len(self.steps)} turns",
            )
        except Exception:
            pass

        return AutonomousLoopResult(
            goal=goal,
            completed=completed,
            summary=final_summary
            or ("Loop completed maximum turns." if not completed else "Done."),
            steps=steps,
            modified_files=modified_files,
            total_duration=total_duration,
            model=self.model_name,
            error=None if completed else "Exceeded max turn budget without explicit finish.",
        )

    _SENSITIVE_PARTS = {".git", ".ssh", ".aws", ".gnupg", ".voicefi"}
    _SENSITIVE_FILES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "config.yaml"}
    _FORBIDDEN_SHELL_TOKENS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r", "\x00")
    _ALLOWED_BINARIES = {"pytest", "python", "python3", "ruff", "git", "mypy", "flake8", "echo", "ls", "pwd"}

    def _resolve_safe_repo_path(self, rel_path: str, allow_dir: bool = False) -> Optional[Path]:
        """Ensure rel_path resolves strictly inside self.repo_root and is not a sensitive secret path."""
        try:
            clean_rel = (rel_path or "").strip()
            if not clean_rel:
                return self.repo_root.resolve() if allow_dir else None
            resolved_root = self.repo_root.resolve()
            candidate = (resolved_root / clean_rel).resolve()
            if not candidate.is_relative_to(resolved_root):
                return None
            rel_parts = candidate.relative_to(resolved_root).parts
            if any(part in self._SENSITIVE_PARTS or part.startswith(".env") for part in rel_parts):
                return None
            if candidate.name in self._SENSITIVE_FILES:
                return None
            return candidate
        except Exception:
            return None

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Run requested tool locally on macOS."""
        try:
            if tool_name == "search_code":
                query = (args.get("query") or "").strip()
                if not query:
                    return "Error: Empty search query."
                path_prefix = args.get("path", ".")
                safe_target = self._resolve_safe_repo_path(path_prefix, allow_dir=True)
                if safe_target is None:
                    return f"Error: Access denied for path '{path_prefix}' (outside repository)."
                safe_rel = str(safe_target.relative_to(self.repo_root.resolve()))
                lines = []
                # Try ripgrep first (handles untracked files and fast search)
                try:
                    res = subprocess.run(
                        ["rg", "-n", "-i", "--no-heading", "--max-count", "15", "--", query, safe_rel],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=5,
                        shell=False,
                    )
                    if res.stdout.strip():
                        lines = res.stdout.strip().splitlines()[:15]
                except Exception:
                    pass

                # Fallback to git grep
                if not lines:
                    cmd = ["git", "grep", "-n", "-I", "-i", "-e", query, "--", safe_rel]
                    res = subprocess.run(
                        cmd,
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=5,
                        shell=False,
                    )
                    if res.stdout.strip():
                        lines = res.stdout.strip().splitlines()[:15]

                return "\n".join(lines) if lines else "No matching references found."

            elif tool_name == "find_symbol":
                name = args.get("name", "")
                records = self.symbol_index.find_symbol(name, root_dir=self.repo_root)
                if not records:
                    records = self.symbol_index.search_symbols(
                        name, limit=5, root_dir=self.repo_root
                    )
                if not records:
                    return f"Symbol '{name}' not found in index."
                out = []
                for r in records:
                    out.append(
                        f"{r.kind} {r.name}{r.signature} in {r.file_path} (L{r.start_line}-L{r.end_line})"
                    )
                return "\n".join(out)

            elif tool_name == "read_slice":
                rel_path = args.get("path", "")
                full_path = self._resolve_safe_repo_path(rel_path, allow_dir=False)
                if full_path is None:
                    return f"Error: Access denied: path '{rel_path}' is outside repository or restricted."
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
                full_path = self._resolve_safe_repo_path(rel_path, allow_dir=False)
                if full_path is None:
                    return f"Error: Access denied: path '{rel_path}' is outside repository or restricted."
                if not full_path.is_file():
                    return f"Error: File not found: {rel_path}"
                search_block = args.get("search", "")
                replace_block = args.get("replace", "")
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                updated, matched = apply_search_replace(content, search_block, replace_block)
                if not matched:
                    return f"Error: Could not locate exact search block in {rel_path}. TIP: Call read_slice(path='{rel_path}', start_line=1, end_line=50) to see exact code lines."
                if full_path.suffix == ".py":
                    try:
                        import ast

                        ast.parse(updated)
                    except SyntaxError as syn_err:
                        return (
                            f"Error: AST SyntaxGuard rejected your diff in {rel_path} at line {syn_err.lineno}: "
                            f"{syn_err.msg}. Check indentation and brackets, then retry apply_diff."
                        )
                # Write backup and updated
                bak = full_path.with_suffix(full_path.suffix + ".vifi_bak")
                with open(bak, "w", encoding="utf-8") as f:
                    f.write(content)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(updated)
                return f"Successfully applied changes to {rel_path}."

            elif tool_name == "run_command":
                cmd = (args.get("command") or "").strip()
                if not cmd:
                    return "Error: No command provided."
                # Security boundary: disallow destructive root commands or shell injection metacharacters
                if any(k in cmd for k in ("rm -rf", "sudo", ":(){", "mkfs", "chmod", "chown", "curl ", "wget ", "nc ", "bash", "sh ")):
                    return "Error: Disallowed destructive command."
                if any(tok in cmd for tok in self._FORBIDDEN_SHELL_TOKENS):
                    return "Error: Disallowed destructive command (shell chaining/redirection not permitted)."
                try:
                    cmd_args = shlex.split(cmd)
                except ValueError as e:
                    return f"Error: Invalid command syntax: {e}"
                if not cmd_args:
                    return "Error: No command provided."
                exe_name = Path(cmd_args[0]).name
                if exe_name not in self._ALLOWED_BINARIES:
                    return f"Error: Disallowed destructive command (executable '{exe_name}' not in safe allowlist)."
                if exe_name in ("python", "python3") and any(a in ("-c", "-i") for a in cmd_args[1:]):
                    return "Error: Disallowed destructive command (inline python -c is not permitted)."
                if exe_name == "git" and len(cmd_args) > 1 and cmd_args[1] in ("push", "reset", "clean", "rm", "config", "remote"):
                    return f"Error: Disallowed destructive command ('git {cmd_args[1]}' is not permitted)."
                sub_env = os.environ.copy()
                py_bin = os.path.dirname(sys.executable)
                sub_env["PATH"] = f"{py_bin}:{sub_env.get('PATH', '')}"
                res = subprocess.run(
                    cmd_args,
                    shell=False,
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

    @staticmethod
    def _normalize_tool_dict(data: Any) -> Optional[Dict[str, Any]]:
        """Normalize {'tool': ...} or {'name': ...} tool call dicts, including flat argument schemas."""
        if not isinstance(data, dict):
            return None
        tool_name = data.get("tool") or data.get("name") or data.get("function") or data.get("action")
        if isinstance(tool_name, dict):
            # Handle {"function": {"name": "...", "arguments": {...}}}
            nested_args = tool_name.get("arguments") or tool_name.get("parameters") or {}
            tool_name = tool_name.get("name")
        else:
            nested_args = None
        if not tool_name or not isinstance(tool_name, str):
            return None
        args = (
            nested_args
            or data.get("arguments")
            or data.get("parameters")
            or data.get("args")
            or data.get("input")
            or {}
        )
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        if not args:
            reserved = {"tool", "name", "function", "action", "arguments", "parameters", "args", "input", "thought"}
            args = {k: v for k, v in data.items() if k not in reserved}
        return {"tool": tool_name.strip(), "arguments": args}

    def _parse_tool_calls(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract thought and JSON tool calls (supports multi-tool execution pipelines)."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        calls: List[Tuple[str, Dict[str, Any]]] = []

        # 1. Find all JSON code blocks or <tool_call> XML blocks with preceding thoughts
        pattern = r"(?:THOUGHT:\s*(.*?)\s*)?(?:```(?:json)?|<tool_call>)\s*(\{.*?\})\s*(?:```|</tool_call>)"
        matches = re.findall(pattern, cleaned, re.DOTALL | re.IGNORECASE)
        for thought_txt, json_txt in matches:
            for loader in (json.loads, __import__("ast").literal_eval):
                try:
                    norm = self._normalize_tool_dict(loader(json_txt))
                    if norm:
                        calls.append((thought_txt.strip(), norm))
                        break
                except Exception:
                    pass

        if not calls:
            t, single = self._parse_tool_call(cleaned)
            if single:
                calls.append((t, single))

        return calls

    def _parse_tool_call(self, text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Extract thought and JSON tool call."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        thought_match = re.search(r"THOUGHT:\s*(.*?)(?=```|<tool_call>|\{|$)", cleaned, re.DOTALL | re.IGNORECASE)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 1. Search all markdown json blocks and <tool_call> blocks
        blocks = re.findall(r"(?:```(?:json)?|<tool_call>)\s*(\{.*?\})\s*(?:```|</tool_call>)", cleaned, re.DOTALL)
        for b in blocks:
            for loader in (json.loads, __import__("ast").literal_eval):
                try:
                    norm = self._normalize_tool_dict(loader(b))
                    if norm:
                        return thought, norm
                except Exception:
                    pass

        # 2. Try raw json objects with "tool" or "name" (including raw_decode for trailing braces/fences)
        raw_matches = re.findall(r'(\{\s*"(?:tool|name)"\s*:\s*"[^"]+".*\})', cleaned, re.DOTALL)
        for m in raw_matches:
            for loader in (json.loads, __import__("ast").literal_eval):
                try:
                    norm = self._normalize_tool_dict(loader(m))
                    if norm:
                        return thought, norm
                except Exception:
                    pass
            try:
                obj, _ = json.JSONDecoder().raw_decode(m.lstrip())
                norm = self._normalize_tool_dict(obj)
                if norm:
                    return thought, norm
            except Exception:
                pass

        return thought, None

    OLLAMA_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "read_slice",
                "description": "view specific lines of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path", "start_line", "end_line"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_symbol",
                "description": "look up class, function, or method definitions in the SQLite AST index",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "search for text/regex across files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_diff",
                "description": "apply exact SEARCH/REPLACE block to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "search": {"type": "string"},
                        "replace": {"type": "string"},
                    },
                    "required": ["path", "search", "replace"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "execute a shell/test command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "declare the task completed",
                "parameters": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                },
            },
        },
    ]

    async def _query_model(self, messages: List[Dict[str, str]]) -> str:
        """Send chat messages to warm local model server (LiteRT or Ollama)."""
        from voicefi.local.supervisor import default_supervisor

        default_supervisor.assert_can_load(self.model_name)

        # 1. Check Ollama API first
        ollama_url = "http://127.0.0.1:11434/api/chat"
        try:
            req_data: Dict[str, Any] = {
                "model": self.model_name,
                "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 2048},
            }
            if "flint" in self.model_name:
                req_data["tools"] = self.OLLAMA_TOOLS
            req = urllib.request.Request(
                ollama_url,
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msg = data.get("message", {})
                content = msg.get("content", "").strip()
                if not content and msg.get("thinking"):
                    content = msg.get("thinking", "").strip()
                native_tcs = msg.get("tool_calls") or []
                for tc in native_tcs:
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tc_json = json.dumps(
                            {"tool": fn["name"], "arguments": fn.get("arguments", {})}
                        )
                        content = f"{content}\n```json\n{tc_json}\n```".strip()
                return content
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
