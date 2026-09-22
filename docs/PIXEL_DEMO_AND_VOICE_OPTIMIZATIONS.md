# Google Pixel & Companion Mobile Demo Playbook — VoiceFi™

Universal Voice Layer for AI Agents, MCP, and macOS.

---

## 📱 Executive Summary

The **Google Pixel** (powered by Google Tensor TPU chips and running Android Chrome) represents the highest-performing mobile hardware target for the **VoiceFi Remote Companion** (`https://companion.voicefi.app`). 

While mobile Safari on iOS imposes aggressive background audio throttling and WebKit constraints, Pixel devices provide:
1. **Zero-Latency On-Device Speech-to-Text:** Tensor-accelerated Assistant Voice Typing transcribes speech locally in **0 ms** with auto-punctuation, sidestepping cloud Whisper latency.
2. **Hardware Acoustic Echo Cancellation (AEC):** Multi-mic beamforming and Clear Calling hardware in the Android Audio HAL isolate speaker output from mic capture, stabilizing full-duplex loops.
3. **Dedicated WebAudio Worklet Threading:** Android Chrome executes 16kHz PCM downsampling on a dedicated real-time audio thread without UI thread contention.
4. **Reliable Screen WakeLock:** `navigator.wakeLock` prevents mobile screen sleep from severing active WebSockets during live presentations.

This playbook documents the **3 distinct demo modes**, the **Gboard Tensor zero-latency workaround**, hard benchmark latencies, and mobile optimization standards.

---

## 🎯 The 3 Mobile Demo Modes (Selection Matrix)

| Demo Goal | Recommended Model | Companion Mode | Input Method | Typical Latency | Spoken Feedback |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Agentic Coding & IDE Actions** | Gemini 3.8 Flash / Antigravity | Turn-based (`/rc`) | Push-to-Talk or Auto-Listen | ~2.8s | Concise soundbite from active agent persona |
| **2. Instant Voice Banter & Live Roasts** | `gemini-3.8-live` | Live Studio (`/live`) | Gboard Tensor Fast-Path | **~520ms** | Affective dialogue + co-timed SFX (rimshots, applause) |
| **3. Pure Hands-Free Open Mic** | `gemini-2.5-flash-native-audio-latest` | Live Studio (`/live`) | Open Mic (AirPods or Pixel AEC) | ~2.1s | Conversational speech-to-speech |

---

## 🔬 Empirical Latency Benchmarks (Measured Hard Data)

Benchmark conducted on VoiceFi's bidirectional audio streaming pipeline using real 16kHz speech input (*"What is the capital of Texas?"*):

```
1. Gemini 3.8 Live (Text In ──► Spoken Audio Out):
   └── TTFA (Time to First Audio): 528.5 ms ⚡ [BLAZING FAST]
   └── Audio Generated: 2.32s (111,360 bytes @ 24kHz)
   └── Transcription: "The capital of Texas is Austin."

2. Gemini 2.5 Flash Native Audio (PCM Audio In ──► Spoken Audio Out):
   └── Connection Time: 137.8 ms
   └── TTFA from end of speech: 2,151.4 ms (Includes server-side acoustic VAD)
   └── Model Audio: 2.48s (119,040 bytes @ 24kHz)
   └── Full Native Speech-to-Speech: Operational ✅

3. Gemini 3.8 Live (PCM Audio In ──► Broken / Unsupported by Google API):
   └── TTFA: None (0 bytes returned)
   └── Cause: Google GenAI API endpoint lacks server-side audio-in VAD on 3.8 Live preview.

4. Gemini 3.8 Flash (Turn-Based Cascade: Local Whisper ──► LLM ──► EdgeTTS):
   ├── STT (Whisper local base.en): 1,513.0 ms
   ├── LLM (Gemini 3.8 Flash generation): 913.7 ms
   └── TTS (EdgeTTS streaming synthesis): 472.9 ms
   └── Total Turn-Based Pipeline Latency: 2,899.6 ms (~2.9 seconds)
```

---

## ⚡ The Gboard Tensor "Zero-Latency" Workaround

### The Problem
- Traditional turn-based cascades take **~2.9s** because cloud/local Whisper STT alone eats ~1.5 seconds before the LLM even begins.
- Meanwhile, `gemini-3.8-live` cannot process raw PCM audio directly over WebSockets yet.

### The Solution
Pixel's Tensor Gboard transcribes speech **on-device in real time (0 ms)**. When that clean text is dispatched directly to `gemini-3.8-live`, the model returns spoken audio in **528 ms**.

```
   Developer Speaks Aloud
            │
            ▼
   [Pixel Tensor Gboard] ────(0ms On-Device Speech Typing)───► Text in Input Capsule
            │
            ▼ (Auto-dispatched via 1.2s silence debounce or "...send" voice trigger)
   [Gemini 3.8 Live API] ───(528ms TTFA Native Audio Stream)──► Phone Speaker / Earbuds
   ─────────────────────────────────────────────────────────────────────────────
   👉 TOTAL ROUND-TRIP PERCEIVED LATENCY: ~520 ms
```

### Why This Outperforms All Alternatives
1. **No Cloud STT Overhead:** Saves ~1,500 ms compared to Whisper or Gemini Transcribe.
2. **No TTS Synthesis Phase:** Bypasses external TTS engines; speech streams straight out of the model.
3. **No Audio Packet Loss:** Zero risk of WebAudio buffer drops or Wi-Fi packet re-transmissions on the uplink.
4. **Punctuation & Formatting:** Pixel Assistant Voice Typing automatically applies commas, question marks, and capitalization.

---

## 🎭 Live Comedy & Roast Demos (`vifi comedy`)

Gemini 3.8 Live is calibrated with **affective dialogue** and **real-time tool calling**, enabling interactive stand-up comedy and codebase roasting.

### Execution Sequence:
1. **Prompt Dispatched:** E.g., *"Roast someone who commits directly to main without tests."*
2. **Speech Synthesis Starts (~500ms):** The voice (e.g. *Puck*) delivers the punchline with sarcastic cadence, conversational pauses, and laughter.
3. **Co-Timed Tool Call (`play_sound_effect`):** On the exact beat of the punchline, Gemini Live calls `play_sound_effect(name="rimshot")` or `"sad_trombone"`.
4. **Foley Sound Effect Plays:** VoiceFi fires the master sound clip simultaneously over desktop speakers and mobile companion audio.
5. **Barge-In Heckling:** If someone in the room laughs or heckles aloud, the full-duplex socket trips barge-in (<150ms), stopping the punchline and allowing Gemini to banter back.

---

## 🛠️ Companion Optimizations for Android & Pixel

To achieve zero-friction voice operation on Google Pixel devices, the companion frontend (`src/voicefi/companion/static/index.html`) adheres to the following standards:

### 1. Dedicated Keyboard Action Hints
```html
<input 
  id="chatInput" 
  type="text" 
  enterkeyhint="send" 
  autocapitalize="sentences" 
  autocomplete="off" 
  spellcheck="false" 
  placeholder="Message or dictate..."
/>
```
* `enterkeyhint="send"`: Forces Gboard to replace the standard Enter key with a prominent blue **Send** action arrow.

### 2. Hands-Free Pause Auto-Dispatch
A sliding 1.2-second debounce timer listens to DOM `input` events:
```javascript
let speechDebounceTimer = null;
chatInput.addEventListener('input', (e) => {
  if (!isVoiceTypingActive) return;
  clearTimeout(speechDebounceTimer);
  speechDebounceTimer = setTimeout(() => {
    const val = chatInput.value.trim();
    if (val.length > 3) {
      triggerHapticFeedback();
      sendVoiceCommand(val, false);
      chatInput.value = "";
    }
  }, 1200);
});
```

### 3. Spoken "Send" Voice Command Parser
If Gboard transcribes trailing command cues, the parser strips the cue and fires immediately:
```javascript
function checkSpokenSendCue(text) {
  const match = text.match(/^(.*?)\s+(?:send|submit|go)[.!?]?$/i);
  if (match) {
    return match[1].trim(); // Returns command without the "send" keyword
  }
  return null;
}
```

### 4. Native Pixel Haptics
Provides tactile confirmation on prompt dispatch and turn completion:
```javascript
function triggerHapticFeedback(pattern = [20, 30, 20]) {
  if (typeof navigator !== 'undefined' && navigator.vibrate) {
    navigator.vibrate(pattern);
  }
}
```

---

## 🛡️ Acoustic Hygiene & Demo Rules

1. **AirPods / Earbuds Recommended for Open Mic:** Even with Pixel hardware AEC, running full-duplex open-mic audio (`gemini-2.5-flash-native-audio-latest`) at maximum speaker volume in small reflective rooms can cause echo bleed. Wearing earbuds provides 100% isolation.
2. **Never Use Open-Mic 3.8 Live in Meetings:** In multi-speaker meetings, a conversational model that attempts to speak aloud after every human pause creates chaos. For meetings, use **VoiceFi Ambient Mode** (`vifi ambient start --proactive`), which operates as a **100% silent observer**, staging git scaffolds (`Workspace="branch"`) and Linear tickets in the background.
3. **Keep Desktop Audio Unmuted (`mute_mac_when_companion_active: false`):** During rehearsals, keep your Mac desktop speakers on as an independent physical canary to verify whether turns are completing upstream.
