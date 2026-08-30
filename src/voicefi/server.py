"""
Unified Server, Process Lifecycle, and Cache Management for VoiceFi.

Handles:
- LaunchAgent management (bootout, disable, load, status)
- Process detection, signal handling, and PID-aware lock recovery
- Cache invalidation (__pycache__, update checks, temporary session state)
- Development environment linking for Antigravity and Claude Code hooks
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


LAUNCHAGENT_LABELS = ["com.voicefi.menubar", "com.voicefi.tray"]
LAUNCHAGENT_LABEL = "com.voicefi.menubar"
LAUNCHAGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"
LAUNCHAGENT_PLISTS = [Path.home() / "Library" / "LaunchAgents" / f"{lbl}.plist" for lbl in LAUNCHAGENT_LABELS]
LOCK_FILE = Path("/tmp/voicefi_tray.lock")
PID_FILE = Path("/tmp/voicefi_tray.pid")


def get_current_uid() -> int:
    """Return the current user ID."""
    try:
        return os.getuid()
    except Exception:
        return 501


def is_pid_running(pid: int) -> bool:
    """Check whether a process with given PID is currently running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def get_process_info_by_pid(pid: int) -> Optional[Dict[str, Any]]:
    """Retrieve commandline and runtime details for a given PID."""
    if not is_pid_running(pid):
        return None
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split(None, 2)
            cmd = parts[2] if len(parts) > 2 else ""
            return {"pid": pid, "command": cmd}
    except Exception:
        pass
    return {"pid": pid, "command": "unknown"}


def find_running_voicefi_processes(include_mcp: bool = True) -> List[Dict[str, Any]]:
    """Scan and return all active VoiceFi / vifi processes."""
    my_pid = os.getpid()
    results = []
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,ppid,command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line_str = line.strip()
                if not line_str:
                    continue
                parts = line_str.split(None, 2)
                if len(parts) < 3:
                    continue
                try:
                    pid = int(parts[0])
                    ppid = int(parts[1])
                except ValueError:
                    continue
                cmd = parts[2]

                # Filter out current process, grep, or editor tools
                if pid == my_pid:
                    continue
                if "grep" in cmd or "ps -eo" in cmd:
                    continue

                # Match voicefi / vifi CLI, servers, daemons, HUDs, or test runners
                cmd_lower = cmd.lower()
                is_voicefi = False
                if "voicefi" in cmd_lower or "vifi" in cmd_lower:
                    is_voicefi = True
                elif any(kw in cmd_lower for kw in [
                    "test_btn_crash", "test_hud", "unified_hud", "activity_hub",
                    "capture_hud_states", "sync_hud_assets", "audition_server", "pytest"
                ]):
                    is_voicefi = True

                if is_voicefi:
                    is_mcp = bool(" mcp" in cmd_lower or cmd_lower.endswith(" mcp"))
                    if not include_mcp and is_mcp:
                        continue
                    results.append({
                        "pid": pid,
                        "ppid": ppid,
                        "command": cmd,
                        "is_mcp": is_mcp,
                    })
    except Exception:
        pass
    return results


def get_port_listener(port: int = 5141) -> Optional[Dict[str, Any]]:
    """Find process currently listening on the specified TCP port."""
    try:
        port = int(port)
    except (ValueError, TypeError):
        return None

    for flag in [f"-iTCP:{port}", f"-i:{port}"]:
        try:
            res = subprocess.run(
                ["lsof", "-n", "-P", flag, "-sTCP:LISTEN"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            if res.returncode == 0 and res.stdout.strip():
                lines = res.stdout.strip().splitlines()
                for line in lines[1:]:
                    cols = line.split()
                    if len(cols) >= 2:
                        pname = cols[0]
                        try:
                            pid = int(cols[1])
                            if is_pid_running(pid):
                                return {
                                    "port": port,
                                    "pid": pid,
                                    "command_name": pname,
                                    "full_info": get_process_info_by_pid(pid),
                                }
                        except ValueError:
                            continue
        except Exception:
            pass
    return None


def get_launchagent_status() -> Dict[str, Any]:
    """Check macOS LaunchAgent state for VoiceFi."""
    uid = get_current_uid()
    for lbl in LAUNCHAGENT_LABELS:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{lbl}.plist"
        plist_exists = plist_path.is_file()
        is_loaded = False
        pid = None

        try:
            res = subprocess.run(
                ["launchctl", "list", lbl],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                is_loaded = True
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('"PID"') or line.startswith('"pid"'):
                        try:
                            pid = int(line.split("=")[-1].replace(";", "").strip())
                        except ValueError:
                            pass
        except Exception:
            pass

        if not is_loaded:
            try:
                res = subprocess.run(
                    ["launchctl", "print", f"gui/{uid}/{lbl}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0:
                    is_loaded = True
                    for line in res.stdout.splitlines():
                        if "pid =" in line:
                            try:
                                pid = int(line.split("=")[-1].strip())
                            except ValueError:
                                pass
            except Exception:
                pass

        if is_loaded or plist_exists:
            return {
                "label": lbl,
                "plist_path": str(plist_path),
                "plist_exists": plist_exists,
                "is_loaded": is_loaded,
                "pid": pid,
            }

    return {
        "label": LAUNCHAGENT_LABEL,
        "plist_path": str(LAUNCHAGENT_PLIST),
        "plist_exists": LAUNCHAGENT_PLIST.is_file(),
        "is_loaded": False,
        "pid": None,
    }


def get_full_server_status() -> Dict[str, Any]:
    """Compile comprehensive status of VoiceFi server, processes, ports, and locks."""
    if "get_full_daemon_status" in globals() and globals()["get_full_daemon_status"] is not get_full_server_status:
        try:
            return globals()["get_full_daemon_status"]()
        except TypeError:
            pass

    la_status = get_launchagent_status()
    port_status = get_port_listener(5141) or get_port_listener(8765)
    processes = find_running_voicefi_processes()

    lock_active = LOCK_FILE.exists()
    pid_file_data = None
    if PID_FILE.is_file():
        try:
            pid_file_data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        except Exception:
            try:
                pid_file_data = {"pid": int(PID_FILE.read_text().strip())}
            except Exception:
                pid_file_data = {"raw": PID_FILE.read_text().strip()}

    gemini_hook = Path.home() / ".gemini" / "config" / "hooks.json"
    plugin_hook = Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin" / "hooks.json"
    claude_hook = Path.home() / ".claude" / "settings.json"
    
    gemini_cmd = None
    for cand in (plugin_hook, gemini_hook):
        if cand.is_file():
            try:
                gh_data = json.loads(cand.read_text(encoding="utf-8"))
                gemini_cmd = gh_data.get("voicefi-voice-layer", {}).get("Stop", [{}])[0].get("command")
                if gemini_cmd:
                    break
            except Exception:
                pass

    claude_cmd = None
    if claude_hook.is_file():
        try:
            ch_data = json.loads(claude_hook.read_text(encoding="utf-8"))
            hooks_list = ch_data.get("hooks", {}).get("Stop", [{}])[0].get("hooks", [{}])
            if hooks_list:
                claude_cmd = hooks_list[0].get("command")
        except Exception:
            pass

    codex_hook = Path.home() / ".codex" / "hooks.json"
    codex_cmd = None
    if codex_hook.is_file():
        try:
            codex_data = json.loads(codex_hook.read_text(encoding="utf-8"))
            hooks_list = codex_data.get("hooks", {}).get("Stop", [{}])[0].get("hooks", [{}])
            if hooks_list:
                codex_cmd = hooks_list[0].get("command")
        except Exception:
            pass

    return {
        "launchagent": la_status,
        "port_5141": port_status,
        "port_8765": port_status,
        "port_listener": port_status,
        "running_processes": processes,
        "lock_active": lock_active,
        "pid_file": pid_file_data,
        "hooks": {
            "antigravity": gemini_cmd,
            "claude": claude_cmd,
            "codex": codex_cmd,
        },
        "python_executable": sys.executable,
    }


# Backwards compatibility alias
get_full_daemon_status = get_full_server_status


def stop_all_voicefi_servers(
    disable_launchagent: bool = True,
    remove_plist: bool = False,
    timeout_seconds: float = 3.0,
    stop_mcp: bool = False,
) -> Dict[str, Any]:
    """
    Safely and comprehensively stop all running VoiceFi servers, background agents,
    and release locks and ports.
    """
    if "stop_all_voicefi_daemons" in globals() and globals()["stop_all_voicefi_daemons"] is not stop_all_voicefi_servers:
        try:
            return globals()["stop_all_voicefi_daemons"](
                disable_launchagent=disable_launchagent,
                remove_plist=remove_plist,
                timeout_seconds=timeout_seconds,
            )
        except TypeError:
            pass

    # 0. Instantly stop any active speech synthesis and audio playback
    try:
        from voicefi.tts.base import stop_all_speech
        stop_all_speech()
    except Exception:
        pass

    uid = get_current_uid()
    stopped_pids = []
    errors = []

    # 1. Unload and disable LaunchAgents first to avoid respawn loops
    for lbl in LAUNCHAGENT_LABELS:
        try:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{lbl}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception as e:
            errors.append(f"Launchctl bootout notice for {lbl}: {e}")

        try:
            subprocess.run(
                ["launchctl", "disable", f"gui/{uid}/{lbl}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass

    for plist in LAUNCHAGENT_PLISTS:
        if plist.is_file():
            try:
                subprocess.run(
                    ["launchctl", "unload", str(plist)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                pass
            if remove_plist:
                plist.unlink(missing_ok=True)

    # 2. Terminate running VoiceFi server and background daemon processes (excluding MCP clients unless stop_mcp=True)
    try:
        procs = find_running_voicefi_processes(include_mcp=stop_mcp)
    except TypeError:
        procs = find_running_voicefi_processes()
    for p in procs:
        pid = p["pid"]
        try:
            os.kill(pid, signal.SIGTERM)
            stopped_pids.append(pid)
        except (OSError, ProcessLookupError):
            pass

    # Wait for processes to exit
    start_t = time.time()
    while time.time() - start_t < timeout_seconds:
        alive = [pid for pid in stopped_pids if is_pid_running(pid)]
        if not alive:
            break
        time.sleep(0.1)

    # Force kill any stubborn processes
    for pid in stopped_pids:
        if is_pid_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    # 3. Check if port 5141 or legacy port 8765 are still occupied and kill their owners
    for p_num in (5141, 8765):
        port_listener = get_port_listener(p_num)
        if port_listener and port_listener.get("pid"):
            port_pid = port_listener["pid"]
            if port_pid != os.getpid() and port_pid not in stopped_pids:
                try:
                    os.kill(port_pid, signal.SIGKILL)
                    stopped_pids.append(port_pid)
                except Exception:
                    pass

    # Brief settle margin for socket release
    time.sleep(0.1)

    # 4. Clean up lock files and stale state
    clean_lock_files()

    return {
        "success": True,
        "stopped_pids": stopped_pids,
        "errors": errors,
        "port_freed": (get_port_listener(5141) is None and get_port_listener(8765) is None),
    }


# Backwards compatibility alias
stop_all_voicefi_daemons = stop_all_voicefi_servers


def clean_lock_files(only_stale: bool = False):
    """Purge temporary lock files, cross-process HUD states, and PID markers."""
    tmp_dir = Path("/tmp")
    known_files = [
        LOCK_FILE,
        PID_FILE,
        Path("/tmp/voicefi_active_turns.lock"),
        Path("/tmp/voicefi_speech.lock"),
        Path("/tmp/voicefi_cross_process_hud.json"),
        Path("/tmp/voicefi_hud_state.json"),
        Path("/tmp/voicefi_hud_stream.json"),
        Path("/tmp/voicefi_speech_pause.lock"),
        Path("/tmp/voicefi_speaking.status"),
        Path("/tmp/voicefi_audio_playing.status"),
        Path("/tmp/voicefi_recent_speech.json"),
        Path("/tmp/voicefi_last_speech_stop.ts"),
    ]

    if not only_stale:
        for lock in known_files:
            try:
                if lock.is_file() or lock.is_symlink():
                    lock.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            for f in tmp_dir.glob("voicefi*"):
                try:
                    if f.is_file() or f.is_symlink():
                        f.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
        return

    # Only stale cleanup
    try:
        for f in tmp_dir.glob("voicefi*"):
            try:
                if not (f.is_file() or f.is_symlink()):
                    continue
                is_stale = False
                try:
                    content = f.read_text(errors="ignore").strip()
                    if content.startswith("{") and "pid" in content:
                        data = json.loads(content)
                        if isinstance(data, dict) and "pid" in data:
                            f_pid = int(data["pid"])
                            if not is_pid_running(f_pid):
                                is_stale = True
                    elif ":" in content:
                        parts = content.split(":")
                        if len(parts) >= 2 and parts[0].isdigit():
                            f_pid = int(parts[0])
                            if not is_pid_running(f_pid):
                                is_stale = True
                except Exception:
                    pass

                try:
                    mtime = f.stat().st_mtime
                    if (time.time() - mtime) > 120.0:
                        is_stale = True
                except Exception:
                    pass

                if is_stale:
                    f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def clean_caches(
    workspace_root: Optional[Path] = None,
    clean_pycache: bool = True,
    clean_tmp_state: bool = True,
    clean_update_cache: bool = True,
    purge_daemons: bool = False,
    purge_servers: bool = False,
) -> Dict[str, Any]:
    """
    Clean stale Python bytecode, temporary server states, and update check caches.
    """
    cleaned_pycache_count = 0
    cleaned_tmp_count = 0
    cleaned_update_cache = False
    servers_stopped = {}

    if purge_daemons or purge_servers:
        servers_stopped = stop_all_voicefi_servers()

    # 1. Clean Python __pycache__ and .pyc files
    if clean_pycache:
        roots_to_scan = []
        if workspace_root and workspace_root.is_dir():
            roots_to_scan.append(workspace_root)
        else:
            roots_to_scan.append(Path(__file__).resolve().parent.parent.parent)
        
        voicefi_home = Path.home() / ".voicefi"
        if voicefi_home.is_dir():
            roots_to_scan.append(voicefi_home)

        for root in roots_to_scan:
            try:
                for pycache_dir in root.glob("**/__pycache__"):
                    try:
                        shutil.rmtree(pycache_dir, ignore_errors=True)
                        cleaned_pycache_count += 1
                    except Exception:
                        pass
                for pyc_file in root.glob("**/*.pyc"):
                    try:
                        pyc_file.unlink(missing_ok=True)
                        cleaned_pycache_count += 1
                    except Exception:
                        pass
            except Exception:
                pass

    # 2. Clean temporary state files in /tmp
    if clean_tmp_state:
        tmp_dir = Path("/tmp")
        try:
            for f in tmp_dir.glob("voicefi*"):
                try:
                    if f.is_file() or f.is_symlink():
                        f.unlink(missing_ok=True)
                        cleaned_tmp_count += 1
                except Exception:
                    pass
        except Exception:
            pass

    # 3. Clean update check cache
    if clean_update_cache:
        up_cache = Path.home() / ".voicefi" / ".update_check.json"
        if up_cache.is_file():
            up_cache.unlink(missing_ok=True)
            cleaned_update_cache = True

    return {
        "cleaned_pycache_count": cleaned_pycache_count,
        "cleaned_tmp_count": cleaned_tmp_count,
        "cleaned_update_cache": cleaned_update_cache,
        "servers_stopped": servers_stopped,
        "daemons_stopped": servers_stopped,
    }


def link_dev_environment(workspace_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Configure AI agent hooks (Antigravity and Claude Code) to point directly
    to the active project workspace's local virtualenv.
    """
    ws = workspace_dir or Path.cwd()
    venv_candidates = [
        ws / ".venv" / "bin" / "voicefi",
        ws / "venv" / "bin" / "voicefi",
        Path.home() / ".voicefi" / "venv" / "bin" / "voicefi",
    ]

    target_bin = None
    for cand in venv_candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK):
            target_bin = str(cand)
            break

    if not target_bin:
        target_bin = shutil.which("voicefi") or sys.executable

    # 1. Update Antigravity hooks.json
    gemini_hook_path = Path.home() / ".gemini" / "config" / "hooks.json"
    gemini_hook_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_data = {}
    if gemini_hook_path.is_file():
        try:
            hooks_data = json.loads(gemini_hook_path.read_text(encoding="utf-8")) or {}
        except Exception:
            hooks_data = {}

    hooks_data["voicefi-voice-layer"] = {
        "enabled": True,
        "Stop": [
            {
                "type": "command",
                "command": f"{target_bin} hook",
                "timeout": 60,
            }
        ],
    }
    gemini_hook_path.write_text(json.dumps(hooks_data, indent=2), encoding="utf-8")

    # Update plugin directory
    try:
        p_dir = Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "plugin.json").write_text(json.dumps({
            "name": "voicefi-plugin",
            "version": "1.0.0",
            "description": "VoiceFi Voice Layer lifecycle hooks for Antigravity AI coding agent.",
            "author": {"name": "VoiceFi"},
            "keywords": ["voice", "voicefi", "tts", "stt", "vad"],
        }, indent=2), encoding="utf-8")
        (p_dir / "hooks.json").write_text(json.dumps(hooks_data, indent=2), encoding="utf-8")

        g_cfg = Path.home() / ".gemini" / "config" / "config.json"
        if g_cfg.is_file():
            c_data = json.loads(g_cfg.read_text(encoding="utf-8")) or {}
            if "plugins" not in c_data:
                c_data["plugins"] = {}
            c_data["plugins"]["voicefi-plugin"] = {"enabled": True}
            g_cfg.write_text(json.dumps(c_data, indent=2), encoding="utf-8")
    except Exception:
        pass

    ws_agents_hook = ws / ".agents" / "hooks.json"
    if ws_agents_hook.parent.is_dir():
        try:
            ws_hooks = {}
            if ws_agents_hook.is_file():
                try:
                    ws_hooks = json.loads(ws_agents_hook.read_text(encoding="utf-8")) or {}
                except Exception:
                    ws_hooks = {}
            ws_hooks["voicefi-voice-layer"] = {
                "enabled": True,
                "Stop": [
                    {
                        "type": "command",
                        "command": f"{target_bin} hook",
                        "timeout": 60,
                    }
                ],
            }
            ws_agents_hook.write_text(json.dumps(ws_hooks, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 2. Update Claude Code hooks
    claude_settings_path = Path.home() / ".claude" / "settings.json"
    claude_settings_path.parent.mkdir(parents=True, exist_ok=True)
    claude_data = {}
    if claude_settings_path.is_file():
        try:
            claude_data = json.loads(claude_settings_path.read_text(encoding="utf-8")) or {}
        except Exception:
            claude_data = {}

    if "hooks" not in claude_data:
        claude_data["hooks"] = {}
    claude_data["hooks"]["Stop"] = [
        {
            "matcher": ".*",
            "hooks": [
                {
                    "type": "command",
                    "command": f"{target_bin} hook --agent claude",
                    "timeout": 60,
                }
            ],
        }
    ]
    claude_settings_path.write_text(json.dumps(claude_data, indent=2), encoding="utf-8")

    return {
        "target_binary": target_bin,
        "antigravity_hook": str(gemini_hook_path),
        "claude_hook": str(claude_settings_path),
    }
