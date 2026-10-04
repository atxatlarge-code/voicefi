"""
title: Local Bug Solver
author: VoiceFi
author_url: https://voicefi.org
version: 1.0.0
description: Fix codebase bugs on your Mac using local models on Apple Silicon Metal GPU (Gemma 4 2B/26B) with self-healing test verification.
"""

import json
import urllib.request
import urllib.error
from typing import Optional
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        bridge_url: str = Field(
            default="http://host.docker.internal:5141/api/fix",
            description="URL of the local VoiceFi fix bridge on host machine",
        )
        default_model_scout: str = Field(
            default="gemma4-2b",
            description="Local model for Recon Scout",
        )
        default_model_coder: str = Field(
            default="gemma4-26b",
            description="Local model for code modification",
        )

    def __init__(self):
        self.valves = self.Valves()

    def fix_local_bug(
        self,
        target_file: str,
        error_or_traceback: str,
        test_command: Optional[str] = None,
    ) -> str:
        """
        Pass a bug, traceback, or test failure to local on-device models to solve and verify.

        :param target_file: Path to the file to modify on the host (e.g., src/voicefi/engine.py or full path).
        :param error_or_traceback: The traceback, error message, or explanation of what to fix.
        :param test_command: Optional verification test command (e.g., 'pytest tests/test_engine.py').
        :return: Unified git diff, verification status, and tokens saved.
        """
        payload = json.dumps(
            {
                "target": target_file,
                "error": error_or_traceback,
                "test": test_command or "",
                "apply": True,
                "model_scout": self.valves.default_model_scout,
                "model_coder": self.valves.default_model_coder,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self.valves.bridge_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

                if data.get("error") and not data.get("diff"):
                    return f"❌ Fix failed: {data.get('error')}"

                status_emoji = "✅" if data.get("applied") else "⚠️"
                diff_block = data.get("diff", "No diff produced")
                tokens_saved = data.get("tokens_saved", 0)
                savings_pct = data.get("savings_pct", 0)
                duration = data.get("total_duration", 0)

                msg = [
                    f"### {status_emoji} Local Fix Applied to `{data.get('target')}`",
                    f"- **Duration:** {duration}s",
                    f"- **Token Savings:** {tokens_saved} tokens ({savings_pct}% context preserved)",
                ]

                if data.get("test_passed") is not None:
                    test_status = "PASSED ✅" if data.get("test_passed") else "FAILED ❌"
                    msg.append(f"- **Verification:** {test_status}")
                    if data.get("test_output"):
                        msg.append(f"\n```text\n{data.get('test_output')}\n```")

                msg.append(f"\n```diff\n{diff_block}\n```")
                return "\n".join(msg)

        except urllib.error.URLError as e:
            return f"❌ Could not connect to VoiceFi host bridge at {self.valves.bridge_url}: {e}"
        except Exception as e:
            return f"❌ Unexpected error while communicating with host bridge: {e}"
