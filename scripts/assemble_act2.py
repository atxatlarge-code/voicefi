#!/usr/bin/env python3
import os
import subprocess
import time
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

base_dir = '/Users/jaketrigg/Projects/VoiceFi/assets/reels'
audio_master = os.path.join(base_dir, 'spicewood_outlaws_master_vocal_mix.wav')
work_dir = '/tmp/spicewood_act2_work'
os.makedirs(work_dir, exist_ok=True)
output_mp4 = '/Users/jaketrigg/Desktop/spicewood_act2.mp4'

# Act 2 spans 00:55.56 to 02:30.62 (dur = 95.06s)
ACT_START = 55.56
ACT_END = 150.62
ACT_DUR = round(ACT_END - ACT_START, 2)

# Curated 27-shot sequence with 1-to-1 bar alignment across the speed burst
shots = [
    # 2.01a: Hook 1 drops - Grand hero shot on limestone bluff
    ('2.01a', 55.56, 58.38, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_16.mp4', 0.0, None),
    # 2.01b: Three horseback riders on ridge against sky
    ('2.01b', 58.38, 61.21, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_31.mp4', 0.0, None),
    # 2.02: Sharp butcher knife slicing tender smoked brisket flat (User request: make this brisket cutting scene)
    ('2.02', 61.21, 64.03, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_2.mp4', 0.0, None),
    # 2.03: Dense oak smoke billowing from outdoor pit smoker
    ('2.03', 64.03, 66.85, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_39.mp4', 0.0, None),
    # 2.04: Texas Longhorn steer standing proud in pasture (Reversed: Longhorn 1st)
    ('2.04', 66.85, 69.68, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_19.mp4', 0.0, None),
    # 2.05: Nine-Banded Texas Armadillo rooting in limestone dirt (Reversed: Armadillo 2nd)
    ('2.05', 69.68, 72.50, 'spicewood_act2_raw/wildlife/armadillo_rooting_limestone.mp4', 0.0, None),
    # 2.06: Weathered rancher tipping Stetson by spinning windmill
    ('2.06', 72.50, 75.32, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_6.mp4', 0.0, None),
    # 2.08: Outlaw tapping temple near green SPICEWOOD sign (User request: trim front so it goes to key action)
    ('2.08', 75.32, 76.98, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_7.mp4', 2.25, None),
    # 2.09: Outlaw strides forward through barbecue smoke yard
    ('2.09', 76.98, 79.80, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_18.mp4', 0.0, None),
    # 2.10: Full outdoor smoke yard at sunset with massive offset smokers
    ('2.10', 79.80, 82.63, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_35.mp4', 0.0, None),
    # 2.11: Pitmaster adding split post-oak log to firebox (User request: crop out 2nd fire cut at 2.46s)
    ('2.11', 82.63, 85.45, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_34.mp4', 0.0, 2.40),
    # 2.12: Outlaw gripping vintage Shure 55SH microphone by barn
    ('2.12', 85.45, 89.04, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_14.mp4', 0.0, None),
    # 2.13: Outlaw standing on limestone bluff edge
    ('2.13', 89.04, 91.80, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_37.mp4', 0.0, None),
    # 2.14: Underwater shot of cliff diver landing into cobalt lake water
    ('2.14', 91.80, 94.60, 'spicewood_act3_raw/Cliff_diver_hitting_lake_surface_202609031636.mp4', 0.2, None),
    # 2.15: Pitmaster stirring glowing red-hot coals with iron poker
    ('2.15', 94.60, 97.40, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_15.mp4', 0.0, None),
    # 2.16: Headlights flaring on truck in dusk (snaps right to "Better watch what you wear")
    ('2.16', 97.40, 100.08, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_4.mp4', 0.0, None),
    # 2.17: Bar 37 Speed burst - Black muscle car prowling cedar trail
    ('2.17', 100.08, 103.18, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_24.mp4', 0.0, None),
    # 2.18: Bar 38 - Iron Wolf neon sign with howling wolf
    ('2.18', 103.18, 106.00, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_5.mp4', 0.0, None),
    # 2.19: Bar 39 - Hero truck drift on river gravel
    ('2.19', 106.00, 108.86, 'spicewood_act2_raw/truck_power_slide_hero_2.19.mp4', 0.0, None),
    # 2.20: Bar 40 - High-speed FPV drone skimming down river canyon
    ('2.20', 108.86, 111.52, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_36.mp4', 0.0, None),
    # 2.21: Bar 41 - Hero cash fan on bluff with turquoise ring
    ('2.21', 111.52, 114.50, 'spicewood_act2_raw/outlaw_money_fan_hero_2.21.mp4', 0.0, None),
    # 2.22: Bar 42 - Open-air wooden dancehall pavilion with two-stepping crowd
    ('2.22', 114.50, 116.98, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_21.mp4', 0.0, None),
    # 2.23: Bar 43 - Outlaw on bluff overlooking river in golden sunset
    ('2.23', 116.98, 119.76, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_11.mp4', 0.0, None),
    # 2.24: Bar 44 - Outlaw looking into radiant setting Texas sun with fist raised
    ('2.24', 119.76, 123.20, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_3.mp4', 0.0, None),
    # 2.25a: Hook 2 - Community feast picnic table under oaks
    ('2.25a', 123.20, 126.00, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_33.mp4', 0.0, None),
    # 2.25b: Texas Whitetail Buck stepping through prairie grass
    ('2.25b', 126.00, 129.00, 'spicewood_act2_raw/wildlife/buck_walking_prairie.mp4', 0.0, None),
    # 2.26a1: Rio Grande Wild Turkeys strutting past limestone wall
    ('2.26a1', 129.00, 131.40, 'spicewood_act2_raw/wildlife/wild_turkeys_grass.mp4', 0.0, None),
    # 2.26a2: Great Egret wading in emerald Pedernales River shelves
    ('2.26a2', 131.40, 134.00, 'spicewood_act2_raw/wildlife/egret_wading_river.mp4', 0.0, None),
    # 2.26a3: Greater Roadrunner running full tilt on caliche road
    ('2.26a3', 134.00, 137.00, 'spicewood_act2_raw/wildlife/roadrunner_running_gravel.mp4', 0.0, None),
    # 2.26a4: Golden-Cheeked Warbler singing with beak open on cedar bough
    ('2.26a4', 137.00, 140.00, 'spicewood_act2_raw/wildlife/golden_cheeked_warbler_singing.mp4', 0.0, None),
    # 2.26b1: Outlaws singing and clinking beers together under night sky
    ('2.26b1', 140.00, 142.40, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_32.mp4', 0.0, None),
    # 2.26b2: Glowing campfire coals stirred with iron poker
    ('2.26b2', 142.40, 145.00, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_25.mp4', 0.0, None),
    # 2.26b3: Massive roaring bonfire blazing at night (New 8s Flow video - zero looping)
    ('2.26b3', 145.00, 150.62, 'spicewood_act2_raw/bonfire_burning_at_night_flow_8s.mp4', 0.0, None)
]

print(f'Slicing {len(shots)} Act 2 video shots...')
t0 = time.time()
seg_files = []
for idx, item in enumerate(shots, 1):
    shot_id = item[0]
    start_t = item[1]
    end_t = item[2]
    rel_path = item[3]
    src_in = item[4] if len(item) > 4 else 0.0
    max_src_t = item[5] if len(item) > 5 else None
    
    dur = round(end_t - start_t, 3)
    src_file = os.path.join(base_dir, rel_path)
    out_seg = os.path.join(work_dir, f'seg_{idx:03d}.mp4')
    
    if max_src_t is not None:
        src_dur = max_src_t - src_in
        pts_scale = round(dur / src_dur, 4)
        vf = f'[0:v]setpts={pts_scale}*PTS,scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24[v]'
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(src_in),
            '-i', src_file,
            '-t', str(src_dur),
            '-filter_complex', vf,
            '-map', '[v]',
            '-t', str(dur),
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            out_seg
        ]
    else:
        vf = '[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p[v]'
        cmd = [
            'ffmpeg', '-y',
            '-stream_loop', '3',
            '-ss', str(src_in),
            '-i', src_file,
            '-t', str(dur),
            '-filter_complex', vf,
            '-map', '[v]',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            out_seg
        ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    seg_files.append(out_seg)

concat_list = os.path.join(work_dir, 'video_concat.txt')
with open(concat_list, 'w') as f:
    for s in seg_files:
        f.write(f"file '{s}'\n")

base_video = os.path.join(work_dir, 'act2_base_video.mp4')
subprocess.run([
    'ffmpeg', '-y',
    '-f', 'concat', '-safe', '0',
    '-i', concat_list,
    '-c', 'copy',
    base_video
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
print(f'Base video compiled ({time.time()-t0:.1f}s)')

# Zero comic bursts in Act 2 per negative constraint
hype_bursts = {}

# Lyric Karaoke Subtitle Events (relative to Act 2 start: t_local = t_master - ACT_START)
def rel_w(words, offset=ACT_START):
    return [(w[0], round(w[1] - offset, 3), round(w[2] - offset, 3)) for w in words]

lyrics_timeline = [
    # 2.01a: 55.56 - 58.38 (Hook 1 drops)
    {
        'start': round(55.56 - ACT_START, 3), 'end': round(58.38 - ACT_START, 3),
        'words': rel_w([
            ("OUT", 55.56, 56.26), ("HERE", 56.26, 56.76), ("WE", 56.76, 56.90),
            ("IN", 56.90, 57.10), ("OUTLAW", 57.10, 57.34), ("COUNTRY", 57.34, 58.38)
        ])
    },
    # 2.01b: 58.38 - 61.21
    {
        'start': round(58.38 - ACT_START, 3), 'end': round(61.21 - ACT_START, 3),
        'words': rel_w([
            ("JUST", 58.38, 59.62), ("FOR", 59.62, 59.88),
            ("OUTLAW", 59.88, 60.18), ("SAKE", 60.18, 61.21)
        ])
    },
    # 2.02: 61.21 - 64.03
    {
        'start': round(61.21 - ACT_START, 3), 'end': round(64.03 - ACT_START, 3),
        'words': rel_w([
            ("OUT", 61.21, 61.82), ("HERE", 61.82, 62.16), ("WE", 62.16, 62.50),
            ("JUDGE", 62.50, 62.84), ("A", 62.84, 63.24), ("BRISKET", 63.24, 64.03)
        ])
    },
    # 2.03: 64.03 - 66.85
    {
        'start': round(64.03 - ACT_START, 3), 'end': round(66.85 - ACT_START, 3),
        'words': rel_w([
            ("BY", 64.03, 65.22), ("HOW", 65.22, 65.42),
            ("LONG", 65.42, 65.74), ("IT", 65.74, 66.02), ("TAKE", 66.02, 66.85)
        ])
    },
    # 2.04: 66.85 - 69.68 (Fixed: "Out here we raisin' breeds...")
    {
        'start': round(66.85 - ACT_START, 3), 'end': round(69.68 - ACT_START, 3),
        'words': rel_w([
            ("Out", 66.85, 67.42), ("here", 67.42, 67.78), ("we", 67.78, 68.10),
            ("raisin'", 68.10, 68.56), ("breeds...", 68.56, 69.68)
        ])
    },
    # 2.05: 69.68 - 72.50
    {
        'start': round(69.68 - ACT_START, 3), 'end': round(72.50 - ACT_START, 3),
        'words': rel_w([
            ("They", 69.68, 70.14), ("are", 70.14, 70.30),
            ("very", 70.30, 70.78), ("rare", 70.78, 72.50)
        ])
    },
    # 2.06: 72.50 - 75.32
    {
        'start': round(72.50 - ACT_START, 3), 'end': round(75.32 - ACT_START, 3),
        'words': rel_w([
            ("They", 72.50, 72.92), ("say", 72.92, 73.24), ("we're", 73.24, 73.94),
            ("all", 73.94, 74.08), ("out", 74.08, 74.36), ("here...", 74.36, 75.32)
        ])
    },
    # 2.08: 75.32 - 76.98
    {
        'start': round(75.32 - ACT_START, 3), 'end': round(76.98 - ACT_START, 3),
        'words': rel_w([
            ("'Cause", 75.32, 75.76), ("we're", 75.76, 76.02),
            ("not", 76.02, 76.36), ("all", 76.36, 76.62), ("there!", 76.62, 76.98)
        ])
    },
    # 2.09: 76.98 - 79.80 (Verse 2 starts)
    {
        'start': round(76.98 - ACT_START, 3), 'end': round(79.80 - ACT_START, 3),
        'words': rel_w([
            ("Yeah,", 76.98, 77.80), ("clear", 77.80, 78.62), ("the", 78.62, 78.80),
            ("air,", 78.80, 79.12), ("PULL", 79.48, 79.66), ("UP", 79.66, 79.92),
            ("A", 79.92, 80.12), ("CHAIR", 80.12, 80.50)
        ])
    },
    # 2.10: 79.80 - 82.63
    {
        'start': round(79.80 - ACT_START, 3), 'end': round(82.63 - ACT_START, 3),
        'words': rel_w([
            ("Second", 80.50, 81.14), ("verse", 81.14, 81.46), ("villain,", 81.46, 82.08),
            ("BRAIN", 82.08, 82.36), ("BROKE", 82.36, 82.46), ("BEYOND", 82.46, 82.74),
            ("REPAIR", 82.74, 83.20)
        ])
    },
    # 2.11: 82.63 - 85.45
    {
        'start': round(82.63 - ACT_START, 3), 'end': round(85.45 - ACT_START, 3),
        'words': rel_w([
            ("Oak", 83.50, 84.20), ("wood", 84.20, 84.50), ("brisket,", 84.50, 84.86),
            ("SMOKE", 85.12, 85.22), ("UP", 85.22, 85.42), ("IN", 85.42, 85.62),
            ("THE", 85.62, 85.78), ("FLARE", 85.78, 86.04)
        ])
    },
    # 2.12: 85.45 - 89.04
    {
        'start': round(85.45 - ACT_START, 3), 'end': round(89.04 - ACT_START, 3),
        'words': rel_w([
            ("Listen", 86.44, 86.58), ("to", 86.58, 86.96), ("the", 86.96, 87.16),
            ("master,", 87.16, 87.60), ("NOTHIN'", 87.60, 88.16), ("TO", 88.16, 88.36),
            ("COMPARE", 88.36, 88.76)
        ])
    },
    # 2.13: 89.04 - 91.80
    {
        'start': round(89.04 - ACT_START, 3), 'end': round(91.80 - ACT_START, 3),
        'words': rel_w([
            ("Pace", 89.04, 89.30), ("Bend", 89.30, 89.60), ("cliff", 89.60, 90.18),
            ("dive,", 90.18, 90.56), ("FALL", 90.56, 90.92), ("THROUGH", 90.92, 91.26),
            ("THE", 91.26, 91.42), ("AIR!", 91.42, 91.80)
        ])
    },
    # 2.14: 91.80 - 94.60
    {
        'start': round(91.80 - ACT_START, 3), 'end': round(94.60 - ACT_START, 3),
        'words': rel_w([
            ("Cobalt", 92.14, 92.58), ("lake", 92.58, 92.96), ("water,", 92.96, 93.32),
            ("ICED-OUT", 93.32, 94.18), ("MILLIONAIRE", 94.18, 94.60)
        ])
    },
    # 2.15: 94.60 - 97.40
    {
        'start': round(94.60 - ACT_START, 3), 'end': round(97.40 - ACT_START, 3),
        'words': rel_w([
            ("Sun-baked", 94.92, 95.34), ("sandstone,", 95.34, 95.76),
            ("SITTIN'", 95.76, 96.44), ("IN", 96.44, 96.74),
            ("THE", 96.74, 96.94), ("GLARE", 96.94, 97.40)
        ])
    },
    # 2.16: 97.40 - 100.08
    {
        'start': round(97.40 - ACT_START, 3), 'end': round(100.08 - ACT_START, 3),
        'words': rel_w([
            ("Better", 97.58, 97.80), ("watch", 97.80, 98.16), ("what", 98.16, 98.30),
            ("you", 98.30, 98.48), ("wear,", 98.48, 98.76),
            ("OUTLAWS", 98.76, 99.40), ("EVERYWHERE!", 99.40, 99.84)
        ])
    },
    # 2.17: Bar 37 Speed burst (100.08 - 103.18) - Micro-calibrated acoustic timing
    {
        'start': round(100.08 - ACT_START, 3), 'end': round(103.18 - ACT_START, 3),
        'words': rel_w([
            ("Sippin'", 100.08, 100.70), ("on", 100.70, 100.94), ("that", 100.94, 101.14),
            ("bourbon,", 101.14, 101.44), ("I'm", 101.44, 101.75), ("an", 101.75, 101.90),
            ("OUTLAW", 101.90, 102.48), ("PROWLIN'", 102.48, 103.02)
        ])
    },
    # 2.18: Bar 38 Speed burst (103.18 - 106.00) - Micro-calibrated acoustic timing
    {
        'start': round(103.18 - ACT_START, 3), 'end': round(106.00 - ACT_START, 3),
        'words': rel_w([
            ("Iron", 103.18, 103.60), ("Wolf", 103.60, 103.80), ("is", 103.80, 103.90),
            ("howlin',", 103.90, 104.40),
            ("ENGINES", 104.78, 105.14), ("GROWLIN'", 105.14, 105.80)
        ])
    },
    # 2.19: Bar 39 Speed burst (106.00 - 108.86) - (Fixed: "in the thousand")
    {
        'start': round(106.00 - ACT_START, 3), 'end': round(108.86 - ACT_START, 3),
        'words': rel_w([
            ("Whippin'", 106.00, 106.16), ("round", 106.16, 106.36), ("the", 106.36, 106.72),
            ("river,", 106.72, 106.90), ("PULL", 107.22, 107.66), ("UP", 107.66, 107.76),
            ("IN", 107.76, 107.94), ("THE", 107.94, 108.10), ("THOUSAND", 108.10, 108.56)
        ])
    },
    # 2.20: Bar 40 Speed burst (108.86 - 111.52) - Micro-calibrated acoustic timing
    {
        'start': round(108.86 - ACT_START, 3), 'end': round(111.52 - ACT_START, 3),
        'words': rel_w([
            ("Pedernales", 108.86, 109.38), ("Valley,", 109.38, 109.80),
            ("I'ma", 110.04, 110.18), ("make", 110.18, 110.36),
            ("the", 110.36, 110.54), ("whole", 110.54, 110.72), ("town", 110.72, 110.94),
            ("LOUD!", 110.94, 111.30)
        ])
    },
    # 2.21: Bar 41 Speed burst (111.52 - 114.50) - Micro-calibrated acoustic timing
    {
        'start': round(111.52 - ACT_START, 3), 'end': round(114.50 - ACT_START, 3),
        'words': rel_w([
            ("Spicewood", 111.52, 112.14), ("in", 112.14, 112.48), ("my", 112.48, 112.62),
            ("pocket,", 112.62, 112.94), ("I'MA", 113.10, 113.30), ("MAKE", 113.30, 113.46),
            ("ANOTHER", 113.46, 113.80), ("MILLION", 113.80, 114.22)
        ])
    },
    # 2.22: Bar 42 Speed burst (114.50 - 116.98) - (Fixed: "Rock the old outlaw rhythm")
    {
        'start': round(114.50 - ACT_START, 3), 'end': round(116.98 - ACT_START, 3),
        'words': rel_w([
            ("Rock", 114.50, 114.60), ("the", 114.60, 114.78), ("old", 114.78, 114.96),
            ("outlaw", 114.96, 115.38), ("rhythm...", 115.38, 115.78), ("HATS", 115.78, 115.88),
            ("ON", 115.88, 116.26), ("IN", 116.26, 116.52), ("THE", 116.52, 116.70),
            ("PAVILION!", 116.70, 116.94)
        ])
    },
    # 2.23: Bar 43 Speed burst (116.98 - 119.76) - (Fixed: "is a hell of a feelin'")
    {
        'start': round(116.98 - ACT_START, 3), 'end': round(119.76 - ACT_START, 3),
        'words': rel_w([
            ("Stackin'", 117.20, 117.42), ("up", 117.42, 117.64), ("the", 117.64, 117.84),
            ("paper", 117.84, 118.10), ("is", 118.10, 118.42), ("a", 118.42, 118.54),
            ("HELL", 118.54, 118.76), ("OF", 118.76, 119.14), ("A", 119.14, 119.26),
            ("FEELIN'", 119.26, 119.54)
        ])
    },
    # 2.24: Bar 44 Speed burst (119.76 - 123.20) - (Fixed: "ONE IN 8.3 TRILLION!")
    {
        'start': round(119.76 - ACT_START, 3), 'end': round(123.20 - ACT_START, 3),
        'words': rel_w([
            ("Spittin'", 119.76, 120.16), ("pure", 120.16, 120.54), ("gold", 120.54, 120.94),
            ("baby,", 121.04, 121.36),
            ("ONE", 121.58, 121.80), ("IN", 121.80, 122.02), ("8.3", 122.02, 122.26),
            ("TRILLION!", 122.26, 123.20)
        ])
    },
    # 2.25a: 123.20 - 126.00 (Hook 2 - Community feast part 1)
    {
        'start': round(123.20 - ACT_START, 3), 'end': round(126.00 - ACT_START, 3),
        'words': rel_w([
            ("OUT", 123.20, 123.66), ("HERE", 123.66, 123.92), ("WE", 123.92, 124.10),
            ("IN", 124.10, 124.40), ("OUTLAW", 124.40, 124.86), ("COUNTRY,", 124.86, 125.36)
        ])
    },
    # 2.25b: 126.00 - 129.00 (Hook 2 - Community feast part 2)
    {
        'start': round(126.00 - ACT_START, 3), 'end': round(129.00 - ACT_START, 3),
        'words': rel_w([
            ("JUST", 126.34, 126.74), ("FOR", 126.74, 126.94),
            ("OUTLAW", 126.94, 127.68), ("SAKE", 127.68, 128.74)
        ])
    },
    # 2.26a1: 129.00 - 131.40 (Tailgate toast part 1)
    {
        'start': round(129.00 - ACT_START, 3), 'end': round(131.40 - ACT_START, 3),
        'words': rel_w([
            ("Out", 128.74, 128.92), ("here", 128.92, 129.26), ("we", 129.26, 129.60),
            ("judge", 129.60, 129.90), ("a", 129.90, 130.30), ("brisket...", 130.30, 131.04)
        ])
    },
    # 2.26a2: 131.40 - 134.00 (Tailgate toast part 2)
    {
        'start': round(131.40 - ACT_START, 3), 'end': round(134.00 - ACT_START, 3),
        'words': rel_w([
            ("...by", 131.60, 132.20), ("how", 132.20, 132.44), ("long", 132.44, 132.78),
            ("it", 132.78, 133.04), ("take...", 133.04, 133.44)
        ])
    },
    # 2.26a3: 134.00 - 137.00 (Tailgate toast part 3 - NEW LINE like last time)
    {
        'start': round(134.00 - ACT_START, 3), 'end': round(137.00 - ACT_START, 3),
        'words': rel_w([
            ("Out", 134.36, 134.50), ("here", 134.50, 134.84), ("we", 134.84, 135.16),
            ("raisin'", 135.16, 135.52), ("breeds...", 135.52, 136.44)
        ])
    },
    # 2.26a4: 137.00 - 140.00 (Tailgate toast part 4)
    {
        'start': round(137.00 - ACT_START, 3), 'end': round(140.00 - ACT_START, 3),
        'words': rel_w([
            ("...that", 137.12, 137.26), ("are", 137.26, 137.42),
            ("very", 137.42, 137.82), ("rare", 137.82, 138.66)
        ])
    },
    # 2.26b1: 140.00 - 142.40 (Roaring campfire part 1)
    {
        'start': round(140.00 - ACT_START, 3), 'end': round(142.40 - ACT_START, 3),
        'words': rel_w([
            ("They", 140.00, 140.22), ("say", 140.22, 140.40), ("we're", 140.40, 140.94),
            ("all", 140.94, 141.20), ("out", 141.20, 141.40), ("here...", 141.40, 141.80)
        ])
    },
    # 2.26b2: 142.40 - 145.00 (Roaring campfire part 2)
    {
        'start': round(142.40 - ACT_START, 3), 'end': round(145.00 - ACT_START, 3),
        'words': rel_w([
            ("'Cause", 142.40, 142.72), ("we're", 142.72, 142.92),
            ("not", 142.92, 143.12), ("all", 143.12, 143.54), ("there...", 143.54, 144.10)
        ])
    },
    # 2.26b3: 145.00 - 150.62 (Roaring campfire part 3 - NEW LINE: Summertime... and the living is easy...)
    {
        'start': round(145.00 - ACT_START, 3), 'end': round(150.62 - ACT_START, 3),
        'words': rel_w([
            ("Summertime...", 145.12, 147.50), ("and", 148.04, 148.50),
            ("the", 148.50, 148.90), ("living", 148.90, 149.60),
            ("is", 149.60, 150.00), ("easy...", 150.00, 150.62)
        ])
    }
]

# Generate discrete time boundaries
time_points = {0.0, ACT_DUR}
for p in lyrics_timeline:
    time_points.add(p['start'])
    time_points.add(p['end'])
    for w in p['words']:
        time_points.add(w[1])
        time_points.add(w[2])

sorted_times = sorted([t for t in time_points if 0.0 <= t <= ACT_DUR])

font = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 36, index=1)
space_w = font.getbbox(' ')[2] - font.getbbox(' ')[0]

print(f'Rendering {len(sorted_times)-1} overlay time slices...')
plan_file = os.path.join(work_dir, 'overlay_plan.txt')
plan_lines = []

for i in range(len(sorted_times) - 1):
    t_start = sorted_times[i]
    t_end = sorted_times[i+1]
    dur = t_end - t_start
    if dur < 0.005:
        continue
        
    active_phrase = None
    for p in lyrics_timeline:
        if p['start'] <= t_start < p['end']:
            active_phrase = p
            break
            
    frame = Image.new('RGBA', (1280, 720), (0, 0, 0, 0))
    
    if active_phrase:
        words = [w[0] for w in active_phrase['words']]
        active_idx = -1
        last_spoken_idx = -1
        for widx, w in enumerate(active_phrase['words']):
            if w[1] <= t_start < w[2]:
                active_idx = widx
                break
            elif t_start >= w[2]:
                last_spoken_idx = widx
                
        word_widths = [font.getbbox(w)[2] - font.getbbox(w)[0] for w in words]
        total_w = sum(word_widths) + space_w * (len(words) - 1)
        sx = (1280 - total_w) // 2
        sy = 620
        
        shadow = Image.new('RGBA', (1280, 720), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        cx = sx
        for widx, w in enumerate(words):
            sdraw.text((cx + 2, sy + 3), w, font=font, fill=(0, 0, 0, 220))
            cx += word_widths[widx] + space_w
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=2.5))
        frame.alpha_composite(shadow)
        
        tdraw = ImageDraw.Draw(frame)
        cx = sx
        for widx, w in enumerate(words):
            if widx == active_idx:
                color = (245, 158, 11, 255) # Texas Amber Gold (actively being sung)
            elif (active_idx != -1 and widx < active_idx) or (active_idx == -1 and widx <= last_spoken_idx):
                color = (255, 255, 255, 240) # Spoken white (already sung)
            else:
                color = (156, 163, 175, 230) # Tailwind gray-400 (grey before spoken)
            tdraw.text((cx, sy), w, font=font, fill=color)
            cx += word_widths[widx] + space_w
            
    png_path = os.path.join(work_dir, f'ovl_{i:04d}.png')
    frame.save(png_path)
    plan_lines.append(f"file '{png_path}'\nduration {dur:.3f}\n")

if plan_lines:
    plan_lines.append(plan_lines[-1].split('\n')[0] + '\n')

with open(plan_file, 'w') as f:
    f.writelines(plan_lines)

print('Compositing Act 2 master with 24-bit audio & karaoke overlay...')
t1 = time.time()

audio_slice = os.path.join(work_dir, 'act2_audio.wav')
subprocess.run([
    'ffmpeg', '-y',
    '-ss', str(ACT_START), '-t', str(ACT_DUR),
    '-i', audio_master,
    '-c:a', 'pcm_s24le',
    audio_slice
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# Safely close existing document in QuickTime if open to prevent file-lock collision
subprocess.run(['osascript', '-e', 'tell application "QuickTime Player" to if it is running then close (every document whose name contains "spicewood_act2") saving no'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

final_cmd = [
    'ffmpeg', '-y',
    '-i', base_video,
    '-f', 'concat', '-safe', '0', '-i', plan_file,
    '-i', audio_slice,
    '-filter_complex', '[0:v][1:v]overlay=0:0[v]',
    '-map', '[v]',
    '-map', '2:a',
    '-t', str(ACT_DUR),
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '18',
    '-pix_fmt', 'yuv420p',
    '-g', '24',
    '-keyint_min', '12',
    '-movflags', '+faststart',
    '-c:a', 'aac',
    '-b:a', '320k',
    output_mp4
]
res = subprocess.run(final_cmd, capture_output=True, text=True)
if res.returncode != 0:
    print('Final render error:', res.stderr)
    exit(1)

print(f'Rendered Act 2 successfully: {output_mp4} ({time.time()-t1:.1f}s)')
print('Launching in QuickTime Player...')
subprocess.run(['open', '-a', 'QuickTime Player', output_mp4])
