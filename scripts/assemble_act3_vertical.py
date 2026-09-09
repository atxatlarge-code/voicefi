#!/Users/jaketrigg/Projects/VoiceFi/.venv/bin/python
import os
import subprocess
import time
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

base_dir = '/Users/jaketrigg/Projects/VoiceFi/assets/reels'
audio_master = os.path.join(base_dir, 'spicewood_outlaws_master_vocal_mix.wav')
work_dir = '/tmp/spicewood_act3_vertical_work'
os.makedirs(work_dir, exist_ok=True)
output_mp4 = '/Users/jaketrigg/Desktop/spicewood_act3_vertical_9_16.mp4'

# Act 3 spans 02:30.62 to 04:21.44 (dur = 110.82s)
ACT_START = 150.62
ACT_END = 261.44
ACT_DUR = round(ACT_END - ACT_START, 2)

# Curated 43-shot measure-locked sequence for 9:16 vertical (1080x1920)
shots = [
    # Section 1: Porch Whittling, Tube Glow & Wisdom (150.62 - 161.56s)
    ('3.01',  150.62, 154.50, 'spicewood_act3_downloaded_scenes/Scene_01_3.01_Sunset_Canyon.mp4', 0.0, 'ambient_blur'),
    ('3.02',  154.50, 157.00, 'spicewood_act3_downloaded_scenes/Scene_04_3.04_Porch_Whittling.mp4', 0.0, 'center'),
    ('3.03',  157.00, 159.34, 'spicewood_act3_raw/Tube_amplifier_glowing_on_shelf_202609031636.mp4', 0.0, 'center'),
    ('3.04',  159.34, 161.56, 'spicewood_act3_downloaded_scenes/Scene_03_3.03_Cicada_Macro.mp4', 0.0, 'center'),

    # Section 2: Willie's Trigger & Vintage Reel (161.56 - 170.64s)
    ('3.05a', 161.56, 162.54, 'spicewood_act3_downloaded_scenes/Scene_06_3.07a_Trigger_Guitar_Picking.mp4', 0.0, 'center'),
    ('3.05b', 162.54, 163.40, 'spicewood_act3_downloaded_scenes/Scene_07_3.07b_Trigger_Guitar_Body.mp4', 0.0, 'center'),
    ('3.05c', 163.40, 164.38, 'spicewood_act3_downloaded_scenes/Scene_08_3.07c_Trigger_Guitar_Neck.mp4', 0.0, 'center'),
    ('3.06',  164.38, 167.08, 'spicewood_act3_downloaded_scenes/Scene_09_3.08_Reel_To_Reel_Tape.mp4', 0.0, 'center'),
    ('3.07',  167.08, 170.64, 'spicewood_act3_downloaded_scenes/Scene_10_3.10_Bluebonnet_Ridge.mp4', 0.0, 'ambient_blur'),

    # Section 3: Speed Verse / Rapid-Fire 786 (170.64 - 192.06s)
    ('3.08',  170.64, 174.30, 'spicewood_hero_selects/Act_3/Shot_3.09_Roadhouse_Pool_Table.mp4', 0.0, 'center'),
    ('3.09',  174.30, 176.88, 'spicewood_act3_downloaded_scenes/Scene_12_3.11_Turquoise_Zippo_Snap.mp4', 0.0, 'center'),
    ('3.10',  176.88, 178.56, 'spicewood_act3_downloaded_scenes/Scene_11_3.12_Grandfather_Clock.mp4', 0.0, 'center'),
    ('3.11',  178.56, 180.98, 'spicewood_act3_downloaded_scenes/Scene_13_3.13_Tavern_Bourbon_Toast.mp4', 0.0, 'center'),
    ('3.12a', 180.98, 182.50, 'spicewood_act3_downloaded_scenes/Scene_14_3.14a_Neon_Jukebox_Wide.mp4', 0.0, 'center'),
    ('3.12b', 182.50, 183.84, 'spicewood_act3_downloaded_scenes/Scene_15_3.14b_Neon_Jukebox_Turntable.mp4', 0.0, 'center'),
    ('3.13',  183.84, 186.82, 'spicewood_act3_downloaded_scenes/Scene_16_3.15_Tractor_Hayride.mp4', 0.0, 'center'),
    ('3.14a', 186.82, 188.60, 'spicewood_act3_downloaded_scenes/Scene_17_3.16a_Outlaw_Tailgate_Hero.mp4', 0.0, 'center'),
    ('3.14b', 188.60, 190.40, 'spicewood_act3_downloaded_scenes/Scene_18_3.16b_Outlaw_Tailgate_Medium.mp4', 0.0, 'center'),
    ('3.14c', 190.40, 192.06, 'spicewood_hero_selects/Act_3/Shot_3.16_Outlaw_Tailgate_Dusk.mp4', 0.0, 'center'),

    # Section 4: The Turnaround Buildup (192.06 - 201.12s)
    ('3.15',  192.06, 196.00, 'spicewood_act3_downloaded_scenes/Scene_20_3.17_Elder_Rancher_Speaking.mp4', 0.0, 'center'),
    ('3.16',  196.00, 199.50, 'spicewood_act3_downloaded_scenes/Scene_21_3.18_Outlaw_Gravel_Walk.mp4', 0.0, 'center'),
    ('3.17',  199.50, 201.12, 'spicewood_act3_downloaded_scenes/Scene_22_3.19_Truck_Headlights_Flare.mp4', 0.0, 'center'),

    # Section 5: Climax Hook 3 / Grand Outlaw Anthem (201.12 - 229.41s)
    ('3.18',  201.12, 203.95, 'spicewood_act3_raw/Campfire_erupts_with_roaring_flames_202609031636.mp4', 0.0, 'center'),
    ('3.19',  203.95, 206.77, 'spicewood_act3_raw/Bonfire_exploding_into_starry_night_202609031636.mp4', 0.0, 'center'),
    ('3.20',  206.77, 209.60, 'spicewood_act2_raw/Act_II:_Outlaw_Anthem_&_202609031546_2.mp4', 0.50, 'center'),
    ('3.21',  209.60, 212.42, 'spicewood_act3_raw/Barbecue_smoke_yard_at_sunset_202609031636.mp4', 0.0, 'ambient_blur'),
    ('3.22',  212.42, 215.25, 'spicewood_act3_raw/Horseback_riders_trotting_on_ridge_202609031636.mp4', 0.0, 'center'),
    ('3.23',  215.25, 218.07, 'spicewood_act3_raw/Texas_Longhorn_steer_standing_in…_202609031635.mp4', 0.0, 'center'),
    ('3.24',  218.07, 220.90, 'spicewood_act3_raw/03_texas_armadillos_lawn.mp4', 1.0, 'center'),
    ('3.25',  220.90, 223.72, 'spicewood_act3_raw/Truck_drifting_on_gravel_river_202609031636.mp4', 0.0, 'center'),
    ('3.26',  223.72, 226.55, 'spicewood_act3_raw/Lake_Travis_panoramic_view_202609031636.mp4', 0.0, 'ambient_blur'),
    ('3.27',  226.55, 229.41, 'spicewood_act3_raw/Limestone_campfire_erupts_with_f…_202609031636.mp4', 0.0, 'center'),

    # Section 6: Authentic Hill Country Outro & Texas Goodnight (229.41 - 261.44s)
    ('3.28',  229.41, 233.00, 'spicewood_act3_outro/01_waterfall_ferns.mp4',    0.0, 'center'),
    ('3.29',  233.00, 236.60, 'spicewood_act3_outro/02_spring_face_splash.mp4', 0.0, 'ambient_blur'),
    ('3.30',  236.60, 240.20, 'spicewood_act3_outro/03_texas_armadillos_lawn.mp4',     7.0, 'ambient_blur'),
    ('3.31',  240.20, 243.80, 'spicewood_act3_outro/04_cypress_spring_pool.mp4',     2.0, 'ambient_blur'),
    ('3.32',  243.80, 247.40, 'spicewood_act3_outro/05_bluebonnet_bluff.mp4',        1.5, 'ambient_blur'),
    ('3.33',  247.40, 251.00, 'spicewood_act3_outro/06_country_buggy_ride.mp4',      2.0, 'ambient_blur'),
    ('3.34',  251.00, 256.65, 'spicewood_act3_outro/08_dramatic_sky_lake_sunset.jpg', 0.0, 'kenburns'),
    ('3.35',  256.65, 261.44, 'spicewood_act3_outro/09_lake_twilight.mp4',           2.0, 'center')
]

base_video = os.path.join(work_dir, 'act3_vertical_base_video.mp4')
if not os.path.exists(base_video):
    print(f'Slicing {len(shots)} Act 3 vertical 9:16 video shots (1080x1920)...')
    t0 = time.time()
    seg_files = []
    for idx, item in enumerate(shots, 1):
        shot_id = item[0]
        start_t = item[1]
        end_t = item[2]
        rel_path = item[3]
        src_in = item[4] if len(item) > 4 else 0.0
        mode = item[5] if len(item) > 5 else 'center'
        
        dur = round(end_t - start_t, 3)
        src_file = os.path.join(base_dir, rel_path)
        out_seg = os.path.join(work_dir, f'seg_{idx:03d}.mp4')
        
        is_img = src_file.lower().endswith(('.jpg', '.jpeg', '.png'))
        num_frames = int(round(dur * 24))
        
        if is_img:
            vf = f'[0:v]scale=2560:1440,zoompan=z=\'min(zoom+0.0005,1.15)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={num_frames}:s=1080x1920:fps=24,format=yuv420p,setsar=1[v]'
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1',
                '-i', src_file,
                '-t', str(dur),
                '-filter_complex', vf,
                '-map', '[v]',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                out_seg
            ]
        elif mode == 'ambient_blur':
            vf = '[0:v]split=2[fg][bg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];[fg]scale=1080:-1[fg];[bg][fg]overlay=0:(H-h)/2,format=yuv420p,setsar=1,fps=24[v]'
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(src_in),
                '-i', src_file,
                '-t', str(dur),
                '-filter_complex', vf,
                '-map', '[v]',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                out_seg
            ]
        else:
            vf = '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(in_w-1080)/2:0,format=yuv420p,setsar=1,fps=24[v]'
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(src_in),
                '-i', src_file,
                '-t', str(dur),
                '-filter_complex', vf,
                '-map', '[v]',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                out_seg
            ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        seg_files.append(out_seg)

    concat_list = os.path.join(work_dir, 'video_concat.txt')
    with open(concat_list, 'w') as f:
        for s in seg_files:
            f.write(f"file '{s}'\n")

    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_list,
        '-c', 'copy',
        base_video
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    print(f'Base vertical video compiled ({time.time()-t0:.1f}s)')
else:
    print(f'Using existing cached base vertical video: {base_video}')

# 2. Comic Burst Generator (Scaled for 1080x1920)
def create_comic_burst(text, bg='#FFE500', shadow='#D50000', stroke='#000000', text_c='#FFFFFF', shape='star', angle=-8, w=420, h=200, spikes=18):
    scale = 2
    sw, sh = w * scale, h * scale
    cx, cy = sw // 2, sh // 2
    points = []
    random.seed(len(text) * 11 + 42)
    
    for i in range(spikes * 2):
        a = i * (math.pi / spikes)
        is_outer = (i % 2 == 0)
        j = random.uniform(0.95, 1.05)
        if shape == 'shock':
            rx = (sw * 0.46) if is_outer else (sw * 0.28)
            ry = (sh * 0.46) if is_outer else (sh * 0.26)
        elif shape == 'flame':
            rx = (sw * 0.48) if is_outer else (sw * 0.33)
            ry = (sh * 0.44) if is_outer else (sh * 0.29)
        elif shape == 'cloud':
            rx = (sw * 0.44) if is_outer else (sw * 0.35)
            ry = (sh * 0.42) if is_outer else (sh * 0.33)
        else:
            rx = (sw * 0.44) if is_outer else (sw * 0.31)
            ry = (sh * 0.44) if is_outer else (sh * 0.30)
        points.append((cx + rx * j * math.cos(a), cy + ry * j * math.sin(a)))
        
    canvas = Image.new('RGBA', (sw + 60*scale, sh + 60*scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    
    s_off = 12 * scale
    draw.polygon([(p[0] + s_off, p[1] + s_off) for p in points], fill='#000000')
    a_off = 6 * scale
    draw.polygon([(p[0] + a_off, p[1] + a_off) for p in points], fill=shadow)
    draw.polygon(points, fill=bg)
    draw.line(points + [points[0]], fill=stroke, width=6 * scale, joint='curve')
    
    font_size = 42 if len(text) <= 10 else 34
    font = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', font_size * scale, index=1)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = cx - tw // 2, cy - th // 2 - 2 * scale
    
    if text_c == '#FFFFFF':
        stroke_w = 4 * scale
        for dx in range(-stroke_w, stroke_w + 1, scale):
            for dy in range(-stroke_w, stroke_w + 1, scale):
                if dx*dx + dy*dy <= stroke_w*stroke_w:
                    draw.text((tx + dx, ty + dy), text, font=font, fill='#000000')
    else:
        draw.text((tx + 2*scale, ty + 2*scale), text, font=font, fill='rgba(0,0,0,120)')
        
    draw.text((tx, ty), text, font=font, fill=text_c)
    downscaled = canvas.resize((canvas.width // scale, canvas.height // scale), Image.Resampling.LANCZOS)
    return downscaled.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

# Pre-render Act 3 comic hype bursts positioned for 1080x1920 (upper-third action band)
# Micro-calibrated to acoustic vocal onsets & offsets
hype_bursts = {
    'pew_pew': {
        'start': 13.80,
        'end': 14.45,
        'pos': (540, 460),
        'img': create_comic_burst('pew pew', bg='#E040FB', shadow='#00E5FF', stroke='#000000', text_c='#FFFFFF', shape='shock', angle=-15, w=400, h=190)
    },
    'tik_tok': {
        'start': 26.60,
        'end': 27.94,
        'pos': (500, 480),
        'img': create_comic_burst('t-t-tik tok tik', bg='#FFF59D', shadow='#FF6D00', stroke='#000000', text_c='#000000', shape='cloud', angle=7, w=490, h=200)
    }
}

# 3. Lyric Karaoke Subtitle Events
lyrics_timeline = [
    # 3.01: 150.62 - 155.98 (Local 0.00 - 5.36)
    {
        'start': 0.00, 'end': 5.36,
        'words': [
            ("Outlaw", 0.00, 1.80), ("lifestyle", 1.80, 3.82), ("counting", 3.82, 4.74),
            ("the", 4.74, 5.00), ("days", 5.00, 5.36)
        ]
    },
    # 3.02: 156.26 - 159.34 (Local 5.64 - 8.72)
    {
        'start': 5.64, 'end': 8.72,
        'words': [
            ("Porch", 5.64, 5.94), ("swing", 5.94, 6.28), ("rockin'", 6.28, 6.84),
            ("in", 7.18, 7.56), ("outlaw", 7.56, 8.04), ("ways...", 8.04, 8.72)
        ]
    },
    # 3.03 - 3.04: 159.34 - 161.56 (Local 8.72 - 10.94)
    {
        'start': 8.72, 'end': 10.94,
        'words': [
            ("In", 8.72, 9.10), ("the", 9.10, 9.40), ("timeless", 9.40, 9.74),
            ("rhythm,", 9.74, 10.08), ("AND", 10.08, 10.40), ("I", 10.40, 10.58),
            ("WILL", 10.58, 10.75), ("AMAZE,", 10.75, 10.94)
        ]
    },
    # 3.05: 161.56 - 164.38 (Local 10.94 - 13.76)
    {
        'start': 10.94, 'end': 13.76,
        'words': [
            ("Willie", 10.94, 11.56), ("pickin'", 11.56, 12.02), ("Trigger,", 12.02, 12.50),
            ("GUNS", 12.50, 13.10), ("ABLAZE!", 13.10, 13.76)
        ]
    },
    # 3.06: 164.38 - 167.08 (Local 13.76 - 16.46)
    {
        'start': 13.76, 'end': 16.46,
        'words': [
            ("Spin", 13.76, 14.20), ("the", 14.20, 14.38), ("vintage", 14.38, 14.66),
            ("reel,", 14.66, 15.36), ("LET", 15.36, 15.60), ("THE", 15.60, 15.78),
            ("RECORD", 15.78, 16.02), ("PLAY", 16.02, 16.46)
        ]
    },
    # 3.07: 167.08 - 170.64 (Local 16.46 - 20.02)
    {
        'start': 16.46, 'end': 20.02,
        'words': [
            ("7-8-6", 16.46, 17.66), ("in", 17.66, 18.06), ("the", 18.06, 18.20),
            ("spotlight", 18.20, 18.70), ("flicks,", 18.70, 19.14), ("in", 19.14, 19.48),
            ("the", 19.48, 19.70), ("bluebonnet", 19.70, 20.02)
        ]
    },
    # 3.08: 170.64 - 174.30 (Local 20.02 - 23.68)
    {
        'start': 20.02, 'end': 23.68,
        'words': [
            ("fields", 20.02, 20.74), ("where", 20.74, 20.84), ("the", 20.84, 21.08),
            ("feed", 21.08, 21.80), ("is", 21.80, 21.92), ("sick,", 21.92, 22.34),
            ("LOW-KEY", 22.34, 22.92), ("LYRICIST...", 22.92, 23.68)
        ]
    },
    # 3.09: 174.30 - 176.88 (Local 23.68 - 26.26)
    {
        'start': 23.68, 'end': 26.26,
        'words': [
            ("...pull", 23.68, 23.92), ("a", 23.92, 24.14), ("magic", 24.14, 24.42),
            ("trick", 24.42, 24.72), ("in", 24.72, 25.06), ("EVERY", 25.06, 25.50),
            ("SINGLE", 25.50, 25.86), ("RHYME", 25.86, 26.26)
        ]
    },
    # 3.10: 176.88 - 178.56 (Local 26.26 - 27.94)
    {
        'start': 26.26, 'end': 27.94,
        'words': [
            ("...like", 26.26, 26.48), ("a", 26.48, 26.60), ("t-t-tik", 26.60, 26.98),
            ("tok", 26.98, 27.62), ("tik...", 27.62, 27.94)
        ]
    },
    # 3.11: 178.56 - 180.98 (Local 27.94 - 30.36)
    {
        'start': 27.94, 'end': 30.36,
        'words': [
            ("Raise", 27.94, 28.46), ("that", 28.46, 28.68), ("glass", 28.68, 28.90),
            ("in", 28.90, 29.26), ("the", 29.26, 29.36), ("SEVEN-EIGHT-SIX,", 29.36, 30.36)
        ]
    },
    # 3.12: 180.98 - 183.84 (Local 30.36 - 33.22)
    {
        'start': 30.36, 'end': 33.22,
        'words': [
            ("...and", 30.36, 30.70), ("the", 30.70, 30.86), ("outlaw", 30.86, 31.40),
            ("music", 31.40, 31.96), ("IN", 31.96, 32.26), ("A", 32.26, 32.40),
            ("MIDNIGHT", 32.40, 32.80), ("MIX", 32.80, 33.22)
        ]
    },
    # 3.13: 183.84 - 186.58 (Local 33.22 - 35.96)
    {
        'start': 33.22, 'end': 35.96,
        'words': [
            ("...and", 33.22, 33.48), ("a", 33.48, 33.56), ("bumpy", 33.56, 34.10),
            ("hayride,", 34.10, 34.56), ("THERE'S", 34.56, 34.82), ("NOTHIN'", 34.82, 35.20),
            ("TO", 35.20, 35.54), ("FIX,", 35.54, 35.96)
        ]
    },
    # 3.14: 186.58 - 190.24 (Local 35.96 - 39.62)
    {
        'start': 35.96, 'end': 39.62,
        'words': [
            ("I'ma", 35.96, 36.30), ("Spicewood", 36.30, 36.84), ("legend,", 36.84, 37.24),
            ("SEVEN-EIGHT-SIX!", 37.24, 38.74), ("(6-9!)", 38.74, 39.62)
        ]
    },
    # 3.15: 192.06 - 196.00 (Local 41.44 - 45.38)
    {
        'start': 41.44, 'end': 45.38,
        'words': [
            ("Man,", 41.50, 42.10), ("I", 42.10, 42.30), ("tell", 42.30, 42.50),
            ("you", 42.50, 42.70), ("what,", 42.70, 43.00), ("Hank...", 43.00, 43.50),
            ("talkin'", 43.50, 43.80), ("'bout", 43.80, 44.10), ("that", 44.10, 44.30),
            ("meanin'", 44.30, 44.70), ("of", 44.70, 44.90), ("life...", 44.90, 45.38)
        ]
    },
    # 3.16: 196.00 - 199.50 (Local 45.38 - 48.88)
    {
        'start': 45.38, 'end': 48.88,
        'words': [
            ("...man,", 45.38, 45.80), ("it's", 45.80, 46.20), ("like", 46.20, 46.60),
            ("a", 46.60, 46.80), ("butterfly", 46.80, 47.40), ("flappin'", 47.40, 47.90),
            ("his", 47.90, 48.10), ("wings...", 48.10, 48.88)
        ]
    },
    # 3.17: 199.50 - 201.12 (Local 48.88 - 50.50)
    {
        'start': 48.88, 'end': 50.50,
        'words': [
            ("...deep", 48.88, 49.10), ("down", 49.10, 49.40), ("in", 49.40, 49.60),
            ("the", 49.60, 49.80), ("forest,", 49.80, 50.10), ("man.", 50.10, 50.50)
        ]
    },
    # 3.18: 201.12 - 203.52 (Local 50.50 - 52.90)
    {
        'start': 50.50, 'end': 52.90,
        'words': [
            ("OUT", 50.50, 50.90), ("HERE", 50.90, 51.20), ("WE", 51.20, 51.56),
            ("IN", 51.56, 51.72), ("OUTLAW", 51.72, 52.20), ("COUNTRY!", 52.20, 52.90)
        ]
    },
    # 3.19: 204.36 - 206.02 (Local 53.74 - 55.40)
    {
        'start': 53.74, 'end': 55.40,
        'words': [
            ("JUST", 53.74, 54.34), ("FOR", 54.34, 54.54),
            ("OUTLAWS", 54.54, 55.00), ("SAKE!", 55.00, 55.40)
        ]
    },
    # 3.20: 206.62 - 209.20 (Local 56.00 - 58.58)
    {
        'start': 56.00, 'end': 58.58,
        'words': [
            ("Out", 56.00, 56.46), ("here", 56.46, 56.80), ("we", 56.80, 57.14),
            ("judge", 57.14, 57.58), ("a", 57.58, 57.92), ("brisket...", 57.92, 58.58)
        ]
    },
    # 3.21: 210.06 - 211.74 (Local 59.44 - 61.12)
    {
        'start': 59.44, 'end': 61.12,
        'words': [
            ("...by", 59.44, 59.90), ("how", 59.90, 60.38), ("long", 60.38, 60.64),
            ("it", 60.64, 60.85), ("take...", 60.85, 61.12)
        ]
    },
    # 3.22: 212.20 - 214.66 (Local 61.58 - 64.04)
    {
        'start': 61.58, 'end': 64.04,
        'words': [
            ("Out", 61.58, 62.04), ("here", 62.04, 62.42), ("we", 62.42, 62.76),
            ("raisin'", 62.76, 63.48), ("breeds...", 63.48, 64.04)
        ]
    },
    # 3.23: 214.66 - 216.62 (Local 64.04 - 66.00)
    {
        'start': 64.04, 'end': 66.00,
        'words': [
            ("...that", 64.04, 64.80), ("are", 64.80, 65.20),
            ("very", 65.20, 65.56), ("rare...", 65.56, 66.00)
        ]
    },
    # 3.24: 217.70 - 220.04 (Local 67.08 - 69.42)
    {
        'start': 67.08, 'end': 69.42,
        'words': [
            ("They", 67.08, 67.54), ("say", 67.54, 68.06), ("we're", 68.06, 68.62),
            ("all", 68.62, 68.90), ("out", 68.90, 69.10), ("here...", 69.10, 69.42)
        ]
    },
    # 3.25: 220.54 - 222.18 (Local 69.92 - 71.56)
    {
        'start': 69.92, 'end': 71.56,
        'words': [
            ("'Cause", 69.92, 70.38), ("we're", 70.38, 70.62),
            ("not", 70.62, 71.02), ("all", 71.02, 71.20), ("there...", 71.20, 71.56)
        ]
    },
    # 3.26: 224.76 - 225.68 (Local 74.14 - 75.06)
    {
        'start': 74.14, 'end': 75.06,
        'words': [
            ("Summertime...", 74.14, 75.06)
        ]
    },
    # 3.27: 226.56 - 229.76 (Local 75.94 - 79.14)
    {
        'start': 75.94, 'end': 79.14,
        'words': [
            ("...and", 75.94, 76.40), ("the", 76.40, 77.08),
            ("living", 77.08, 77.90), ("is", 77.90, 78.30), ("easy...", 78.30, 79.14)
        ]
    }
]

# 4. Outro Master Credit Card Generator (Scaled for 1080x1920)
def create_outro_card():
    scale = 2
    w, h = 880 * scale, 340 * scale
    card = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    
    draw.rounded_rectangle([(0, 0), (w, h)], radius=18*scale, fill=(10, 10, 15, 225), outline=(245, 158, 11, 180), width=3*scale)
    
    f_title = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 38 * scale, index=1)
    f_by = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 24 * scale, index=0)
    f_credit = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 20 * scale, index=0)
    
    cx = w // 2
    draw.text((cx, 46 * scale), 'SPICEWOOD OUTLAWS', font=f_title, fill='#FFFFFF', anchor='mm')
    draw.text((cx, 98 * scale), 'by vifi', font=f_by, fill='#F59E0B', anchor='mm')
    
    draw.line([(cx - 260 * scale, 140 * scale), (cx + 260 * scale, 140 * scale)], fill='rgba(255, 255, 255, 60)', width=2*scale)
    
    draw.text((cx, 190 * scale), 'Instrumental Beat: "Society" by Shinra B', font=f_credit, fill='#F3F4F6', anchor='mm')
    draw.text((cx, 246 * scale), 'Vocal Production & AI Direction: VoiceFi Productions', font=f_credit, fill='#D1D5DB', anchor='mm')
    draw.text((cx, 294 * scale), 'Universal Voice Layer for AI Agents · voicefi.org', font=f_credit, fill='#94A3B8', anchor='mm')
    
    return card.resize((card.width // scale, card.height // scale), Image.Resampling.LANCZOS)

outro_card_img = create_outro_card()
OUTRO_CARD_START = 104.00
OUTRO_CARD_END = ACT_DUR

# Generate discrete time boundaries
time_points = {0.0, ACT_DUR, OUTRO_CARD_START, OUTRO_CARD_END}
for p in lyrics_timeline:
    time_points.add(p['start'])
    time_points.add(p['end'])
    for w in p['words']:
        time_points.add(w[1])
        time_points.add(w[2])

for h in hype_bursts.values():
    time_points.add(h['start'])
    time_points.add(h['end'])

sorted_times = sorted([t for t in time_points if 0.0 <= t <= ACT_DUR])

# Subtitle Font & Layout for 1080x1920
sub_font = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 50, index=1)
space_w = sub_font.getbbox(' ')[2] - sub_font.getbbox(' ')[0]

def layout_words(words_list, max_w=900):
    lines = []
    cur_line = []
    cur_w = 0
    for widx, (w, s, e) in enumerate(words_list):
        bbox = sub_font.getbbox(w)
        w_w = bbox[2] - bbox[0]
        needed = w_w if not cur_line else (space_w + w_w)
        
        break_line = False
        if cur_line:
            prev_w = cur_line[-1][1].rstrip()
            
            # Rule 1: Break after comma if cur_line has >= 2 words (or keyword) and upcoming words exist
            if prev_w.endswith(','):
                remaining = words_list[widx:]
                has_bold_punchline = any(rw[0].isupper() and len(rw[0]) > 1 for rw in remaining)
                if has_bold_punchline or len(remaining) >= 2 or remaining[0][0].isupper():
                    if len(cur_line) >= 2 or prev_w.lower() in ('pedernales,', 'colorado,'):
                        break_line = True
                        
            # Rule 2: Break before all-caps bold punchline after ellipsis or lowercase setup
            elif prev_w.endswith('...') and w.isupper() and len(w) > 1:
                break_line = True
            elif not prev_w.isupper() and w.isupper() and len(w) > 1:
                remaining = words_list[widx:]
                if len(remaining) >= 2 and all(rw[0].isupper() or len(rw[0]) <= 2 for rw in remaining):
                    if len(cur_line) >= 3:
                        break_line = True

        if cur_line and (break_line or (cur_w + needed > max_w)):
            lines.append(cur_line)
            cur_line = [(widx, w, w_w)]
            cur_w = w_w
        else:
            cur_line.append((widx, w, w_w))
            cur_w += needed
    if cur_line:
        lines.append(cur_line)
    return lines

print(f'Rendering {len(sorted_times)-1} vertical overlay time slices (1080x1920)...')
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
            
    active_hypes = []
    for h_name, h_info in hype_bursts.items():
        if h_info['start'] <= t_start < h_info['end']:
            active_hypes.append(h_info)
            
    frame = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
    
    if active_phrase:
        active_idx = -1
        last_spoken_idx = -1
        for widx, w in enumerate(active_phrase['words']):
            if w[1] <= t_start < w[2]:
                active_idx = widx
                break
            elif t_start >= w[2]:
                last_spoken_idx = widx
                
        lines = layout_words(active_phrase['words'], max_w=900)
        line_h = 64
        total_h = len(lines) * line_h
        sy_base = 1420 - total_h // 2
        
        # 1. 3D Shadow Layer with Blur
        shadow = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        for l_idx, line in enumerate(lines):
            line_w = sum(x[2] for x in line) + space_w * (len(line) - 1)
            cx = (1080 - line_w) // 2
            cy = sy_base + l_idx * line_h
            for widx, w, w_w in line:
                sdraw.text((cx + 3, cy + 4), w, font=sub_font, fill=(0, 0, 0, 230))
                cx += w_w + space_w
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=3.0))
        frame.alpha_composite(shadow)
        
        # 2. Text Layer with Amber Gold Active Word Glow
        tdraw = ImageDraw.Draw(frame)
        for l_idx, line in enumerate(lines):
            line_w = sum(x[2] for x in line) + space_w * (len(line) - 1)
            cx = (1080 - line_w) // 2
            cy = sy_base + l_idx * line_h
            for widx, w, w_w in line:
                if widx == active_idx:
                    color = (245, 158, 11, 255) # Texas Amber Gold
                elif widx < active_idx or (active_idx == -1 and widx <= last_spoken_idx):
                    color = (255, 255, 255, 245) # Spoken white
                else:
                    color = (156, 163, 175, 230) # Upcoming grey
                tdraw.text((cx, cy), w, font=sub_font, fill=color)
                cx += w_w + space_w
                
    for h in active_hypes:
        frame.alpha_composite(h['img'], dest=h['pos'])
        
    if OUTRO_CARD_START <= t_start < OUTRO_CARD_END:
        dest_x = (1080 - 880) // 2
        dest_y = 790
        frame.alpha_composite(outro_card_img, dest=(dest_x, dest_y))
        
    png_path = os.path.join(work_dir, f'ovl_{i:04d}.png')
    frame.save(png_path)
    plan_lines.append(f"file '{png_path}'\nduration {dur:.3f}\n")

if plan_lines:
    plan_lines.append(plan_lines[-1].split('\n')[0] + '\n')

with open(plan_file, 'w') as f:
    f.writelines(plan_lines)

print('Compositing Act 3 vertical master with 24-bit audio & karaoke overlay...')
t1 = time.time()

# Extract 24-bit PCM master audio slice
audio_slice = os.path.join(work_dir, 'act3_audio_master.wav')
subprocess.run([
    'ffmpeg', '-y',
    '-ss', str(ACT_START), '-t', str(ACT_DUR),
    '-i', audio_master,
    '-c:a', 'pcm_s24le',
    '-ar', '44100',
    audio_slice
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

needle_sfx = '/Users/jaketrigg/Projects/VoiceFi/assets/audio/sfx/needle_drop/NeedleDrop02.mp3'
audio_mixed = os.path.join(work_dir, 'act3_audio_mixed.wav')
if os.path.exists(needle_sfx):
    delay_ms = int((182.60 - ACT_START) * 1000)
    filter_mix = f'[1:a]aresample=44100,adelay={delay_ms}|{delay_ms},volume=0.45[sfx];[0:a][sfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]'
    subprocess.run([
        'ffmpeg', '-y',
        '-i', audio_slice,
        '-i', needle_sfx,
        '-filter_complex', filter_mix,
        '-map', '[a]',
        '-c:a', 'pcm_s24le',
        '-ar', '44100',
        audio_mixed
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
else:
    audio_mixed = audio_slice

final_cmd = [
    'ffmpeg', '-y',
    '-i', base_video,
    '-f', 'concat', '-safe', '0', '-i', plan_file,
    '-i', audio_mixed,
    '-filter_complex', '[1:v]fps=24[ovl];[0:v][ovl]overlay=0:0[v]',
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
    '-ar', '44100',
    output_mp4
]
res = subprocess.run(final_cmd, capture_output=True, text=True)
if res.returncode != 0:
    print('Final vertical render error:', res.stderr)
    exit(1)

print(f'Rendered Act 3 Vertical successfully: {output_mp4} ({time.time()-t1:.1f}s)')
