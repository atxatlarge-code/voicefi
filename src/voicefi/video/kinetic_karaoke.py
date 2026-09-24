"""
VoiceFi™ Kinetic Word-by-Word Karaoke & Video Canvas Engine.

Renders high-impact vertical (9:16) and multi-format social video reels combining:
1. Generative AI video clips (e.g. Google Flow / Veo pencil flipbooks).
2. Live millisecond-accurate word-level karaoke highlighting (spoken=white, active=glowing neon, upcoming=grey).
3. macOS-inspired frosted glass speaker pills with live pulsing audio indicators.
4. Seamless paper transition pages and freeze-hold ('tpad') frame preservation (zero loops).
5. Automatic speech alignment via faster-whisper.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

from voicefi.video.reel_builder import (
    ANTIGRAVITY_LOGO_SVG,
    CLAUDE_LOGO_SVG,
    VOICEFI_LOGO_SVG,
    RADIO_HOST_LOGO_SVG,
    JAKE_LOGO_SVG,
    get_video_encoder_args,
)

# Canonical Speaker Profiles
SPEAKER_PALETTES = {
    "jake": {
        "name": "Jake",
        "role": "VoiceFi Creator · Developer",
        "tag_color": "#8B9A46",  # Olive Green
        "avatar_svg": JAKE_LOGO_SVG,
    },
    "creator": {
        "name": "Jake",
        "role": "VoiceFi Creator · Developer",
        "tag_color": "#8B9A46",
        "avatar_svg": JAKE_LOGO_SVG,
    },
    "viv": {
        "name": "Viv",
        "role": "Antigravity Main Planner",
        "tag_color": "#3186FF",  # Electric Blue
        "avatar_svg": ANTIGRAVITY_LOGO_SVG,
    },
    "antigravity": {
        "name": "Viv",
        "role": "Antigravity Main Planner",
        "tag_color": "#3186FF",
        "avatar_svg": ANTIGRAVITY_LOGO_SVG,
    },
    "steffan": {
        "name": "Steffan",
        "role": "Claude Code Architect",
        "tag_color": "#D97757",  # Claude Terracotta
        "avatar_svg": CLAUDE_LOGO_SVG,
    },
    "claude": {
        "name": "Steffan",
        "role": "Claude Code Architect",
        "tag_color": "#D97757",
        "avatar_svg": CLAUDE_LOGO_SVG,
    },
    "christopher": {
        "name": "Christopher",
        "role": "Acoustic DSP Lead",
        "tag_color": "#F59E0B",  # Amber Gold
        "avatar_svg": RADIO_HOST_LOGO_SVG,
    },
    "emily": {
        "name": "Emily",
        "role": "VoiceFi Narrator",
        "tag_color": "#10B981",  # Emerald Green
        "avatar_svg": VOICEFI_LOGO_SVG,
    },
    "voicefi": {
        "name": "Emily",
        "role": "VoiceFi Narrator",
        "tag_color": "#10B981",
        "avatar_svg": VOICEFI_LOGO_SVG,
    },
}


class KineticKaraokeEngine:
    """Production compiler for kinetic karaoke reels with generative video backdrops."""

    @staticmethod
    def extract_word_timestamps(audio_path: Union[str, Path]) -> List[Tuple[str, float, float]]:
        """Extract millisecond word timestamps from any audio file using faster-whisper."""
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), word_timestamps=True)

        words = []
        for s in segments:
            for w in s.words:
                cleaned = w.word.strip()
                if cleaned:
                    words.append((cleaned, round(w.start, 2), round(w.end, 2)))
        return words

    @classmethod
    def render_overlay_html(
        cls,
        speaker_info: Dict[str, Any],
        subtext: str,
        words: List[Tuple[str, float, float]],
        active_word_idx: int,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
        """Render single transparent HTML frame with active word glowing."""
        tag_color = speaker_info.get("tag_color", "#8B9A46")
        speaker_name = speaker_info.get("name", "Speaker")
        role = speaker_info.get("role", "AI Agent")
        avatar_svg = speaker_info.get("avatar_svg", VOICEFI_LOGO_SVG)

        word_spans = []
        for idx, (word_text, _, _) in enumerate(words):
            if idx < active_word_idx:
                word_spans.append(f"<span class='word-spoken'>{word_text}</span>")
            elif idx == active_word_idx:
                word_spans.append(f"<span class='word-active'>{word_text}</span>")
            else:
                word_spans.append(f"<span class='word-upcoming'>{word_text}</span>")

        rendered_words = " ".join(word_spans)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800;900&family=JetBrains+Mono:wght@700;800&family=Bricolage+Grotesque:wght@700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {width}px;
    height: {height}px;
    background: transparent;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    align-items: center;
    padding: 130px 60px 180px 60px;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #F8FAFC;
    overflow: hidden;
  }}
  .speaker-pill {{
    display: flex;
    align-items: center;
    gap: 20px;
    background: rgba(13, 17, 26, 0.92);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border: 2.5px solid {tag_color};
    padding: 14px 34px 14px 20px;
    border-radius: 100px;
    box-shadow: 0 16px 45px rgba(0, 0, 0, 0.5), 0 0 35px {tag_color}44;
  }}
  .avatar-wrap {{
    width: 58px;
    height: 58px;
    border-radius: 50%;
    background: {tag_color}22;
    border: 2px solid {tag_color};
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 8px;
    flex-shrink: 0;
  }}
  .speaker-details {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .speaker-name-row {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .speaker-name {{
    font-size: 32px;
    font-weight: 900;
    color: #FFFFFF;
    letter-spacing: -0.5px;
    font-family: 'Bricolage Grotesque', 'Plus Jakarta Sans', sans-serif;
  }}
  .live-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: {tag_color};
    box-shadow: 0 0 14px {tag_color};
  }}
  .speaker-role {{
    font-size: 20px;
    font-weight: 700;
    color: #94A3B8;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.2px;
  }}
  .caption-container {{
    width: 960px;
    background: rgba(10, 13, 20, 0.86);
    backdrop-filter: blur(30px);
    -webkit-backdrop-filter: blur(30px);
    border: 2.5px solid rgba(255, 255, 255, 0.16);
    border-radius: 36px;
    padding: 44px 48px;
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.8), 0 0 40px {tag_color}25;
    display: flex;
    flex-direction: column;
    gap: 18px;
    text-align: center;
  }}
  .caption-text {{
    font-size: 56px;
    font-weight: 800;
    line-height: 1.34;
    letter-spacing: -0.5px;
    font-family: 'Bricolage Grotesque', 'Plus Jakarta Sans', sans-serif;
  }}
  .word-spoken {{
    color: #F8FAFC;
    opacity: 0.95;
  }}
  .word-active {{
    color: {tag_color};
    font-weight: 800;
    text-shadow: 0 0 32px {tag_color}, 0 0 12px {tag_color};
  }}
  .word-upcoming {{
    color: #64748B;
    opacity: 0.55;
  }}
  .caption-subtext {{
    font-size: 22px;
    font-weight: 800;
    color: #94A3B8;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    opacity: 0.85;
  }}
</style>
</head>
<body>
  <div class="speaker-pill">
    <div class="avatar-wrap">{avatar_svg}</div>
    <div class="speaker-details">
      <div class="speaker-name-row">
        <span class="speaker-name">{speaker_name}</span>
        <div class="live-dot"></div>
      </div>
      <span class="speaker-role">{role}</span>
    </div>
  </div>
  <div class="caption-container">
    <div class="caption-text">{rendered_words}</div>
    <div class="caption-subtext">{subtext}</div>
  </div>
</body>
</html>"""

    @classmethod
    def render_karaoke_frames_fast(
        cls,
        turn_idx: int,
        speaker_info: Dict[str, str],
        subtext: str,
        words: List[Tuple[str, float, float]],
        unique_states: List[int],
        tmp_dir: Path,
        width: int = 1080,
        height: int = 1920,
    ) -> Dict[int, Path]:
        """
        Renders all required karaoke overlay frames for a turn.
        Uses persistent Playwright session with in-memory DOM updates (setActiveWord)
        for ultra-fast rendering (~40ms/frame), with transparent Chrome CLI fallback.
        """
        state_png_map: Dict[int, Path] = {}
        for s in unique_states:
            state_png_map[s] = tmp_dir / f"turn_{turn_idx}_state_{s}.png"

        # Try fast path via Playwright
        try:
            from playwright.sync_api import sync_playwright

            base_html = cls.render_overlay_html(
                speaker_info=speaker_info,
                subtext=subtext,
                words=words,
                active_word_idx=-1,
                width=width,
                height=height,
            )
            # Inject fast DOM toggler script into base HTML
            dom_script = """
<script>
function setActiveWord(activeIdx) {
  const spans = document.querySelectorAll('.caption-text span');
  spans.forEach((span, idx) => {
    if (activeIdx === -1) {
      span.className = 'word-upcoming';
    } else if (idx < activeIdx) {
      span.className = 'word-spoken';
    } else if (idx === activeIdx) {
      span.className = 'word-active';
    } else {
      span.className = 'word-upcoming';
    }
  });
}
</script>
</body>"""
            scripted_html = base_html.replace("</body>", dom_script)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(scripted_html)
                try:
                    page.evaluate("() => document.fonts.ready")
                except Exception:
                    pass
                for state_idx in unique_states:
                    page.evaluate(f"setActiveWord({state_idx})")
                    page.screenshot(path=str(state_png_map[state_idx]), omit_background=True)
                browser.close()
            return state_png_map
        except Exception:
            pass

        # Fallback: Chrome CLI per frame
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not os.path.exists(chrome_path):
            chrome_path = (
                shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"
            )

        for state_idx in unique_states:
            png_file = state_png_map[state_idx]
            html_file = tmp_dir / f"turn_{turn_idx}_state_{state_idx}.html"
            html_content = cls.render_overlay_html(
                speaker_info=speaker_info,
                subtext=subtext,
                words=words,
                active_word_idx=state_idx,
                width=width,
                height=height,
            )
            html_file.write_text(html_content, encoding="utf-8")
            cmd = [
                chrome_path,
                "--headless",
                "--disable-gpu",
                "--default-background-color=00000000",
                f"--window-size={width},{height}",
                f"--screenshot={str(png_file)}",
                f"file://{str(html_file)}",
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        return state_png_map

    @classmethod
    def compile_section(
        cls,
        clip_path: Path,
        overlay_plan_txt: Path,
        duration: float,
        out_mp4: Path,
        width: int = 1080,
        height: int = 1920,
        fps: int = 24,
    ):
        """Composite video clip with transparent word overlay stream."""
        encoder_args = get_video_encoder_args(quality="high")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(clip_path),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(overlay_plan_txt),
            "-filter_complex",
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},tpad=stop_mode=clone:stop_duration=20,trim=0:{duration:.3f},setpts=PTS-STARTPTS[base];"
            f"[1:v]fps={fps},scale={width}:{height}[ovl];"
            f"[base][ovl]overlay=0:0:shortest=1[v_out]",
            "-map",
            "[v_out]",
            "-t",
            f"{duration:.3f}",
            *encoder_args,
            "-an",
            str(out_mp4),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Section compilation failed: {res.stderr}")
