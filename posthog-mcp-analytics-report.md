# PostHog MCP Analytics — Integration Report

## Summary

VoiceFi's MCP server (`src/voicefi/mcp_server.py`) is a hand-rolled STDIO JSON-RPC 2.0 custom dispatcher — it speaks the MCP protocol directly with no `@modelcontextprotocol/sdk` or `fastmcp` server object to wrap. The integration follows **Path P2** (custom dispatcher) using `PostHogMCP` from `posthog.mcp`.

Every tool call and initialize handshake now emits standard `$mcp_*` events to PostHog.

## Changes Made

### Files Modified

| File | Change |
|------|--------|
| `src/voicefi/mcp_server.py` | Added PostHog MCP analytics instrumentation |

### Files Created

| File | Change |
|------|--------|
| `.env` | Added `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` environment variables |

### What Was Added to `mcp_server.py`

1. **`signal` import** — needed for the SIGTERM shutdown handler.

2. **Module-scope `PostHogMCP` client** — constructed once at import time, reading credentials from env vars (`POSTHOG_PROJECT_TOKEN` → `POSTHOG_API_KEY` → existing VoiceFi default). Guarded by `try/except` so a missing `posthog.mcp` or bad credentials never break the server.

3. **`capture_initialize` call** in the `initialize` handler — fires on every MCP session handshake, recording the connecting client's name and version (e.g. `claude-code`, `cursor`).

4. **`capture_tool_call` call** in `execute_tool`'s `finally` block — fires after every tool call (success or error), capturing tool name, parameters, response, duration, and error state alongside the existing VoiceFi telemetry.

5. **SIGTERM shutdown handler** in `run_stdio()` — calls `_mcp_posthog.shutdown()` on graceful termination so no queued events are dropped.

## SDK Version

`posthog>=7.43.0` was already a dependency in `pyproject.toml` (requirement is `>=7.21`). No package installation was needed.

## Environment Variables

Written to `.env` (already covered by `.gitignore`):

```
POSTHOG_PROJECT_TOKEN=phc_oFyLfqmnEeFMDehRQ4DzGrN9AGctauZiZhfufRtmW92e
POSTHOG_HOST=https://us.i.posthog.com
```

The code reads these at startup via `os.environ.get(...)`.

## Events You'll See in PostHog

Once the MCP server handles its next request, you'll see these events in your PostHog project:

| Event | When |
|-------|------|
| `$mcp_initialize` | Every new MCP client connection |
| `$mcp_tool_call` | Every tool call (success or error) |

Each `$mcp_tool_call` event includes:
- `$mcp_tool_name` — e.g. `voicefi_speak`, `voicefi_listen`
- `$mcp_duration_ms` — tool execution time
- `$mcp_is_error` — whether the call failed
- `$mcp_parameters` — the arguments passed by the agent
- `$mcp_response` — the tool's response content

## Next Steps

1. **Load the env vars** — the MCP server process must inherit `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST`. Either source `.env` before launching, or export them in your shell profile / MCP host config.

2. **Trigger a tool call** — run `vifi mcp` and call any tool (e.g. `voicefi_status`) from an MCP client. Events appear in PostHog within a few seconds.

3. **View events** — open [PostHog → Events](https://us.posthog.com/project/574817/events) and filter by `$mcp_tool_call` or `$mcp_initialize`.

4. **Build a dashboard** — see https://posthog.com/docs/mcp-analytics for the recommended dashboard template covering tool usage, error rates, and latency.
