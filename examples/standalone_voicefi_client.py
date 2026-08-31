#!/usr/bin/env python3
"""
Standalone VoiceFi Third-Party Integration Client.

Zero-internal-dependency Python client demonstrating plug-and-play voice interaction,
synthetic sound effects, status queries, and cross-agent command dispatch via:
1. HTTP REST API (Port 5141, default for companion server)
2. Stdio MCP JSON-RPC 2.0 Protocol (spawning `vifi mcp` or `python -m voicefi.mcp_server`)

Uses ONLY standard Python libraries (urllib.request, subprocess, json, sys, argparse, time, typing, os).
No VoiceFi packages or third-party dependencies required.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union


# ============================================================================
# Mode 1: HTTP REST API Client (Port 5141)
# ============================================================================


class VoiceFiRestClient:
    """
    Zero-dependency HTTP client for VoiceFi Companion Server (Port 5141).
    Provides synchronous methods for talking, sound effects, cross-agent dispatch, and diagnostics.
    """

    def __init__(self, host: str = "localhost", port: int = 5141, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform HTTP request against VoiceFi REST API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Accept": "application/json"}
        data_bytes = None

        if payload is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                if not resp_body.strip():
                    return {"status": "ok", "http_code": resp.status}
                return json.loads(resp_body)
        except urllib.error.HTTPError as he:
            body = he.read().decode("utf-8") if he.fp else ""
            try:
                err_json = json.loads(body)
                return {
                    "error": err_json.get("error", str(he)),
                    "http_code": he.code,
                    "details": err_json,
                }
            except Exception:
                return {"error": f"HTTP {he.code}: {he.reason}", "http_code": he.code, "raw": body}
        except urllib.error.URLError as ue:
            return {"error": f"Connection failed to {url}: {ue.reason}", "connection_error": True}
        except Exception as ex:
            return {"error": f"Request exception: {ex}"}

    def status(self) -> Dict[str, Any]:
        """Query VoiceFi companion server status and audio device profile."""
        return self._request("/api/status", method="GET")

    def speak(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        conv_id: Optional[str] = None,
        block: bool = True,
    ) -> Dict[str, Any]:
        """
        Synthesize and speak text aloud in active agent persona.

        Args:
            text: Text to speak.
            voice: Optional voice name/persona (e.g. 'Ava (Premium)', 'Viv', 'Steffan').
            rate: Optional speech rate (e.g. '+10%').
            conv_id: Optional active conversation ID to associate speech turn with.
            block: Whether the server should wait for audio playback to complete.
        """
        payload: Dict[str, Any] = {"text": text, "block": block}
        if voice:
            payload["voice"] = voice
        if rate:
            payload["rate"] = rate
        if conv_id:
            payload["conv_id"] = conv_id
        return self._request("/api/speak", method="POST", payload=payload)

    def sfx(
        self,
        name: str = "drum_smash",
        volume: float = 1.0,
        block: bool = True,
    ) -> Dict[str, Any]:
        """
        Play a procedural comedy or acoustic sound effect.

        Args:
            name: Sound effect name (drum_smash, honk, sad_trombone, applause, boing, crickets).
            volume: Volume multiplier (0.0 to 2.0).
            block: Whether to wait for audio to finish playing.
        """
        payload = {"name": name, "volume": volume, "block": block}
        return self._request("/api/sfx", method="POST", payload=payload)

    def stop(self) -> Dict[str, Any]:
        """Stop all active audio playback and microphone capture."""
        return self._request("/api/stop", method="POST", payload={})

    def send(
        self,
        text: str,
        to: str = "claude",
        conv_id: Optional[str] = None,
        reply: bool = False,
        sender_name: Optional[str] = "StandaloneClient",
        title: Optional[str] = None,
        from_conv_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dispatch cross-agent task, message, or findings to Antigravity or Claude Code.

        Args:
            text: Command or message text.
            to: Target engine ('antigravity' or 'claude').
            conv_id: Target conversation ID, or 'reply' to resolve return route.
            reply: If True, resolves reply route automatically from origin journal.
            sender_name: Attribution name for the sender.
            title: Custom title header in UI conversation transcript.
            from_conv_id: Originating conversation ID for bidirectional tracking.
        """
        target_conv = "reply" if reply else conv_id
        payload: Dict[str, Any] = {
            "text": text,
            "engine": to,
            "sender_name": sender_name,
        }
        if target_conv:
            payload["conv_id"] = target_conv
        if title:
            payload["title"] = title
        if from_conv_id:
            payload["from_conv_id"] = from_conv_id
        return self._request("/api/send", method="POST", payload=payload)


# ============================================================================
# Mode 2: Stdio MCP JSON-RPC 2.0 Client
# ============================================================================


class VoiceFiMCPClient:
    """
    Zero-dependency Stdio JSON-RPC 2.0 Model Context Protocol (MCP) client.
    Spawns VoiceFi MCP server process and manages tool calls (`voicefi_speak`, `voicefi_sfx`, `voicefi_send`, `voicefi_status`, `voicefi_stop`).
    """

    def __init__(
        self,
        command: Optional[Union[str, List[str]]] = None,
        timeout: float = 15.0,
    ):
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0

        if command is None:
            # Auto-detect vifi command or fallback to python module
            vifi_path = shutil.which("vifi")
            if vifi_path:
                self.command = [vifi_path, "mcp"]
            else:
                self.command = [sys.executable, "-m", "voicefi.mcp_server"]
        elif isinstance(command, str):
            self.command = command.split()
        else:
            self.command = list(command)

    def start(self) -> None:
        """Start the background MCP server subprocess and execute initialize handshake."""
        if self.process is not None and self.process.poll() is None:
            return

        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # 1. Send initialize request
        init_req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "standalone_voicefi_client", "version": "1.0.0"},
            },
        }
        resp = self._send_request(init_req)
        if "error" in resp:
            raise RuntimeError(f"MCP initialize failed: {resp['error']}")

        # 2. Send initialized notification
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        self._send_notification(notif)

    def close(self) -> None:
        """Gracefully close the MCP server subprocess."""
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_notification(self, notif: Dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("MCP process not running")
        line = json.dumps(notif) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def _send_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("MCP process not running")

        line = json.dumps(req) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

        # Read JSON-RPC response line
        start_t = time.time()
        while time.time() - start_t < self.timeout:
            if self.process.poll() is not None:
                err_out = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(
                    f"MCP server terminated unexpectedly with code {self.process.returncode}: {err_out}"
                )

            out_line = self.process.stdout.readline()
            if not out_line:
                time.sleep(0.02)
                continue

            try:
                msg = json.loads(out_line.strip())
                if isinstance(msg, dict) and msg.get("id") == req.get("id"):
                    return msg
            except json.JSONDecodeError:
                continue

        raise TimeoutError(f"MCP request {req.get('method')} timed out after {self.timeout}s")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available MCP tools exposed by VoiceFi."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = self._send_request(req)
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke a specific MCP tool by name."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        resp = self._send_request(req)
        if "error" in resp:
            return {"isError": True, "error": resp["error"]}
        return resp.get("result", {})

    def speak(
        self,
        text: str,
        persona: Optional[str] = None,
        agent_name: Optional[str] = "antigravity",
        conv_id: Optional[str] = None,
        block: bool = True,
    ) -> Dict[str, Any]:
        """Synthesize and speak text via MCP `voicefi_speak` tool."""
        args: Dict[str, Any] = {"text": text, "block": block}
        if persona:
            args["persona"] = persona
        if agent_name:
            args["agent_name"] = agent_name
        if conv_id:
            args["conv_id"] = conv_id
        return self.call_tool("voicefi_speak", args)

    def sfx(self, name: str = "drum_smash", volume: float = 1.0) -> Dict[str, Any]:
        """Play a sound effect via MCP `voicefi_sfx` tool."""
        return self.call_tool("voicefi_sfx", {"name": name, "volume": volume})

    def stop(self) -> Dict[str, Any]:
        """Stop all speech via MCP `voicefi_stop` tool."""
        return self.call_tool("voicefi_stop", {})

    def status(self) -> Dict[str, Any]:
        """Query status via MCP `voicefi_status` tool."""
        return self.call_tool("voicefi_status", {})

    def send(
        self,
        text: str,
        to: str = "antigravity",
        conv_id: Optional[str] = None,
        reply: bool = False,
        sender: Optional[str] = "StandaloneMCPClient",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch cross-agent task via MCP `voicefi_send` tool."""
        args: Dict[str, Any] = {
            "text": text,
            "to": to,
            "reply": reply,
            "sender": sender,
        }
        if conv_id:
            args["conv_id"] = conv_id
        if title:
            args["title"] = title
        return self.call_tool("voicefi_send", args)


# ============================================================================
# Demo Routine
# ============================================================================


def run_integration_demo(
    mode: str = "rest", host: str = "localhost", port: int = 5141, mcp_cmd: Optional[str] = None
) -> bool:
    """Run a comprehensive walkthrough of VoiceFi capabilities across the selected protocol."""
    print("=" * 70)
    print(f"🎙️  VoiceFi Standalone Integration Client Demo (Protocol Mode: {mode.upper()})")
    print("=" * 70)

    if mode == "rest":
        client = VoiceFiRestClient(host=host, port=port)
        print(f"\n[1/5] Checking Server Status via HTTP REST ({client.base_url}/api/status)...")
        st = client.status()
        if "error" in st:
            print(f"⚠️ Status warning: {st.get('error')}")
        else:
            print(f"✅ Server Status: {json.dumps(st, indent=2)}")

        print("\n[2/5] Synthesizing Voice Speech (POST /api/speak)...")
        sp_res = client.speak(
            "Hello! This is a test from the VoiceFi standalone REST client.", block=True
        )
        print(f"Result: {json.dumps(sp_res)}")

        print("\n[3/5] Playing Algorithmic Sound Effect (POST /api/sfx 'drum_smash')...")
        sfx_res = client.sfx("drum_smash", volume=0.8, block=True)
        print(f"Result: {json.dumps(sfx_res)}")

        print("\n[4/5] Testing Cross-Agent Task Dispatch (POST /api/send to Antigravity)...")
        send_res = client.send(
            "Echo test message from standalone REST client",
            to="antigravity",
            title="Integration Demo",
        )
        print(f"Result: {json.dumps(send_res)}")

        print("\n[5/5] Testing Stop Audio Cancellation (POST /api/stop)...")
        stop_res = client.stop()
        print(f"Result: {json.dumps(stop_res)}")

    else:
        print("\n[1/5] Initializing Stdio MCP Client...")
        with VoiceFiMCPClient(command=mcp_cmd) as mcp:
            tools = mcp.list_tools()
            tool_names = [t.get("name") for t in tools]
            print(f"✅ Discovered {len(tools)} MCP Tools: {', '.join(tool_names)}")

            print("\n[2/5] Querying System Status via MCP 'voicefi_status'...")
            st_res = mcp.status()
            print(f"Result: {json.dumps(st_res, indent=2)}")

            print("\n[3/5] Synthesizing Voice Speech via MCP 'voicefi_speak'...")
            sp_res = mcp.speak(
                "Greetings! This is a test from the VoiceFi standalone MCP client.", block=True
            )
            print(f"Result: {json.dumps(sp_res)}")

            print("\n[4/5] Playing Sound Effect via MCP 'voicefi_sfx' ('applause')...")
            sfx_res = mcp.sfx("applause", volume=0.8)
            print(f"Result: {json.dumps(sfx_res)}")

            print("\n[5/5] Dispatching Cross-Agent Message via MCP 'voicefi_send'...")
            send_res = mcp.send(
                "Task dispatched via Stdio MCP client", to="antigravity", title="MCP Integration"
            )
            print(f"Result: {json.dumps(send_res)}")

    print("\n✨ Demo completed successfully!")
    return True


# ============================================================================
# CLI Entrypoint
# ============================================================================


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standalone VoiceFi Third-Party Integration Client (REST / MCP Stdio)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check status via REST
  python standalone_voicefi_client.py --mode rest --status

  # Speak text aloud via Port 5141 REST API
  python standalone_voicefi_client.py --mode rest --speak "Deployment complete!"

  # Play comedy sound effect
  python standalone_voicefi_client.py --mode rest --sfx drum_smash

  # Dispatch command to Antigravity via Stdio MCP
  python standalone_voicefi_client.py --mode mcp --send "Review the latest changes" --to antigravity

  # Reply to originating conversation
  python standalone_voicefi_client.py --mode rest --send "Refactoring complete! All tests pass." --to antigravity --reply

  # Run full automated walkthrough
  python standalone_voicefi_client.py --demo --mode rest
""",
    )

    parser.add_argument(
        "--mode",
        choices=["rest", "mcp"],
        default="rest",
        help="Protocol mode: 'rest' (HTTP Port 5141) or 'mcp' (Stdio JSON-RPC 2.0). Default: rest",
    )
    parser.add_argument("--speak", type=str, metavar="TEXT", help="Synthesize and speak text aloud")
    parser.add_argument(
        "--sfx",
        type=str,
        metavar="NAME",
        help="Play sound effect (drum_smash, honk, sad_trombone, applause, boing, crickets)",
    )
    parser.add_argument(
        "--send", type=str, metavar="TEXT", help="Dispatch task or message across agents"
    )
    parser.add_argument(
        "--to",
        choices=["antigravity", "claude"],
        default="claude",
        help="Target agent engine for dispatch (default: claude)",
    )
    parser.add_argument(
        "--reply", action="store_true", help="Resolve and reply to originating conversation route"
    )
    parser.add_argument("--conv-id", type=str, metavar="ID", help="Explicit target conversation ID")
    parser.add_argument(
        "--sender", type=str, default="StandaloneClient", help="Sender attribution name"
    )
    parser.add_argument("--title", type=str, help="Message title header")
    parser.add_argument(
        "--voice", "--persona", type=str, dest="persona", help="Voice persona override"
    )
    parser.add_argument("--volume", type=float, default=1.0, help="SFX volume (0.0 to 2.0)")
    parser.add_argument(
        "--status", action="store_true", help="Query server status and audio devices"
    )
    parser.add_argument("--stop", action="store_true", help="Stop active speech playback")
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="VoiceFi REST server host (default: localhost)",
    )
    parser.add_argument(
        "--port", type=int, default=5141, help="VoiceFi REST server port (default: 5141)"
    )
    parser.add_argument(
        "--mcp-cmd", type=str, help="Custom MCP server command override (e.g. 'vifi mcp')"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw machine-readable JSON result"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Execute complete automated capabilities demo"
    )

    args = parser.parse_args(argv)

    if args.demo:
        try:
            run_integration_demo(
                mode=args.mode, host=args.host, port=args.port, mcp_cmd=args.mcp_cmd
            )
            return 0
        except Exception as e:
            print(f"❌ Demo execution error: {e}", file=sys.stderr)
            return 1

    # Check if any action was specified
    actions = [args.speak, args.sfx, args.send, args.status, args.stop]
    if not any(actions):
        parser.print_help()
        return 0

    try:
        if args.mode == "rest":
            rest_client = VoiceFiRestClient(host=args.host, port=args.port, timeout=args.timeout)

            if args.status:
                res = rest_client.status()
                print(json.dumps(res, indent=2) if args.json else f"Status: {res}")

            if args.speak:
                res = rest_client.speak(args.speak, voice=args.persona, conv_id=args.conv_id)
                print(json.dumps(res, indent=2) if args.json else f"Speak: {res}")

            if args.sfx:
                res = rest_client.sfx(args.sfx, volume=args.volume)
                print(json.dumps(res, indent=2) if args.json else f"SFX: {res}")

            if args.send:
                res = rest_client.send(
                    text=args.send,
                    to=args.to,
                    conv_id=args.conv_id,
                    reply=args.reply,
                    sender_name=args.sender,
                    title=args.title,
                )
                print(json.dumps(res, indent=2) if args.json else f"Send: {res}")

            if args.stop:
                res = rest_client.stop()
                print(json.dumps(res, indent=2) if args.json else f"Stop: {res}")

        else:  # MCP mode
            with VoiceFiMCPClient(command=args.mcp_cmd, timeout=args.timeout) as mcp_client:
                if args.status:
                    res = mcp_client.status()
                    print(json.dumps(res, indent=2) if args.json else f"Status: {res}")

                if args.speak:
                    res = mcp_client.speak(args.speak, persona=args.persona, conv_id=args.conv_id)
                    print(json.dumps(res, indent=2) if args.json else f"Speak: {res}")

                if args.sfx:
                    res = mcp_client.sfx(args.sfx, volume=args.volume)
                    print(json.dumps(res, indent=2) if args.json else f"SFX: {res}")

                if args.send:
                    res = mcp_client.send(
                        text=args.send,
                        to=args.to,
                        conv_id=args.conv_id,
                        reply=args.reply,
                        sender=args.sender,
                        title=args.title,
                    )
                    print(json.dumps(res, indent=2) if args.json else f"Send: {res}")

                if args.stop:
                    res = mcp_client.stop()
                    print(json.dumps(res, indent=2) if args.json else f"Stop: {res}")

        return 0
    except Exception as ex:
        print(f"❌ Error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
