"""
voicefi/factory/markdown_sync.py
Obsidian & Markdown parser and synchronizer for VoiceFi Reel Factory.
Parses Obsidian frontmatter and speaker callouts (> [!speech|speaker]) into ContentManifest.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from voicefi.factory.models import ContentJob, ContentManifest, ContentType, ScriptDialogueTurn


DEFAULT_REELS_DIR = Path("/Users/jaketrigg/Projects/vifi.co/reels")


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter between --- blocks and return (metadata, body)."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw_yaml = parts[1].strip()
    body = parts[2].strip()

    meta: Dict[str, Any] = {}
    current_key: Optional[str] = None
    sub_dict: Dict[str, Any] = {}

    # Lightweight YAML parser without requiring external PyYAML
    for line in raw_yaml.splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#"):
            continue

        if ":" in line:
            # Check indentation for sub-dictionary
            indent = len(line) - len(line.lstrip())
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")

            if indent > 0 and current_key:
                if isinstance(meta.get(current_key), dict):
                    meta[current_key][key] = val
                else:
                    meta[current_key] = {key: val}
                continue

            current_key = key
            if not val:
                meta[key] = {}
            else:
                # Type conversion
                if val.lower() in ("true", "yes"):
                    meta[key] = True
                elif val.lower() in ("false", "no"):
                    meta[key] = False
                elif re.match(r"^-?\d+$", val):
                    meta[key] = int(val)
                elif re.match(r"^-?\d+\.\d+$", val):
                    meta[key] = float(val)
                elif val.endswith("s") and re.match(r"^\d+", val):
                    meta[key] = float(val[:-1])
                else:
                    meta[key] = val

    return meta, body


def parse_reel_markdown(md_text: str, file_path: Optional[Path] = None) -> ContentManifest:
    """Parse Obsidian reel markdown into a ContentManifest dataclass."""
    meta, body = parse_frontmatter(md_text)

    title = meta.get("title")
    if not title:
        # Fallback to first # Header or filename
        header_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if header_match:
            title = header_match.group(1).replace("🎬", "").strip()
        elif file_path:
            title = file_path.stem.replace("_", " ").title()
        else:
            title = "Untitled Social Reel"

    turns: List[ScriptDialogueTurn] = []

    # Pattern 1: Obsidian Callout: > [!speech|speaker] Name (Voice • Inflection)
    callout_pattern = re.compile(
        r">\s*\[!speech(?:\|([\w\-]+))?\]\s*(?:([^\n\(]+))?(?:\(([^\)]+)\))?\s*\n((?:>[^\n]*\n?)+)",
        re.IGNORECASE,
    )

    matches = list(callout_pattern.finditer(body))

    if matches:
        for m in matches:
            spk_tag = m.group(1) or "viv"
            spk_name = (m.group(2) or spk_tag).strip()
            inflection_info = (m.group(3) or "").strip()
            raw_speech = m.group(4)

            # Clean leading '>' from quote lines
            clean_lines = []
            for line in raw_speech.splitlines():
                l = re.sub(r"^>\s*", "", line).strip()
                if l and not l.startswith("[!"):
                    clean_lines.append(l)
            speech_text = " ".join(clean_lines).strip()
            # Remove exterior quotation marks
            speech_text = speech_text.strip('"').strip("“").strip("”")

            # Extract voice name if present in inflection (e.g. Aoede • energetic)
            voice_id = None
            emotion = inflection_info
            if "•" in inflection_info:
                parts = [p.strip() for p in inflection_info.split("•", 1)]
                voice_id = parts[0]
                emotion = parts[1]

            word_count = len(speech_text.split())
            dur = max(2.0, word_count / 2.5)

            turns.append(
                ScriptDialogueTurn(
                    speaker=spk_name,
                    text=speech_text,
                    emotion=emotion,
                    voice_id=voice_id,
                    duration_s=dur,
                )
            )

    # Pattern 2: Markdown Heading: ### Speaker (inflection)
    if not turns:
        heading_pattern = re.compile(
            r"###\s+([^\n\(]+)(?:\(([^\)]+)\))?\n([^#]+)",
            re.MULTILINE,
        )
        for m in heading_pattern.finditer(body):
            spk_name = m.group(1).strip()
            emotion = (m.group(2) or "").strip()
            speech_text = m.group(3).strip().strip('"').strip("“").strip("”")
            word_count = len(speech_text.split())
            dur = max(2.0, word_count / 2.5)

            turns.append(
                ScriptDialogueTurn(
                    speaker=spk_name,
                    text=speech_text,
                    emotion=emotion,
                    duration_s=dur,
                )
            )

    total_words = sum(len(t.text.split()) for t in turns)
    calc_dur = sum(t.duration_s for t in turns)

    return ContentManifest(
        title=title,
        content_type=meta.get("content_type", ContentType.REEL_9_16.value),
        target_duration_s=float(meta.get("target_duration_s", 30.0)),
        aspect_ratio=str(meta.get("aspect_ratio", "9:16")),
        turns=turns,
        backing_track=meta.get("backing_track"),
        total_words=total_words,
        calculated_duration_s=round(calc_dur, 2),
    )


def dump_reel_markdown(manifest: ContentManifest, reel_id: str = "REEL-001") -> str:
    """Format a ContentManifest as an Obsidian-ready Markdown string."""
    lines = [
        "---",
        f"id: {reel_id}",
        f'title: "{manifest.title}"',
        "status: ready_to_render",
        f"aspect_ratio: {manifest.aspect_ratio}",
        f"target_duration_s: {manifest.target_duration_s}",
        "engine: gemini-3.8-flash-tts",
        f"backing_track: {manifest.backing_track or 'spicewood_texas_beat_85bpm.mp3'}",
        "tags: [voicefi, reel, gemini38]",
        "---",
        "",
        f"# 🎬 {manifest.title}",
        "",
        "> [!tip] Factory Studio Control Link",
        f"> [Open in VoiceFi Reel Factory Studio](http://localhost:5141/factory?file=reels/{reel_id}.md)",
        "",
        "---",
        "",
        "## 🎙️ Dialogue Script",
        "",
    ]

    for turn in manifest.turns:
        callout_type = (
            "viv"
            if "viv" in turn.speaker.lower()
            else ("stefan" if "stefan" in turn.speaker.lower() else "jake")
        )
        voice_str = f"{turn.voice_id} • " if turn.voice_id else ""
        emotion_str = f"({voice_str}{turn.emotion})" if turn.emotion or turn.voice_id else ""
        lines.append(f"> [!speech|{callout_type}] {turn.speaker} {emotion_str}".strip())
        lines.append(f"> {turn.text}")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "> [!sfx] Audio Bed & Video Render Notes",
            f"* **Total Words**: {manifest.total_words} words",
            f"* **Estimated Runtime**: ~{manifest.calculated_duration_s}s",
            "* **Hardware Acceleration**: Apple Silicon VideoToolbox 1080x1920 @ 60 FPS",
            "",
        ]
    )

    return "\n".join(lines)


def list_reels_in_vault(vault_reels_dir: Path = DEFAULT_REELS_DIR) -> List[Dict[str, Any]]:
    """Scan vault reels directory and return summary metadata list."""
    if not vault_reels_dir.exists():
        return []

    reels = []
    for p in sorted(vault_reels_dir.glob("*.md")):
        if (
            p.name.startswith(".")
            or "command_center" in p.name.lower()
            or p.name.lower() in ("readme.md", "reel_template.md")
        ):
            continue
        try:
            content = p.read_text(encoding="utf-8")
            meta, _ = parse_frontmatter(content)
            manifest = parse_reel_markdown(content, file_path=p)

            # Check attached video
            vid_meta = meta.get("video") or {}
            vid_file = None
            if isinstance(vid_meta, dict):
                vid_file = vid_meta.get("file")
            elif isinstance(vid_meta, str):
                vid_file = vid_meta

            recordings_dir = Path("/Users/jaketrigg/Projects/vifi.co/reels/recordings")
            default_take = recordings_dir / f"{meta.get('id', p.stem)}_pointing_take.mp4"
            video_url = None
            video_name = None

            if vid_file and (DEFAULT_REELS_DIR / vid_file).exists():
                video_name = Path(vid_file).name
                video_url = f"/api/factory/video/{video_name}"
            elif default_take.exists():
                video_name = default_take.name
                video_url = f"/api/factory/video/{video_name}"

            reels.append(
                {
                    "file_name": p.name,
                    "file_path": str(p),
                    "obsidian_uri": f"obsidian://open?vault=vifi.co&file=reels/{p.name}",
                    "id": meta.get("id", p.stem),
                    "title": manifest.title,
                    "status": meta.get("status", "draft"),
                    "turns_count": len(manifest.turns),
                    "words": manifest.total_words,
                    "duration_s": manifest.calculated_duration_s,
                    "target_duration_s": manifest.target_duration_s,
                    "cast": [t.speaker for t in manifest.turns],
                    "video": vid_meta if isinstance(vid_meta, dict) else {"file": vid_meta},
                    "video_url": video_url,
                    "video_name": video_name,
                    "turns": [
                        {
                            "spk": t.speaker,
                            "voice": t.voice_id
                            or ("Aoede" if "viv" in t.speaker.lower() else "Charon"),
                            "infl": t.emotion or "natural",
                            "dur": f"{t.duration_s:.1f}s",
                            "text": t.text,
                        }
                        for t in manifest.turns
                    ],
                }
            )
        except Exception as e:
            continue
    return reels


def update_reel_frontmatter_video(
    file_path: Path,
    video_rel_path: str,
    original_filename: str = "",
    duration_s: float = 0.0,
) -> bool:
    """Update or inject video: metadata in the reel note frontmatter."""
    if not file_path.exists():
        return False
    content = file_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False
    raw_yaml = parts[1]
    body = parts[2]

    vid_block = f"""video:
  file: {video_rel_path}
  original_filename: {original_filename}
  status: take_ready
  duration_s: {duration_s}"""

    if re.search(r"^video:\s*.*?(?=^[a-zA-Z0-9_-]+:|\Z)", raw_yaml, re.MULTILINE | re.DOTALL):
        new_yaml = re.sub(
            r"^video:\s*.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
            vid_block + "\n",
            raw_yaml,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        new_yaml = raw_yaml.rstrip() + "\n" + vid_block + "\n"

    new_content = f"---{new_yaml}---{body}"
    file_path.write_text(new_content, encoding="utf-8")
    return True


def update_reel_turn_in_file(
    file_path: Path,
    turn_index: int,
    new_speaker: Optional[str] = None,
    new_voice: Optional[str] = None,
    new_inflection: Optional[str] = None,
    new_text: Optional[str] = None,
) -> bool:
    """Surgically update a specific speaker turn in an Obsidian Markdown reel note."""
    if not file_path.exists():
        return False

    content = file_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(>\s*\[!speech(?:\|([\w\-]+))?\]\s*([^\n\(]+)?(?:\(([^\)]+)\))?\s*\n(?:>[^\n]*\n?)+)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(content))
    if not (1 <= turn_index <= len(matches)):
        return False

    target_match = matches[turn_index - 1]
    spk_tag = target_match.group(2) or "viv"
    curr_speaker = (target_match.group(3) or spk_tag).strip()
    curr_infl_raw = (target_match.group(4) or "").strip()

    curr_voice = None
    curr_inflection = curr_infl_raw
    if "•" in curr_infl_raw:
        parts = [p.strip() for p in curr_infl_raw.split("•", 1)]
        curr_voice = parts[0]
        curr_inflection = parts[1]

    # Extract current body text
    body_lines = []
    for line in target_match.group(1).splitlines():
        clean_l = re.sub(r"^>\s*", "", line).strip()
        if clean_l and not clean_l.startswith("[!"):
            body_lines.append(clean_l)
    curr_text = " ".join(body_lines).strip()

    final_speaker = new_speaker if new_speaker is not None else curr_speaker
    final_voice = new_voice if new_voice is not None else curr_voice
    final_inflection = new_inflection if new_inflection is not None else curr_inflection
    final_text = new_text if new_text is not None else curr_text

    low_spk = final_speaker.lower()
    callout_type = (
        "viv"
        if "viv" in low_spk
        else (
            "stefan"
            if "stefan" in low_spk
            else (
                "christopher"
                if any(x in low_spk for x in ["puck", "christopher", "walken"])
                else "jake"
            )
        )
    )

    voice_part = f"{final_voice} • " if final_voice else ""
    infl_part = f"({voice_part}{final_inflection})" if (final_voice or final_inflection) else ""
    new_header = f"> [!speech|{callout_type}] {final_speaker} {infl_part}".strip()
    new_body = f"> {final_text}"
    new_block = f"{new_header}\n{new_body}\n"

    new_content = content[: target_match.start()] + new_block + content[target_match.end() :]
    file_path.write_text(new_content, encoding="utf-8")
    return True
