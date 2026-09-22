---
name: video-lip-sync
description: Precision audio-to-video lip synchronization and alignment engine. Analyzes pre-generated character videos (from Flow, Luma, Runway, Kling, Sora), extracts visual speech windows using Faster-Whisper forced alignment, time-stretches/compresses audio clauses with dynamic time warping, trims dead-air freezes, and eliminates initial black frames with faststart and poster frame embedding.
---

# 👄 Video Lip-Sync & Alignment Skill — VoiceFi™

Specialized engine for synchronizing newly synthesized or directed character audio to pre-existing AI video clips (from Google Flow, Luma, Kling, Runway, Sora).

---

## 🎯 Architectural Premise

> **In modern AI production, video is significantly more difficult, expensive, and time-consuming to generate than audio.**  
> Therefore, the workflow operates **video-first**: we take an existing visual clip where the character speaks, extract the exact mouth-movement timing, and align our new character voice to match the visual lips with millisecond precision.

---

## 🔄 The 4-Stage Precision Lip-Sync Pipeline

```
[Raw AI Video Clip] (Flow / Luma / Kling)
         │
         ▼
[1. Speech Window Extraction] ────► Faster-Whisper extracts clause boundaries & pauses
         │
         ▼
[2. Dead-Air Trim] ───────────────► Auto-trims frozen tail silence (> 1.0s)
         │
         ▼
[3. Clause-Level Time Warping] ───► Calculates atempo ratios per phrase & aligns with adelay
         │
         ▼
[4. Zero-Black-Frame Packaging] ──► Muxes with -movflags +faststart, zeroed PTS, & attached poster
```

---

### Stage 1: Speech Window Extraction via Faster-Whisper

Extract the exact timestamps where the character opens and closes their mouth on each clause:

```python
from faster_whisper import WhisperModel

model = WhisperModel("base.en", device="cpu", compute_type="int8")
segments, info = model.transcribe("video_audio.wav", word_timestamps=True)

# Extract clause windows:
# Clause 1: start_1 -> end_1
# Clause 2: start_2 -> end_2
# Clause 3: start_3 -> end_3
```

---

### Stage 2: Dead-Air Freeze Trimming

AI video generators often generate extra trailing frames where the character freezes awkwardly after finishing their line:

* **Detection:** If `video_duration - last_spoken_word_end > 1.0s`, trailing dead air is present.
* **Action:** Trim the video at `last_spoken_word_end + 0.4s` to maintain natural breathing room while cutting frozen dead air.
* **FFmpeg Command:**
  ```bash
  ffmpeg -y -ss 0.0 -t <trimmed_duration> -i input.mp4 -c copy trimmed.mp4
  ```

---

### Stage 3: Sub-Second Clause Alignment & Dynamic Time Warping

When new character audio is synthesized, its natural duration may differ from the video's mouth movements:

1. **Calculate per-clause tempo ratio:**
   $$\text{ratio} = \frac{\text{raw\_audio\_duration}}{\text{target\_visual\_duration}}$$
2. **Apply FFmpeg `atempo`:**
   ```bash
   # Speeds up or slows down clause without altering pitch
   ffmpeg -y -i raw_clause.wav -filter:a "atempo=1.35" stretched_clause.wav
   ```
3. **Assemble clauses with millisecond onset delays:**
   ```bash
   ffmpeg -y \
     -i c1_stretched.wav -i c2_stretched.wav -i c3_stretched.wav \
     -filter_complex "[0:a]adelay=0|0[a0];[1:a]adelay=1840|1840[a1];[2:a]adelay=5480|5480[a2];[a0][a1][a2]amix=inputs=3:dropout_transition=0[out]" \
     -map "[out]" synced_audio.wav
   ```

---

### Stage 4: Eliminating the "Video Loads All Black" Bug (Permanent Standard)

When videos load with a black screen in QuickTime, Safari, iOS, or macOS Finder, three container defects are responsible:

1. **Missing `faststart` (`moov` atom at file end):**  
   QuickTime cannot index the first frame until reading the entire file.  
   **Fix:** `-movflags +faststart` (moves `moov` to byte 40).
2. **Non-Zero Presentation Timestamps (`start_time > 0.0`):**  
   Hardware encoders (like VideoToolbox) introduce B-frame reordering delay (`start_time: 0.021s`). Players display an empty black frame before the first packet.  
   **Fix:** `-vf "setpts=PTS-STARTPTS" -avoid_negative_ts make_zero`.
3. **Missing Poster Frame Track:**  
   macOS Finder defaults to a black thumbnail if no explicit cover art is registered.  
   **Fix:** Extract frame 1 and embed as an attached picture track (`-disposition:v:1 attached_pic`).

#### Universal Production Master Command:
```bash
# 1. Extract first frame as poster JPEG
ffmpeg -y -ss 0.0 -i input.mp4 -vframes 1 -q:v 2 /tmp/poster.jpg

# 2. Package master video with faststart and embedded poster
ffmpeg -y \
  -i input.mp4 -i /tmp/poster.jpg \
  -map 0:v -map 0:a -map 1:v \
  -c:v:0 libx264 -preset superfast -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  -c:v:1 mjpeg -disposition:v:1 attached_pic \
  -vf "setpts=PTS-STARTPTS" \
  -avoid_negative_ts make_zero \
  -movflags +faststart \
  master_clean.mp4
```

---

## 💻 Reusable Automation Script (`scripts/video/sync_audio_to_video.py`)

A full end-to-end Python utility automating this pipeline is located in:  
[`scripts/video/sync_audio_to_video.py`](file:///Users/jaketrigg/Projects/vifi.co/scripts/video/sync_audio_to_video.py).
