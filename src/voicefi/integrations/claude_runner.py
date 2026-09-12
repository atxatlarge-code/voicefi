"""
Headless Claude Runner for VoiceFi.
Provides zero-flicker, non-interactive execution of Claude Code CLI sessions
bound to specific conversation IDs, with automatic token discovery, per-conversation
serialization locks, and seamless companion WebSocket return loops.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.conversations import (
    claim_turn,
    save_session_cookie,
    set_mobile_turn_origin,
    record_agent_route,
)


def claude_session_exists_on_disk(session_uuid: str) -> bool:
    """Check whether a Claude session JSONL file actually exists in ~/.claude/projects/."""
    try:
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.is_dir():
            return False
        return any(claude_dir.glob(f"*/{session_uuid}.jsonl"))
    except Exception:
        return False


def normalize_claude_conv_id(conv_id: Optional[str]) -> Tuple[str, str, bool]:
    """
    Normalizes conversation ID between canonical VoiceFi ID ('claude_<uuid>')
    and bare UUID expected by Claude CLI ('<uuid>').

    Returns:
        (canonical_id, session_uuid, is_new)
    """
    if not conv_id or str(conv_id).strip().lower() in ("", "new", "null", "none", "active"):
        new_uuid = str(uuid.uuid4())
        return f"claude_{new_uuid}", new_uuid, True

    clean_id = str(conv_id).strip()
    raw_uuid = clean_id[7:].strip() if clean_id.startswith("claude_") else clean_id

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    if uuid_pattern.match(raw_uuid):
        return f"claude_{raw_uuid}", raw_uuid, False

    # If conv_id is a custom slug or name, generate a deterministic UUID
    synth_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_uuid))
    return f"claude_{synth_uuid}", synth_uuid, False


def resolve_claude_auth_token(config: Optional[VoiceFiConfig] = None) -> Optional[str]:
    """
    Resilient 4-tier authentication token resolver for headless Claude execution:
    1. Direct environment variables (CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY).
    2. VoiceFi configuration override (claude.oauth_token in ~/.voicefi/config.yaml).
    3. Configuration dotfiles (~/.config/PAI/.env, ~/.claude/.env).
    4. Active Claude Desktop process environment sniffing on macOS (ps eww).
    5. macOS Keychain query (login.keychain-db).
    """
    # Tier 1: Current process environment
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if env_token and env_token.strip():
        return env_token.strip()

    # Tier 2: Configuration file
    cfg = config or load_config()
    cfg_token = getattr(getattr(cfg, "claude", None), "oauth_token", None)
    if cfg_token and str(cfg_token).strip():
        return str(cfg_token).strip()

    # Tier 3: Known environment dotfiles
    dotfile_candidates = [
        Path.home() / ".config" / "PAI" / ".env",
        Path.home() / ".claude" / ".env",
        Path.home() / ".env",
    ]
    for df in dotfile_candidates:
        if df.is_file():
            try:
                content = df.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip("\"\'")
                        if val:
                            return val
                    elif line.startswith("ANTHROPIC_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"\'")
                        if val:
                            return val
            except Exception:
                pass

    # Tier 4: macOS process sniffing (extract token from active Claude Desktop process)
    if sys.platform == "darwin":
        try:
            ps_cmd = ["pgrep", "-f", "Claude.app|claude"]
            pids_out = subprocess.run(ps_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
            pids = [p.strip() for p in pids_out.splitlines() if p.strip()]
            for pid in pids:
                try:
                    eww_out = subprocess.run(
                        ["ps", "eww", pid],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=1,
                    ).stdout
                    for item in eww_out.split():
                        if item.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                            t = item.split("=", 1)[1].strip()
                            if t and len(t) > 10:
                                return t
                except Exception:
                    continue
        except Exception:
            pass

    # Tier 5: macOS Keychain lookup
    if sys.platform == "darwin":
        keychain_services = ["Claude Code-credentials", "Claude Safe Storage"]
        for svc in keychain_services:
            try:
                res = subprocess.run(
                    ["security", "find-generic-password", "-s", svc, "-w"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2,
                )
                if res.returncode == 0 and res.stdout.strip():
                    val = res.stdout.strip()
                    if val.startswith("sk-") or len(val) > 20:
                        return val
            except Exception:
                continue

    return None


def find_claude_binary() -> Optional[str]:
    """Find the Claude CLI binary executable on macOS/Linux."""
    # 1. System PATH
    found = shutil.which("claude")
    if found and os.access(found, os.X_OK):
        return found

    # 2. Known standard install locations
    home = Path.home()
    candidates = [
        home / ".nvm" / "versions" / "node" / "v22.22.0" / "bin" / "claude",
        home / ".npm-global" / "bin" / "claude",
        home / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ]

    nvm_dir = home / ".nvm" / "versions" / "node"
    if nvm_dir.is_dir():
        try:
            for bin_cand in sorted(nvm_dir.glob("*/bin/claude"), reverse=True):
                if bin_cand.is_file() and os.access(str(bin_cand), os.X_OK):
                    return str(bin_cand)
        except Exception:
            pass

    for cand in candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK):
            return str(cand)

    return None


class ClaudeHeadlessRunner:
    """
    Thread-safe, headless executor for Claude Code CLI sessions.
    Serializes concurrent messages per conversation ID using conversation locks,
    streams output, and broadcasts turn completions to the Companion Server.
    """

    _instance: Optional["ClaudeHeadlessRunner"] = None
    _global_lock = threading.Lock()

    def __init__(self):
        self._conv_locks: Dict[str, threading.Lock] = {}
        self._conv_locks_guard = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ClaudeHeadlessRunner":
        with cls._global_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _get_conv_lock(self, canonical_id: str) -> threading.Lock:
        with self._conv_locks_guard:
            if canonical_id not in self._conv_locks:
                self._conv_locks[canonical_id] = threading.Lock()
            return self._conv_locks[canonical_id]

    def dispatch(
        self,
        text: str,
        conv_id: Optional[str] = None,
        cwd: Optional[Path] = None,
        from_conv_id: Optional[str] = None,
        from_engine: str = "antigravity",
        include_envelope: bool = False,
        config: Optional[VoiceFiConfig] = None,
        timeout: Optional[int] = None,
        async_execution: bool = False,
        origin: str = "desktop",
    ) -> Any:
        from voicefi.integrations.injector import DispatchResult

        if not text or not text.strip():
            return DispatchResult(
                success=False,
                delivery_type="none",
                error="Empty message text",
                target_conv_id=conv_id,
                engine="claude",
            )

        clean_text = text.strip()
        canonical_id, session_uuid, is_new = normalize_claude_conv_id(conv_id)
        cfg = config or load_config()

        if include_envelope and from_conv_id:
            clean_text = f"""[From: {from_engine.capitalize()} | Conversation: {from_conv_id}]
{clean_text}

💡 To return your findings to Antigravity, run:
vifi send --to antigravity --reply "Your findings summary"
# or:
curl -s -X POST http://localhost:5141/api/send -H "Content-Type: application/json" -d '{{"text": "Your findings summary", "conv_id": "{from_conv_id}", "engine": "antigravity", "sender_name": "Claude"}}'"""

        if from_conv_id:
            record_agent_route(
                from_engine=from_engine,
                from_conv_id=from_conv_id,
                to_engine="claude",
                to_conv_id=canonical_id,
            )

        if origin == "mobile":
            set_mobile_turn_origin(canonical_id)
            set_mobile_turn_origin(session_uuid)

        # Resolve active workspace directory if cwd is unstated or home
        resolved_cwd = cwd
        if not resolved_cwd or str(resolved_cwd) == str(Path.home()):
            from voicefi.integrations.conversations import load_session_cookie

            cookie = load_session_cookie()
            if cookie and cookie.get("workspacePath") and Path(cookie["workspacePath"]).is_dir():
                resolved_cwd = Path(cookie["workspacePath"])
            elif (Path.cwd() / "pyproject.toml").is_file() or (Path.cwd() / ".git").is_dir():
                resolved_cwd = Path.cwd()

        save_session_cookie(
            conv_id=canonical_id,
            title=f"Claude ({session_uuid[:8]})",
            workspace_path=str(resolved_cwd or Path.cwd()),
            engine="claude",
        )

        resolved_timeout = timeout or getattr(getattr(cfg, "claude", None), "timeout_seconds", 300)

        if async_execution:
            thread = threading.Thread(
                target=self._execute_headless,
                args=(clean_text, canonical_id, session_uuid, is_new, resolved_cwd, cfg, resolved_timeout, origin),
                daemon=True,
                name=f"ClaudeHeadless-{session_uuid[:8]}",
            )
            thread.start()
            return DispatchResult(
                success=True,
                delivery_type="headless",
                target_conv_id=canonical_id,
                engine="claude",
            )

        return self._execute_headless(
            clean_text, canonical_id, session_uuid, is_new, resolved_cwd, cfg, resolved_timeout, origin
        )

    def _execute_headless(
        self,
        prompt: str,
        canonical_id: str,
        session_uuid: str,
        is_new: bool,
        cwd: Optional[Path],
        config: VoiceFiConfig,
        timeout: int,
        origin: str = "desktop",
    ) -> Any:
        from voicefi.integrations.injector import DispatchResult

        claude_bin = find_claude_binary()
        if not claude_bin:
            err = "Claude CLI binary not found on PATH or in standard directories."
            print(f"[ClaudeRunner] ❌ {err}")
            return DispatchResult(
                success=False,
                delivery_type="none",
                error=err,
                target_conv_id=canonical_id,
                engine="claude",
            )

        token = resolve_claude_auth_token(config)
        env = dict(os.environ)
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token

        perm_mode = getattr(getattr(config, "claude", None), "permission_mode", "auto")

        cmd = [
            claude_bin,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--permission-mode",
            perm_mode,
        ]

        if is_new:
            cmd.extend(["--session-id", session_uuid])
        else:
            cmd.extend(["--resume", session_uuid])

        working_dir = str(cwd or Path.cwd())

        conv_lock = self._get_conv_lock(canonical_id)
        with conv_lock:
            print(
                f"[ClaudeRunner] 🚀 Headless dispatch: {cmd[3][:40]}... (session: {session_uuid[:8]}, is_new: {is_new})"
            )
            try:
                proc = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    cwd=working_dir,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                err = f"Claude session {canonical_id} timed out after {timeout} seconds."
                print(f"[ClaudeRunner] ⏱️ {err}")
                return DispatchResult(
                    success=False,
                    delivery_type="headless",
                    error=err,
                    target_conv_id=canonical_id,
                    engine="claude",
                )
            except Exception as e:
                err = f"Subprocess error: {e}"
                print(f"[ClaudeRunner] ❌ {err}")
                return DispatchResult(
                    success=False,
                    delivery_type="headless",
                    error=err,
                    target_conv_id=canonical_id,
                    engine="claude",
                )

            stdout_text = proc.stdout.strip()
            stderr_text = proc.stderr.strip()

            if proc.returncode != 0:
                combined_err = f"{stderr_text} {stdout_text}".strip()
                # If resume failed because session was not found, retry once with --session-id
                if not is_new and "--resume" in cmd and any(
                    k in combined_err.lower()
                    for k in ("not found", "no session", "does not exist", "failed to load session")
                ):
                    print(
                        f"[ClaudeRunner] 🔄 Session {session_uuid[:8]} not found on disk; retrying with --session-id..."
                    )
                    retry_cmd = list(cmd)
                    idx = retry_cmd.index("--resume")
                    retry_cmd[idx] = "--session-id"
                    try:
                        proc = subprocess.run(
                            retry_cmd,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env=env,
                            cwd=working_dir,
                            timeout=timeout,
                        )
                        stdout_text = proc.stdout.strip()
                        stderr_text = proc.stderr.strip()
                    except Exception as retry_e:
                        print(f"[ClaudeRunner] ⚠️ Retry failed: {retry_e}")

            if proc.returncode != 0:
                combined_err = f"{stderr_text} {stdout_text}".strip()
                if "not logged in" in combined_err.lower() or "please run /login" in combined_err.lower():
                    diag_err = (
                        "Claude Code authentication required. Set CLAUDE_CODE_OAUTH_TOKEN, "
                        "add oauth_token to ~/.voicefi/config.yaml, or log into Claude."
                    )
                else:
                    diag_err = f"Claude CLI error (exit code {proc.returncode}): {combined_err or 'unknown error'}"
                print(f"[ClaudeRunner] ❌ {diag_err}")
                return DispatchResult(
                    success=False,
                    delivery_type="headless",
                    error=diag_err,
                    target_conv_id=canonical_id,
                    engine="claude",
                )

            result_text = ""
            try:
                data = json.loads(stdout_text)
                if isinstance(data, dict):
                    if data.get("is_error"):
                        err_msg = data.get("result") or "Claude reported an error"
                        return DispatchResult(
                            success=False,
                            delivery_type="headless",
                            error=str(err_msg),
                            target_conv_id=canonical_id,
                            engine="claude",
                        )
                    result_text = str(data.get("result", "")).strip()
            except Exception:
                result_text = stdout_text

            if not result_text:
                result_text = "Claude completed the task."

            max_words = getattr(getattr(config, "claude", None), "max_spoken_words", 60)
            summary = clean_markdown_for_speech(result_text, max_words=max_words)

            claim_turn(canonical_id, summary, origin=origin)
            claim_turn(session_uuid, summary, origin=origin)

            self._notify_companion_server(
                summary=summary,
                full_response=result_text,
                canonical_id=canonical_id,
                origin=origin,
            )

            # If desktop voice origin, speak the soundbite aloud on Mac speakers
            if origin != "mobile" and getattr(getattr(config, "claude", None), "read_summary_aloud", True):
                def _speak_on_mac():
                    try:
                        from voicefi.tts import get_tts_engine
                        from voicefi.tts.base import (
                            set_cross_process_hud_state,
                            clear_cross_process_hud_state,
                        )
                        set_cross_process_hud_state("speaking", summary, agent_name="Claude")
                        try:
                            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

                            hud = UnifiedDynamicIslandHUD.get_instance()
                            hud.set_speaking("Claude", summary)
                        except Exception:
                            pass

                        tts = get_tts_engine(config, agent_name="claude")
                        tts.stream_speak(summary, block=True)
                    except Exception as ex:
                        print(f"[ClaudeRunner] Desktop spoken playback error: {ex}", flush=True)
                    finally:
                        try:
                            clear_cross_process_hud_state()
                        except Exception:
                            pass

                threading.Thread(target=_speak_on_mac, daemon=True, name="ClaudeDesktopTTS").start()

            print(f'[ClaudeRunner] ✅ Turn complete for {canonical_id}: "{summary[:50]}..."')
            return DispatchResult(
                success=True,
                delivery_type="headless",
                target_conv_id=canonical_id,
                engine="claude",
            )

    def _notify_companion_server(
        self, summary: str, full_response: str, canonical_id: str, origin: str = "mobile"
    ) -> None:
        try:
            from voicefi.audio.echo_canceller import record_agent_spoken

            if summary:
                record_agent_spoken(summary)
        except Exception:
            pass

        def _post_notify():
            try:
                import json
                import urllib.request

                payload = json.dumps({
                    "summary": summary,
                    "full_response": full_response,
                    "conv_id": canonical_id,
                    "agent_role": "claude",
                    "origin": origin,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:5141/api/turn_notify",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    pass
            except Exception:
                pass

        threading.Thread(target=_post_notify, daemon=True, name="TurnNotify").start()