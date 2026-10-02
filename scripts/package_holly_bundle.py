import os
import shutil
import json
import zipfile
from pathlib import Path

def main():
    staging = Path("/tmp/voicefi_clones_pack")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    # 1. Copy cloned voices
    cloned_dir = staging / "cloned_voices"
    cloned_dir.mkdir(exist_ok=True)

    src_clones = Path.home() / ".voicefi" / "cloned_voices"
    for v in ["christopher_walken", "visionary_quest"]:
        src_v = src_clones / v
        dest_v = cloned_dir / v
        shutil.copytree(src_v, dest_v)
        # Make profile paths relative / home-portable in the export
        prof_file = dest_v / "profile.json"
        if prof_file.is_file():
            with open(prof_file, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            pdata["sample_paths"] = [
                f"~/.voicefi/cloned_voices/{v}/samples/{Path(p).name}"
                for p in pdata.get("sample_paths", [])
            ]
            with open(prof_file, "w", encoding="utf-8") as f:
                json.dump(pdata, f, indent=2)

    # 2. Copy voice-cloning skill
    skills_dir = staging / "skills" / "voice-cloning"
    skills_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2("/Users/jaketrigg/Projects/VoiceFi/.agents/skills/voice-cloning/SKILL.md", skills_dir / "SKILL.md")

    # 3. Create install.sh
    install_sh = """#!/usr/bin/env bash
set -e

echo "🎙️ Installing VoiceFi Cloned Voices (Christopher Walken & Noble / Visionary Quest)..."

TARGET_DIR="$HOME/.voicefi/cloned_voices"
mkdir -p "$TARGET_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy voice folders
cp -R "$SCRIPT_DIR/cloned_voices/christopher_walken" "$TARGET_DIR/"
cp -R "$SCRIPT_DIR/cloned_voices/visionary_quest" "$TARGET_DIR/"

echo "✅ Copied voice profiles to: $TARGET_DIR"

# Fix home path in profile.json on this specific machine
for VOICE in christopher_walken visionary_quest; do
  PROF="$TARGET_DIR/$VOICE/profile.json"
  if [ -f "$PROF" ]; then
    python3 -c "
import json, os
p = '$PROF'
with open(p, 'r') as f:
    d = json.load(f)
home = os.path.expanduser('~')
d['sample_paths'] = [os.path.join(home, '.voicefi/cloned_voices/$VOICE/samples', os.path.basename(x)) for x in d.get('sample_paths', [])]
with open(p, 'w') as f:
    json.dump(d, f, indent=2)
"
  fi
done

# Install Claude Code skill if ~/.claude or current git repo exists
CLAUDE_SKILLS="$HOME/.claude/skills/voice-cloning"
mkdir -p "$CLAUDE_SKILLS"
cp "$SCRIPT_DIR/skills/voice-cloning/SKILL.md" "$CLAUDE_SKILLS/"
echo "✅ Installed voice-cloning skill to: $CLAUDE_SKILLS"

if [ -d ".agents/skills" ]; then
  mkdir -p ".agents/skills/voice-cloning"
  cp "$SCRIPT_DIR/skills/voice-cloning/SKILL.md" ".agents/skills/voice-cloning/"
  echo "✅ Installed voice-cloning skill to local workspace: .agents/skills/voice-cloning"
fi

echo ""
echo "🎉 Voice packs successfully installed!"
echo ""
echo "📋 Next steps to use with Claude Code:"
echo "  1. Assign to Claude:"
echo "     vifi clone assign christopher_walken claude"
echo "     # or: vifi clone assign visionary_quest claude"
echo ""
echo "  2. Audition the voice:"
echo "     vifi speak \\"Why would you pay for voice when you can have it for free? That's crazy!\\" --voice christopher_walken"
echo ""
echo "  3. Set up Claude Code turn completion:"
echo "     vifi setup --claude"
echo ""
echo "💡 For true local Apple Silicon neural diffusion (F5-TTS):"
echo "     brew install ffmpeg"
echo "     pip install f5-tts torchcodec"
echo ""
"""

    (staging / "install.sh").write_text(install_sh)
    os.chmod(staging / "install.sh", 0o755)

    # 4. Create README.md
    readme = """# 🎙️ VoiceFi Voice Pack: Christopher Walken & Noble (Visionary Quest)

This pack adds **Christopher Walken** and **Noble (Visionary Quest)** voice clones to VoiceFi for Claude Code and macOS.

---

## ⚡ 1-Click Quick Install

Open Terminal in this unzipped folder and run:

```bash
./install.sh
```

This will automatically:
1. Install both voice profiles to `~/.voicefi/cloned_voices/`.
2. Install the `voice-cloning` skill into `~/.claude/skills/voice-cloning/` so Claude Code can clone new voices on demand.
3. Configure path resolution for your Mac.

---

## 🎭 How to Use with Claude Code

### 1. Assign to Claude
To have Claude speak with Christopher Walken:
```bash
vifi clone assign christopher_walken claude
```

To have Claude speak with Noble (Visionary Quest):
```bash
vifi clone assign visionary_quest claude
```

### 2. Connect Claude Code Hooks
Ensure VoiceFi's stop hook is linked to Claude Code:
```bash
vifi setup --claude
```
Now, whenever you run `claude` in your terminal and Claude completes a turn, VoiceFi will automatically speak Claude's response aloud in that persona!

### 3. Audition the Voices
```bash
vifi speak "Why would you pay for voice when you can have it for free? That's crazy!" --voice christopher_walken

vifi speak "Find the constraint, break it into moves, clear ownership, clear finish lines." --voice visionary_quest
```

---

## 🧬 Full Neural Diffusion (F5-TTS) Setup (Optional)
If you want the full zero-shot neural diffusion model running directly on your Mac's Apple Silicon GPU (MPS) instead of the calibrated neural fallback:

```bash
brew install ffmpeg
pip install f5-tts torchcodec
```
VoiceFi will automatically detect F5-TTS and synthesize speech with full neural timbre and Walken's syncopated pauses.
"""

    (staging / "README.md").write_text(readme)

    # Create zip file on Desktop and Downloads
    desktop_zip = Path.home() / "Desktop" / "VoiceFi_Clones_Noble_and_Walken.zip"
    downloads_zip = Path.home() / "Downloads" / "VoiceFi_Clones_Noble_and_Walken.zip"

    with zipfile.ZipFile(desktop_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(staging):
            for file in files:
                full_p = Path(root) / file
                rel_p = full_p.relative_to(staging)
                z.write(full_p, rel_p)

    shutil.copy2(desktop_zip, downloads_zip)
    print(f"Created {desktop_zip} ({desktop_zip.stat().st_size / 1024:.1f} KB)")
    print(f"Created {downloads_zip} ({downloads_zip.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    main()
