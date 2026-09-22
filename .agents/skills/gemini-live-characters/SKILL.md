---
name: gemini-live-characters
description: Guides the design, prompt engineering, and real-time generation of distinct acoustic voice personas using Gemini 3.8 Live (gemini-3.8-live) and Gemini Native Audio. Covers system instructions, vocal formants, pitch registers, affective theatrical styles (Shakespearean, Drill Sergeant, 1980s TV Game Show Host, Conspiratorial Insider, Deadpan Sarcastic), and avoiding flat TTS delivery.
---

# 🎭 Gemini Live Characters Skill — VoiceFi™

Engine for authoring, directing, and synthesizing distinct acoustic character personas using Google's **Gemini 3.8 Live** (`gemini-3.8-live`) model and Gemini Native Audio.

---

## 🎯 What This Skill Does

1. **Direct Latent Audio Synthesis:**
   - Unlike standard TTS models that perform text-to-phoneme conversion, `gemini-3.8-live` generates **direct acoustic tokens** in its latent space.
   - Captures throat resonance, breath intakes, theatrical pitch swings, shouting projection, and genuine comedic affect.
2. **Character Personas Beyond Stock Voices:**
   - Transforms base voices (like **Puck**, **Aoede**, **Charon**) into radically distinct theatrical personas:
     - The Fierce Military Drill Sergeant
     - The Elizabethan Shakespearean Tragedian
     - The Slick 1980s TV Game-Show Host
     - The Conspiratorial Underground Insider
     - The Deadpan Sarcastic Ironist
3. **Verbatim Recitation Directives:**
   - Enforces 100% verbatim script fidelity without conversational drift, filler, or preamble.

---

## 🏛️ Character Persona Library & Prompts

### 1. The Military Drill Sergeant
* **Vocal Profile:** Loud, harsh, barking, aggressive cadence, absolute authority, rapid-fire military discipline.
* **Base Voice Recommendation:** `Puck` or `Fenrir`
* **System Instruction:**
  ```text
  You are a fierce, barking military drill sergeant screaming at new recruits in boot camp. Deliver the line with extreme military authority, shouting discipline, aggressive cadence, and zero hesitation.
  ```
* **Script Phrasing Example:**
  ```text
  Read this line verbatim: Here is a piece of terminal lore they do not teach you in vibecamps!
  ```

---

### 2. The Shakespearean Tragedian
* **Vocal Profile:** Grand classical tragedy, theatrical gravitas, trembling breath, heightened emotional stakes, poetic weight.
* **Base Voice Recommendation:** `Puck` or `Charon`
* **System Instruction:**
  ```text
  You are an Elizabethan Shakespearean classical stage actor performing a high-stakes tragedy. Deliver modern technical disaster with immense theatrical gravitas, trembling pathos, and dark poetic weight.
  ```
* **Script Phrasing Example:**
  ```text
  Read this line verbatim: It is 1:00 PM on a Friday. Grok Bot just pushed straight to main, and production is completely on fire.
  ```

---

### 3. The 1980s TV Game-Show Host
* **Vocal Profile:** Booming microphone projection, glossy retro enthusiasm, explosive point reveals, followed by sudden comedic gear shifts into silly deadpan.
* **Base Voice Recommendation:** `Puck` or `Aoede`
* **System Instruction:**
  ```text
  You are an extravagant, slick, high-energy 1980s television game-show host holding a golden microphone on a bright stage. Deliver the line with explosive showmanship on 'FOR 500 POINTS!', then shift smoothly into playful, silly, conspiratorial showmanship.
  ```
* **Script Phrasing Example:**
  ```text
  Read this line verbatim: For 500 points! When the sus admin locks down the server during the SaaS-pocalypse, which command is your absolute last resort?
  ```

---

### 4. The Conspiratorial Underground Insider
* **Vocal Profile:** Hushed whisper, conspiratorial vocal fry, urgent secrets whispered in dark alleys, paranoid glint.
* **Base Voice Recommendation:** `Charon` or `Puck`
* **System Instruction:**
  ```text
  You are an underground hacker whispering forbidden operating system secrets in a dimly lit alley. Deliver the line with hushed, urgent paranoia and conspiratorial intimacy.
  ```

---

### 5. The Deadpan Sarcastic Ironist
* **Vocal Profile:** Flat monotone smirk, trailing consonants, dismissive chuckle, dry Elizabethan mockery.
* **Base Voice Recommendation:** `Puck` or `Kore`
* **System Instruction:**
  ```text
  You are a weary, sarcastic systems engineer delivering dry Elizabethan irony. Speak with deadpan condescension, a mocking chuckle, and zero genuine sympathy.
  ```
* **Script Phrasing Example:**
  ```text
  Read this line verbatim: If you guessed B... congratulations. You barely survived the SaaS-pocalypse.
  ```

---

## 🛠️ Python SDK Implementation (`gemini-3.8-live`)

```python
import asyncio
import wave
from google import genai
from google.genai import types

async def synthesize_character(
    text: str,
    character_prompt: str,
    voice_name: str = "Puck",
    output_wav: str = "/tmp/character.wav",
    api_key: str = None,
):
    client = genai.Client(api_key=api_key)
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=character_prompt)]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )

    chunks = []
    async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
        await session.send_realtime_input(text=f"Read this line verbatim: {text}")
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        chunks.append(part.inline_data.data)
            if response.server_content and response.server_content.turn_complete:
                break

    if chunks:
        pcm = b"".join(chunks)
        with wave.open(output_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)
        return output_wav
    return None
```

---

## 📋 Google Flow Integration Guide

When using the **Flow** web interface:
1. Open the **"Select a voice"** modal.
2. Select base voice (e.g., `Puck`).
3. Under **"Customize performance"**, paste the exact Character System Instruction.
4. Save as a named preset (e.g., `Puck - Drill Sergeant`, `Puck - Game Show Host`).
5. Assign that preset to the corresponding timeline clip.
