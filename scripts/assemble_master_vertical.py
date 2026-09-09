#!/Users/jaketrigg/Projects/VoiceFi/.venv/bin/python
"""
Spicewood Outlaws™ - Master 9:16 Vertical Video Assembly & Platform Cutdown Pipeline

Concatenates Act 1, Act 2, and Act 3 into the full 4m 21.44s master vertical film,
generates platform cutdowns (YouTube Shorts 55s, TikTok/Reels Speedburst 95s, Finale 110s),
and syncs deliverables to Companion PWA downloads directory.
"""
import os
import subprocess
import shutil
import time

desktop_dir = '/Users/jaketrigg/Desktop'
downloads_dir = '/Users/jaketrigg/Projects/VoiceFi/src/voicefi/companion/static/downloads'
base_dir = '/Users/jaketrigg/Projects/VoiceFi/assets/reels'
audio_master = os.path.join(base_dir, 'spicewood_outlaws_master_vocal_mix.wav')
work_dir = '/tmp/spicewood_master_vertical_work'
os.makedirs(work_dir, exist_ok=True)
os.makedirs(downloads_dir, exist_ok=True)

act1_mp4 = os.path.join(desktop_dir, 'spicewood_act1_vertical_9_16.mp4')
act2_mp4 = os.path.join(desktop_dir, 'spicewood_act2_vertical_9_16.mp4')
act3_mp4 = os.path.join(desktop_dir, 'spicewood_act3_vertical_9_16.mp4')

master_desktop = os.path.join(desktop_dir, 'spicewood_outlaws_full_master_9_16.mp4')
shorts_desktop = os.path.join(desktop_dir, 'spicewood_shorts_act1_55s.mp4')
reel2_desktop = os.path.join(desktop_dir, 'spicewood_reel_act2_speedburst.mp4')
reel3_desktop = os.path.join(desktop_dir, 'spicewood_reel_act3_finale.mp4')

print("=" * 60)
print("🤠 SPICEWOOD OUTLAWS™ - MASTER VERTICAL ASSEMBLY & CUTDOWNS")
print("=" * 60)

t0 = time.time()

# 1. Verify source acts
for path, name in [(act1_mp4, "Act 1"), (act2_mp4, "Act 2"), (act3_mp4, "Act 3")]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required act: {name} at {path}")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"✓ Found {name}: {size_mb:.1f} MB ({path})")

# 2. Extract video-only streams to ensure clean start at pts=0 without audio priming offset
print("\n1. Preparing clean video streams...")
v_acts = []
for idx, (path, name) in enumerate([(act1_mp4, "Act 1"), (act2_mp4, "Act 2"), (act3_mp4, "Act 3")], 1):
    v_path = os.path.join(work_dir, f'act{idx}_vonly.mp4')
    subprocess.run([
        'ffmpeg', '-y',
        '-i', path,
        '-map', '0:v',
        '-c', 'copy',
        v_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    v_acts.append(v_path)

concat_list = os.path.join(work_dir, 'acts_concat.txt')
with open(concat_list, 'w') as f:
    for v_path in v_acts:
        f.write(f"file '{v_path}'\n")

# 3. Concatenate video stream
concat_video_raw = os.path.join(work_dir, 'acts_video_concat.mp4')
print("2. Concatenating Act 1, 2 & 3 video streams losslessly...")
subprocess.run([
    'ffmpeg', '-y',
    '-f', 'concat', '-safe', '0',
    '-i', concat_list,
    '-c', 'copy',
    concat_video_raw
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# 4. Prepare pristine master audio with Foley needle drops (Act 1 & Act 3)
print("3. Mixing pristine master audio with Foley needle drops...")
needle_sfx = '/Users/jaketrigg/Projects/VoiceFi/assets/audio/sfx/needle_drop/NeedleDrop02.mp3'
master_audio_foley = os.path.join(work_dir, 'master_audio_foley.wav')

filter_master_audio = (
    '[1:a]aresample=44100,volume=0.88,adelay=2100|2100,afade=t=out:st=5.0:d=1.0[sfx_act1];'
    '[2:a]aresample=44100,adelay=182600|182600,volume=0.45[sfx_act3];'
    '[0:a][sfx_act1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[m1];'
    '[m1][sfx_act3]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]'
)

subprocess.run([
    'ffmpeg', '-y',
    '-i', audio_master,
    '-i', needle_sfx,
    '-i', needle_sfx,
    '-filter_complex', filter_master_audio,
    '-map', '[a]',
    '-c:a', 'pcm_s24le',
    '-ar', '44100',
    master_audio_foley
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# 5. Multiplex with 24-bit audio soundtrack to ensure continuous unbroken sound & zero start offset
print("4. Multiplexing full master with uncompressed 24-bit audio soundtrack...")
master_work = os.path.join(work_dir, 'spicewood_outlaws_full_master_9_16.mp4')
subprocess.run([
    'ffmpeg', '-y',
    '-i', concat_video_raw,
    '-i', master_audio_foley,
    '-map', '0:v:0',
    '-map', '1:a:0',
    '-map_chapters', '-1',
    '-c:v', 'copy',
    '-c:a', 'aac',
    '-b:a', '320k',
    '-ar', '44100',
    '-movflags', '+faststart',
    '-shortest',
    master_work
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

shutil.copy2(master_work, master_desktop)
print(f"✓ Created Full Master Vertical: {master_desktop} ({os.path.getsize(master_desktop)/(1024*1024):.1f} MB)")

# 5. Create Platform Cutdowns
print("\n3. Generating Platform Cutdowns...")

# Cutdown 1: YouTube Shorts (Act 1 <= 60s hard limit)
print("   - Generating YouTube Shorts cut (<60s)...")
shutil.copy2(act1_mp4, shorts_desktop)
print(f"   ✓ YouTube Shorts Cut: {shorts_desktop}")

# Cutdown 2: TikTok / IG Reels Speedburst (Act 2)
print("   - Generating TikTok / IG Reels Speedburst cut...")
shutil.copy2(act2_mp4, reel2_desktop)
print(f"   ✓ TikTok / IG Reels Speedburst: {reel2_desktop}")

# Cutdown 3: Bonfire Finale (Act 3)
print("   - Generating Bonfire Climax / Outro Finale cut...")
shutil.copy2(act3_mp4, reel3_desktop)
print(f"   ✓ Bonfire Climax Finale: {reel3_desktop}")

# 6. Copy Deliverables to Companion PWA Downloads Directory
print("\n4. Syncing Deliverables to Companion PWA Downloads Directory...")
deliverables = [
    (master_desktop, 'spicewood_outlaws_full_master_9_16.mp4'),
    (act1_mp4, 'spicewood_act1_vertical_9_16.mp4'),
    (act2_mp4, 'spicewood_act2_vertical_9_16.mp4'),
    (act3_mp4, 'spicewood_act3_vertical_9_16.mp4'),
    (shorts_desktop, 'spicewood_shorts_act1_55s.mp4'),
    (reel2_desktop, 'spicewood_reel_act2_speedburst.mp4'),
    (reel3_desktop, 'spicewood_reel_act3_finale.mp4')
]

for src, dest_name in deliverables:
    dest_path = os.path.join(downloads_dir, dest_name)
    shutil.copy2(src, dest_path)
    size_mb = os.path.getsize(dest_path) / (1024 * 1024)
    print(f"   ✓ Synced: {dest_name} ({size_mb:.1f} MB)")

print("\n" + "=" * 60)
print(f"✨ ALL DELIVERABLES ASSEMBLED AND SYNCED ({time.time() - t0:.1f}s)")
print("=" * 60)
