# Architectural Lessons Learned — Remote Companion Voice Loop & Concurrency Guardrails

Universal Voice Layer for AI Agents, MCP, and macOS.

---

## Executive Summary

During the field deployment and acoustic verification of the **VoiceFi Remote Companion** (`https://companion.voicefi.app`), subtle race conditions, client-server feedback loops, and cache invalidation traps were diagnosed and resolved. This document captures the **6 core architectural lessons and invariants** required to maintain flawless hands-free voice loops across desktop and mobile devices.

---

## 1. The "Stop Echo" Hazard in Bidirectional WebSockets

### The Failure Mode
When an agent speech turn finished on the host Mac, the backend server broadcasted a lifecycle event:
```json
{"type": "speech_stopped"}
```
On the web client, the incoming event was received by `handleServerEvent()`:
```javascript
// ❌ ANTI-PATTERN: Receiver routine triggers an outbound command
case 'speech_stopped':
case 'stop':
    stopAllAgentSpeech(); // This function cleaned audio AND sent POST /api/stop + {type: 'stop'}!
    break;
```
Inside `stopAllAgentSpeech()`, the code was designed to handle user-initiated cancellations (like pressing a stop button). Consequently, it issued:
1. An HTTP `POST /api/stop` to the local daemon.
2. A WebSocket frame `{"type": "stop"}` back to the server.

The server received this client cancellation, executed its stop handler, updated `/tmp/voicefi_last_speech_stop.ts` to `time.time()`, and broadcasted another `{"type": "speech_stopped"}` event.

### The Consequence
This created an **infinite ping-pong loop** executing ~11 times per second (244 calls in a few seconds). Because `/tmp/voicefi_last_speech_stop.ts` was continuously refreshed with the current timestamp, any subsequent speech turn was evaluated as having started *before* the latest cancellation request. The audio player or sentence pipeliner aborted playback after ~1 second.

### Architectural Invariant
**Decouple state reception from command dispatch.** Handlers processing server state notifications must execute purely local teardown (stopping WebAudio nodes, resetting UI states) and must **NEVER** echo a cancellation or mutation command back to the upstream authority.

```javascript
// ✅ CORRECT PATTERN: Guard flag differentiates local cleanup from command dispatch
function stopAllAgentSpeech(broadcastServer = true) {
    // 1. Clean up local WebAudio & HTML5 audio nodes
    if (activeAudioNode) {
        activeAudioNode.pause();
        activeAudioNode = null;
    }
    setCompanionState('idle');

    // 2. Only notify server if this was a USER-initiated action
    if (broadcastServer) {
        fetch('/api/stop', { method: 'POST' }).catch(() => {});
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'stop' }));
        }
    }
}

// When receiving server telemetry:
case 'speech_stopped':
case 'stop':
    stopAllAgentSpeech(false); // Strictly local teardown
    break;
```

---

## 2. Lock Timestamps Must Be Sampled *Inside* the Mutex

### The Failure Mode
In the speech synthesis engines (`edge_tts.py`, `mac_say.py`, `gemini_tts.py`), speech playback is guarded by a file/process lock (`speech_turn_lock`) to serialize audio turns across subagents, hooks, and manual triggers:

```python
# ❌ ANTI-PATTERN: Timestamp captured before entering the queue
turn_start_time = time.time()
self._stop_requested = False

with speech_turn_lock("/tmp/voicefi_speech.lock"):
    # Play sentences...
    if last_stop_timestamp > turn_start_time:
        abort_speech()
```

When Turn A was speaking and Turn B was queued, Turn B recorded `turn_start_time` while waiting outside the mutex. When Turn A completed, the server stamped the stop timestamp. Turn B finally acquired the lock, but its `turn_start_time` was already older than Turn A's stop timestamp. Turn B evaluated `last_stop_timestamp > turn_start_time` as `True` and immediately aborted without speaking!

### Architectural Invariant
**In queued concurrency pipelines, interruption timestamps must be sampled immediately upon entering the critical section**, not when the job was submitted or enqueued.

```python
# ✅ CORRECT PATTERN: Re-arm timestamp and reset cancellation inside the lock
with speech_turn_lock("/tmp/voicefi_speech.lock"):
    turn_start_time = time.time()
    self._stop_requested = False

    # Now evaluate interruption relative to actual execution start
    if last_stop_timestamp > turn_start_time:
        abort_speech()
```

---

## 3. Multi-Sentence Pipelining as the Canary for Race Conditions

### The Failure Mode
Single-sentence agent replies (under ~10 words) often played synchronously and finished before cancellation race conditions could manifest. 

However, multi-sentence turns (such as jokes with a setup and punchline separated by `?` or `.`) activate VoiceFi's sentence pipeliner:
1. Sentence 1 streams immediately over `afplay`.
2. Sentence 2 is pre-fetched asynchronously in a background worker thread (`_fetcher`) and pushed to an `audio_queue`.
3. The queue worker checks `/tmp/voicefi_last_speech_stop.ts` between sentence chunks.

Because the queue worker explicitly verifies timestamps across chunk boundaries, any background stop ping-pong loop killed the queue right after Sentence 1, reliably cutting off the punchline.

### Architectural Invariant
Never assume voice streaming works based solely on single-sentence verification. **Always include multi-sentence phrases with distinct punctuation pauses (setup + pause + punchline) in automated test suites and field validation.**

---

## 4. Defensive Server-Side Debouncing on Destructive Endpoints

### The Failure Mode
Even with client-side loop prevention, mobile devices operating on lossy cellular networks frequently experience packet re-transmissions, rapid UI double-taps, or WebSocket reconnection bursts that can send redundant stop calls in rapid succession.

### Architectural Invariant
Destructive lifecycle endpoints (`POST /api/stop`, `{"type": "stop"}`) must enforce server-side sliding window debouncing.

```python
# In voicefi/companion/server.py
_last_stop_processed = 0.0
STOP_DEBOUNCE_INTERVAL = 0.5  # 500ms sliding threshold

async def handle_stop(request):
    global _last_stop_processed
    now = time.time()
    if now - _last_stop_processed < STOP_DEBOUNCE_INTERVAL:
        return web.json_response({"status": "debounced"})
    _last_stop_processed = now

    # Proceed with actual hardware audio termination and lock stamping
    stop_all_speech()
    return web.json_response({"status": "stopped"})
```

---

## 5. Mobile PWA Service Worker Cache Persistence

### The Failure Mode
Progressive Web Apps installed on iOS Safari and Android Chrome aggressively cache the Service Worker script (`sw.js`) and application shell (`index.html`). 

During live testing, server-side fixes and fresh deployments to Cloudflare were completely bypassed on the user's mobile device because the PWA continued executing the old ping-ponging client code cached in CacheStorage `v18`.

### Architectural Invariant
1. **Atomic Version Bumps:** Any modification to companion client logic must bump the service worker cache version (e.g. `CACHE_NAME = 'voicefi-companion-v20'`).
2. **Immediate Activation:** Service workers must claim active clients immediately using `self.skipWaiting()` in `install` and `clients.claim()` in `activate`.
3. **Cache Purge on Activate:** The `activate` event must iterate and delete all stale cache keys not matching the active `CACHE_NAME`.

---

## 6. Dual-Acoustic Ground Truth (Never Mute During Field Debugging)

### The Failure Mode
If Mac desktop audio is muted whenever the mobile companion connects (`mute_mac_when_companion_active: true`), a failure in mobile WebSocket audio delivery causes complete silence. It becomes impossible to tell whether:
- The LLM turn detection failed.
- The Antigravity / Claude hook didn't trigger.
- Transcript extraction failed.
- EdgeTTS synthesis failed.
- Or mobile WebSocket streaming failed.

### Architectural Invariant
Keep `mute_mac_when_companion_active: false` during development and field trials. The Mac desktop speakers serve as an **independent physical canary**. If the Mac speaks the soundbite clearly, you immediately know the entire LLM, transcript watcher, hook, and TTS synthesis pipeline are 100% healthy, isolating the issue purely to mobile transport and client state.

---

## Summary Checklist for Companion Development

| Rule | Area | Requirement |
| :--- | :--- | :--- |
| **No Echo** | Client JS | Pass `broadcastServer = false` when cleaning up from server-initiated events. |
| **Inside Mutex** | Python TTS | Set `turn_start_time = time.time()` and `_stop_requested = False` *inside* `speech_turn_lock`. |
| **Sentence Stress** | QA Testing | Always test with multi-sentence dialogue (setup + punchline). |
| **Debounce** | Python Server | Enforce 500ms sliding threshold on `/api/stop` and WebSocket stop messages. |
| **SW Version** | PWA Edge | Increment `CACHE_NAME` in `sw.js` and purge stale caches on every client change. |
| **Dual Canary** | Config | Keep `mute_mac_when_companion_active: false` until production stability is verified. |
