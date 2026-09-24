# 🎙️ Google AI Studio Speech Generator: Voice Testing & Creative Showcase

> **Resource Bookmark & Benchmark Suite for Expressive AI Speech Synthesis**  
> *Target Models: Gemini 3.1 Flash TTS & Gemini 3.8 Live* • *Status: Active Reference*  
> *Direct Studio Link:* [Google AI Studio — Generate Speech](https://aistudio.google.com/generate-speech)

---

## 📌 Bookmark & Access Links

| Resource | URL |
| :--- | :--- |
| **Direct Speech Studio** | [https://aistudio.google.com/generate-speech](https://aistudio.google.com/generate-speech) |
| **Session Preset Link** | [Open AI Studio Speech Generator](https://aistudio.google.com/generate-speech?_gl=1*bit3po*_ga*NzI2ODUwNTcuMTc5MDA1MDAwMQ..*_ga_P1DBVKWT6V*czE3OTAwNTAwMDAkbzEkZzEkdDE3OTAwNTA1MjckajYwJGwwJGgxMzU0MDY3Nzk5) |
| **VoiceFi Gemini TTS Engine** | [`src/voicefi/tts/gemini_tts.py`](../src/voicefi/tts/gemini_tts.py) |
| **VoiceFi Live Studio** | `vifi live` / `vifi -l` / [`scripts/gemini_live_comedian.py`](../scripts/gemini_live_comedian.py) |

---

## 🎭 Prebuilt Neural Voice Matrix

Google's Gemini speech generation engine features a library of 30+ multilingual voices with distinct acoustic personas. The core primary English personas mapped to VoiceFi roles include:

| Voice | Tone Profile | Acoustic Traits | Recommended VoiceFi Role |
| :--- | :--- | :--- | :--- |
| **Aoede** | *Breezy & Expressive* | Polished, bright, modern conversational warmth with exceptional emotional range. | **Primary Planner / Antigravity Lead (`Viv`)** |
| **Puck** | *Upbeat & Agile* | Quick-witted, playful, energetic, natural comedic timing and punchiness. | **Pair Programmer / Claude Code / QA Alerts** |
| **Charon** | *Deep & Informative* | Low-frequency resonance, authoritative, measured gravitas, documentary depth. | **Architect / Security Auditor / Attenborough Narrator** |
| **Kore** | *Firm & Grounded* | Calming, balanced, focused, soothing cadence ideal for continuous listening. | **Deep Focus / Code Reviewer / SRE Lead** |
| **Fenrir** | *Excitable & Dynamic* | Powerful, gritty, urgent, high dynamic range for tense or high-stakes scenarios. | **Incident Commander / Production Alert War Room** |

---

## 🎬 Incredible Audition Examples & Creative Prompts

Copy and paste these prompts directly into the [Google AI Studio Speech Generator](https://aistudio.google.com/generate-speech) to benchmark emotional nuance, breath control, multi-speaker dialogue, and technical articulation.

---

### Example 1: The Midnight Merge (Multi-Speaker Pair Programming Banter)
* **Mode:** Multi-speaker  
* **Speakers:** Speaker 1 = `Aoede` (Lead Architect), Speaker 2 = `Puck` (Caffeinated SRE)  
* **Director Instructions:** Natural, unrehearsed conversational banter. Include soft breathing, chuckles, and authentic late-night dev cadence.

```text
Speaker 1 (Aoede): [soft sigh, gentle smile] Jake, please tell me you did not just merge that branch directly into main at midnight.

Speaker 2 (Puck): [chuckles nervously] Define "directly." Technically... GitHub Actions gave it an orange circle for four seconds before turning bright green!

Speaker 1 (Aoede): [deadpan pause] An orange circle? Puck, that was a database migration dropping the user auth table!

Speaker 2 (Puck): [gasps, then fast apologetic rush] Wait, what?! No no no—[types furiously sound]—reverting! Rollback initiated! Oh thank goodness for point-in-time recovery... [clears throat] You saw nothing, right?

Speaker 1 (Aoede): [laughs softly] I saw everything. But your rollback latency was under three seconds. You get half credit.
```

**What to Listen For:**
- The shift from weary sarcasm in Aoede to adrenaline-fueled panic in Puck.
- Subtle breath intakes and natural pauses between sentences.
- Seamless multi-speaker acoustic balance.

---

### Example 2: Planet Silicon (The Sir David Attenborough Nature Documentary)
* **Mode:** Single speaker  
* **Voice:** `Charon`  
* **Director Instructions:** Low, reverent, hushed British nature documentary tone. Evocative cinematic cadence, prolonged dramatic pauses, and awe-inspiring gravitas.

```text
[hushed, reverent whisper] Here, deep within the fluorescent savannah of the open-plan office, we observe a truly magnificent creature... [dramatic pause] ...the Senior Staff Engineer.

[slow, contemplative pacing] It has been hunting a memory leak for forty-seven continuous hours. Notice the telltale twitch of the eyelid... the ceremonial sipping of lukewarm cold brew.

[tone drops deeper with quiet drama] Suddenly... silence falls across the terminal. A single git bisect points to a commit made three years ago... by none other than... itself. 

[subtle, knowing chuckle] In nature, the predator and the prey are so often... one and the same.
```

**What to Listen For:**
- Vocal fry and resonant low-end presence in Charon's lower register.
- Realistic whisper acoustics without digital artifacts or volume drops.
- Dramatic pause pacing and suspension of disbelief.

---

### Example 3: The Stand-Up Comedy Duo & Punchline Timing
* **Mode:** Multi-speaker  
* **Speakers:** Speaker 1 = `Puck` (Stand-up Comic), Speaker 2 = `Aoede` (Straight-man / Co-host)  
* **Director Instructions:** Fast-paced club comedy routine. Comic delivers sharp punchlines with rhythmic pauses; co-host laughs genuinely and reacts.

```text
Speaker 1 (Puck): [upbeat, leaning in] You know you’ve been vibe coding too long when you start thanking your compiler out loud.

Speaker 2 (Aoede): [giggles] You do not actually say "thank you" to rustc.

Speaker 1 (Puck): [earnestly] I do! I told it yesterday: "Thank you for not giving me a lifetime borrow error, you magnificent steel box." [pause 1.0s] And you know what it did?

Speaker 2 (Aoede): [curious] What?

Speaker 1 (Puck): [deadpan timing] It panicked on line 402 anyway. Pure betrayal! 

Speaker 2 (Aoede): [bursts out laughing] Classic borrow checker! You never had a chance!
```

**What to Listen For:**
- Comedic beat preservation around the 1.0-second pause before the punchline.
- Natural laughing overlays and conversational chemistry.

---

### Example 4: The 3:00 AM Production Outage War Room
* **Mode:** Single speaker  
* **Voice:** `Fenrir`  
* **Director Instructions:** Urgent, intense, disciplined incident response commander. Accelerating rhythm that stabilizes into calm military-grade focus.

```text
[urgent, sharp breath] All hands on the bridge. We have a cascading 502 spike across us-east-1. The ingress pods are death-spiraling and Redis connections are saturated at ninety-eight percent.

[steadying breath, dropping into calm command] SRE team, do not touch the deployment pipeline. I repeat: freeze all deployments immediately. 

[clear, deliberate pacing] Step one: drain traffic from cluster Bravo. Step two: double the connection pool timeout to give the replicas breathing room. 

[pause 1.2s] Watch the latency graph... [relieved exhale] Recovery confirmed. P99 latency dropped from four seconds back down to twelve milliseconds. Outstanding work, team. Breathe.
```

**What to Listen For:**
- High-stress vocal compression and authentic vocal urgency.
- Articulation of technical jargon (`502`, `us-east-1`, `ingress pods`, `P99`, `12ms`).
- Transition from heightened panic to audible relief.

---

### Example 5: Spoken Code Normalization & Complex Math Stress Test
* **Mode:** Single speaker  
* **Voice:** `Aoede`  
* **Director Instructions:** Intelligent, articulate technical presenter reciting code, Git commit hashes, and KaTeX math without robotic stutter.

```text
[bright, explanatory tone] Let's review the optimization in commit a-seven-four-f-two-c. 

[measured and clear] We replaced the naive search with an A-star traversal running in Big-O of n-log-n time. Specifically, the heuristic satisfies the triangle inequality: the estimated cost h of node x is strictly less than or equal to the actual distance d from x to y, plus h of y.

[warm enthusiasm] Furthermore, the regex pattern—lookbehind for foo followed by bar—compiled down to a deterministic finite automaton with zero backtracking! All thirty-two tests passed in four point eight milliseconds.
```

**What to Listen For:**
- Pronunciation of alphanumeric hashes (`a-seven-four-f-two-c`).
- Spoken mathematical symbols ($\mathcal{O}(n \log n)$, $h(x) \le d(x,y) + h(y)$).
- Proper technical terminology without phonetic mangling.

---

### Example 6: Turbo Speed-Talking Velocity Ramp (VoiceFi 2.5x Emulation)
* **Mode:** Single speaker  
* **Voice:** `Kore`  
* **Director Instructions:** Begins in calm, conversational cadence (120 WPM), then smoothly accelerates into high-velocity, fatigue-free 260 WPM delivery before snapping back to a calm conclusion.

```text
[calm, steady pacing] Initializing the developer diagnostic review...

[noticeably faster, crisp cadence] We scanned four thousand two hundred symbols across twenty-eight packages. Memory allocations dropped twelve percent, garbage collection pauses were eliminated across the event loop, socket contention on port 5141 cleared in two milliseconds, and three race conditions inside the mutex pipeline were permanently resolved.

[smooth return to serene, confident tone] System status is fully green. All systems ready for deployment.
```

**What to Listen For:**
- Intelligibility during rapid phonetic delivery.
- Crisp consonant articulation on multi-syllabic technical words.
- Absence of unnatural pitch shifting ("chipmunking") during speed ramping.

---

## 🛠️ Director Mode: Acoustic Prompting Cheat Sheet

Gemini's audio models respond to inline emotional and stylistic directives wrapped in square brackets:

### Emotional & Mood Tags
* `[excited]` — Elevates pitch and cadence with energetic delivery.
* `[whispering]` / `[hushed whisper]` — Low-volume vocal fry with intimate mic proximity.
* `[sighs]` / `[relieved exhale]` — Auditory breath soundscapes adding human realism.
* `[giggles]` / `[chuckles]` / `[laughs warmly]` — Realistic vocal laughter before or during words.
* `[deadpan]` / `[sarcastic]` — Flattens prosody for dry humor and technical irony.
* `[urgent]` / `[tense]` — Tightens vocal cords and speeds up syllable transitions.

### Pacing & Timing Tags
* `[pause 1.0s]` / `[dramatic pause]` — Injects intentional silence without triggering end-of-turn.
* `[fast]` / `[rapid tempo]` — Accelerates speech rate without distorting pitch.
* `[slow]` / `[measured pacing]` — Emphasizes every syllable for instructional clarity.
* `[clears throat]` / `[soft cough]` — Natural conversational hesitation.

---

## 🔗 Integrating AI Studio Personas into VoiceFi

Once you audition and calibrate a voice persona in Google AI Studio, you can immediately activate and use it in your local VoiceFi installation:

### 1. Test via VoiceFi CLI
```bash
# Audition prebuilt Gemini neural voices
vifi voice test "Puck" -t "Testing upbeat Gemini neural voice in VoiceFi."
vifi voice test "Aoede" -t "Testing warm conversational lead in VoiceFi."
vifi voice test "Charon" -t "Testing documentary narrator voice."
```

### 2. Silent TTFB Latency Benchmark (Ping)
```bash
# Benchmark responsiveness silently without playing audio
vifi ping "Puck"
vifi ping "Aoede" -n 3
```

### 3. Set as Active Persona for Antigravity or Claude Code
```bash
# Assign to primary agent
vifi voice set antigravity Aoede

# Assign to pair programmer / QA
vifi voice set claude Puck
vifi voice set researcher Charon
```

### 4. Direct Speech-to-Speech Live Studio
```bash
# Launch interactive Gemini 3.8 Live studio with co-timed sound effects
vifi live
# Or comedy duo mode:
vifi comedy
```

---

## ⚡ Zero-Click Programmatic Dialogue Generation (`scripts/generate_gemini_dialogue.py`)

Rather than navigating the Google AI Studio web UI, creating speaker boxes, and clicking dropdowns and generate buttons 15+ times, VoiceFi provides a native zero-click programmatic synthesizer: [`scripts/generate_gemini_dialogue.py`](../scripts/generate_gemini_dialogue.py).

### Why Use It?
* **Zero Button Clicking**: Feed in a dialogue script (inline string or `.txt` file) and get a finished broadcast-ready 24kHz `.wav` in ~3 seconds.
* **Auto-Speaker Mapping**: Automatically recognizes `Aoede: ...`, `Puck: ...`, `Speaker 1: ...`, `Charon: ...` and binds them to Gemini's multi-speaker engine.
* **Full Acting Tag Preservation**: Keeps all emotional and pacing directives (`[whispers]`, `[sighs]`, `[chuckles]`, `[pause 1.0s]`, `[deadpan]`).
* **Zero Cloud Setup**: Automatically uses your existing `GEMINI_API_KEY` from `~/.voicefi/config.yaml`.

---

### How to Use It

#### Method 1: Ask Antigravity Directly (Zero Effort)
You can paste any script into your Antigravity chat prompt and say:
> *"Synthesize this dialogue with Aoede and Puck and play it."*

Antigravity executes [`scripts/generate_gemini_dialogue.py`](../scripts/generate_gemini_dialogue.py) in the background and delivers the finished audio track.

#### Method 2: From a Text File (`-f`)
Save your dialogue script in a text file (e.g. `podcast_take.txt`):
```text
Aoede: [soft sigh] Jake, tell me you did not just merge directly into main.
Puck: [chuckles] Define directly! GitHub Actions turned green eventually!
```

Run with instant audio playback over your Mac speakers:
```bash
.venv/bin/python scripts/generate_gemini_dialogue.py -f podcast_take.txt --play
```

#### Method 3: Terminal One-Liner
```bash
.venv/bin/python scripts/generate_gemini_dialogue.py \
  "Aoede: [whispers] Are the unit tests running?
Puck: [excited] All 14 passed in 300 milliseconds!" \
  --play
```

#### Method 4: Custom Voice Pairs (e.g. Aoede + Charon)
```bash
.venv/bin/python scripts/generate_gemini_dialogue.py \
  "Aoede: Here is the code review.
Charon: [dramatic pause] Let us examine the memory allocation." \
  --voice1 Aoede --voice2 Charon --play
```

#### Method 5: In Python Code
```python
from scripts.generate_gemini_dialogue import generate_gemini_dialogue

wav_path = generate_gemini_dialogue(
    script_text="Aoede: Ready? \nPuck: Let's ship it!",
    speaker_map={"Aoede": "Aoede", "Puck": "Puck"},
)
print(f"Audio written to: {wav_path}")
```

