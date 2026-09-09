#!/Users/jaketrigg/Projects/VoiceFi/.venv/bin/python
import os
import subprocess
import time
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

base_dir = '/Users/jaketrigg/Projects/VoiceFi/assets/reels'
audio_master = os.path.join(base_dir, 'spicewood_outlaws_master_vocal_mix.wav')
work_dir = '/tmp/spicewood_act1_vertical_work'
os.makedirs(work_dir, exist_ok=True)
output_mp4 = '/Users/jaketrigg/Desktop/spicewood_act1_vertical_9_16.mp4'

# Shot decision table for Act 1: 9:16 vertical framing modes
# mode can be: 'center' (full bleed 1080x1920), 'ambient_blur' (cinematic wide landscape with blurred extension)
shots = [
    ('1.01', 0.00, 2.82, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_2.mp4', 0.0, 'center'),
    ('1.02', 2.82, 5.04, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708.mp4', 0.0, 'center'),
    ('1.03', 5.04, 8.47, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_3.mp4', 0.0, 'center'),
    ('1.04', 8.47, 10.98, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_6.mp4', 0.0, 'center'),
    ('1.05', 10.98, 13.80, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_4.mp4', 1.30, 'center'),
    ('1.06', 13.80, 16.63, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_22.mp4', 0.0, 'center'),
    ('1.07', 16.63, 19.45, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_14.mp4', 0.0, 'center'),
    ('1.08', 19.45, 22.28, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_15.mp4', 0.0, 'ambient_blur'),
    ('1.09', 22.28, 25.10, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_7.mp4', 1.19, 'center'),
    ('1.10', 25.10, 27.93, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_16.mp4', 0.0, 'center'),
    ('1.11', 27.93, 30.75, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_8.mp4', 0.0, 'center'),
    ('1.12', 30.75, 33.46, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_9.mp4', 1.00, 'center'),
    ('1.13', 33.46, 36.28, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_5.mp4', 0.0, 'center'),
    ('1.14', 36.28, 39.11, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_17.mp4', 0.0, 'ambient_blur'),
    ('1.15', 39.11, 41.93, 'spicewood_act3_raw/Man_driving_vintage_pickup_truck_202609031636.mp4', 0.50, 'center'),
    ('1.16', 41.93, 44.08, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_21.mp4', 0.0, 'ambient_blur'),
    ('1.17a', 44.08, 46.50, 'spicewood_act1_raw/Outlaw_swinging_over_green_river_202609040621.mp4', 0.0, 'center'),
    ('1.17b', 46.50, 49.00, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_20.mp4', 0.5, 'center'),
    ('1.18', 49.00, 51.72, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_10.mp4', 0.0, 'ambient_blur'),
    ('1.19_1.20', 51.72, 55.56, 'spicewood_act1_raw/Act_I:_The_Rural_Inception_202609030708_12.mp4', 0.17, 'center')
]

base_video = os.path.join(work_dir, 'act1_vertical_base_video.mp4')
if not os.path.exists(base_video):
    print(f'Slicing {len(shots)} Act 1 vertical 9:16 video shots (1080x1920)...')
    t0 = time.time()
    seg_files = []
    for idx, item in enumerate(shots, 1):
        shot_id = item[0]
        start_t = item[1]
        end_t = item[2]
        rel_path = item[3]
        ss_offset = item[4]
        mode = item[5] if len(item) > 5 else 'center'
        
        dur = round(end_t - start_t, 3)
        src_file = os.path.join(base_dir, rel_path)
        out_seg = os.path.join(work_dir, f'seg_{idx:03d}.mp4')
        
        if mode == 'ambient_blur':
            vf = '[0:v]split=2[fg][bg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];[fg]scale=1080:-1[fg];[bg][fg]overlay=0:(H-h)/2,setsar=1,fps=24,format=yuv420p[v]'
        else:
            vf = '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(in_w-1080)/2:0,setsar=1,fps=24,format=yuv420p[v]'
            
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(ss_offset),
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
    
    # 3D Base Shadow
    s_off = 12 * scale
    draw.polygon([(p[0] + s_off, p[1] + s_off) for p in points], fill='#000000')
    
    # Accent Underlay
    a_off = 6 * scale
    draw.polygon([(p[0] + a_off, p[1] + a_off) for p in points], fill=shadow)
    
    # Main Burst
    draw.polygon(points, fill=bg)
    draw.line(points + [points[0]], fill=stroke, width=6 * scale, joint='curve')
    
    # Font
    font_size = 42 if len(text) <= 10 else 36
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

# 2b. Feminine Comic Burst Generator (Hype Woman, Scaled for 1080x1920)
def create_feminine_burst(
    text,
    bg='#FF1493',
    shadow='#4A0026',
    accent='#FFD700',
    stroke='#260014',
    text_c='#FFFFFF',
    angle=-7,
    w=420,
    h=190,
    lobes=12,
    font_size=46,
    sparkles=True
):
    scale = 2
    sw, sh = w * scale, h * scale
    cx, cy = sw // 2, sh // 2
    
    num_pts = 360
    points = []
    r_base_x = sw * 0.38
    r_base_y = sh * 0.35
    amp_x = sw * 0.08
    amp_y = sh * 0.08
    
    for deg in range(num_pts):
        rad = math.radians(deg)
        lobe_mod = math.pow(abs(math.cos(rad * lobes / 2.0)), 0.6)
        rx = r_base_x + amp_x * lobe_mod
        ry = r_base_y + amp_y * lobe_mod
        px = cx + rx * math.cos(rad)
        py = cy + ry * math.sin(rad)
        points.append((px, py))
        
    canvas = Image.new('RGBA', (sw + 80*scale, sh + 80*scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    
    ox, oy = 40 * scale, 40 * scale
    shifted_points = [(p[0] + ox, p[1] + oy) for p in points]
    
    # 1. 3D Base Shadow
    s_off_x, s_off_y = 10 * scale, 12 * scale
    draw.polygon([(p[0] + s_off_x, p[1] + s_off_y) for p in shifted_points], fill=shadow)
    
    # 2. Accent Underlay
    a_off_x, a_off_y = 5 * scale, 6 * scale
    draw.polygon([(p[0] + a_off_x, p[1] + a_off_y) for p in shifted_points], fill=accent)
    
    # 3. Main Bubble Body
    draw.polygon(shifted_points, fill=bg)
    
    # 4. Soft inner gloss highlight
    gloss_mask = Image.new('L', canvas.size, 0)
    gloss_draw = ImageDraw.Draw(gloss_mask)
    gx, gy = cx + ox, cy + oy - int(sh * 0.14)
    grx, gry = int(sw * 0.30), int(sh * 0.14)
    gloss_draw.ellipse([gx - grx, gy - gry, gx + grx, gy + gry], fill=140)
    gloss_draw.rectangle([0, gy + int(gry * 0.1), canvas.width, canvas.height], fill=0)
    gloss_mask = gloss_mask.filter(ImageFilter.GaussianBlur(7 * scale))
    
    white_gloss = Image.new('RGBA', canvas.size, (255, 255, 255, 100))
    canvas.paste(white_gloss, (0, 0), mask=gloss_mask)
    
    # 5. Crisp Outer Outline
    draw = ImageDraw.Draw(canvas)
    draw.line(shifted_points + [shifted_points[0]], fill=stroke, width=5 * scale, joint='curve')
    
    # 6. Cute Sparkles
    def draw_sparkle(sp_cx, sp_cy, size, color):
        s_pts = [
            (sp_cx, sp_cy - size),
            (sp_cx + size * 0.22, sp_cy - size * 0.22),
            (sp_cx + size, sp_cy),
            (sp_cx + size * 0.22, sp_cy + size * 0.22),
            (sp_cx, sp_cy + size),
            (sp_cx - size * 0.22, sp_cy + size * 0.22),
            (sp_cx - size, sp_cy),
            (sp_cx - size * 0.22, sp_cy - size * 0.22),
        ]
        draw.polygon([(p[0] + 2*scale, p[1] + 2*scale) for p in s_pts], fill='#000000')
        draw.polygon(s_pts, fill=color)
        
    if sparkles:
        draw_sparkle(ox + int(sw * 0.12), oy + int(sh * 0.18), 16 * scale, accent)
        draw_sparkle(ox + int(sw * 0.88), oy + int(sh * 0.78), 12 * scale, '#FFFFFF')
        draw_sparkle(ox + int(sw * 0.84), oy + int(sh * 0.18), 11 * scale, accent)
        
    # 7. Typography (centered in bubble body)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Avenir Next.ttc', font_size * scale, index=8)
    except Exception:
        font = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', font_size * scale, index=1)
        
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx + ox - tw // 2 - bbox[0]
    ty = cy + oy - th // 2 - bbox[1]
    
    t_stroke = 4 * scale
    for dx in range(-t_stroke, t_stroke + 1, scale):
        for dy in range(-t_stroke, t_stroke + 1, scale):
            if dx*dx + dy*dy <= t_stroke*t_stroke:
                draw.text((tx + dx, ty + dy), text, font=font, fill=stroke)
                
    draw.text((tx + 3*scale, ty + 4*scale), text, font=font, fill=shadow)
    draw.text((tx, ty), text, font=font, fill=text_c)
    
    downscaled = canvas.resize((canvas.width // scale, canvas.height // scale), Image.Resampling.LANCZOS)
    return downscaled.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

# Pre-render Act 1 comic hype bursts positioned for 1080x1920 (upper-third action band)
# Micro-calibrated to acoustic vocal onsets & offsets
hype_bursts = {
    'grotto': {
        'start': 15.15, 'end': 15.55, 'pos': (530, 480),
        'img': create_comic_burst('...grotto...', bg='#E0F7FA', shadow='#006064', stroke='#000000', text_c='#006064', shape='cloud', angle=-8, w=410, h=190)
    },
    'rarw': {
        'start': 16.65, 'end': 17.00, 'pos': (80, 520),
        'img': create_feminine_burst('Rarw', bg='#FF1493', shadow='#4A0026', accent='#FFD700', stroke='#260014', angle=-8, w=380, h=180, lobes=10, font_size=50)
    },
    'hubba_hubba': {
        'start': 19.30, 'end': 19.85, 'pos': (510, 500),
        'img': create_feminine_burst('hubba hubba', bg='#FF4081', shadow='#6A0032', accent='#FFF0F5', stroke='#300016', angle=7, w=460, h=200, lobes=12, font_size=44)
    },
    'ding_ding': {
        'start': 20.60, 'end': 21.15, 'pos': (90, 520),
        'img': create_feminine_burst('ding ding', bg='#D500F9', shadow='#311B92', accent='#FFD700', stroke='#1A0033', angle=-9, w=400, h=185, lobes=11, font_size=48)
    },
    'rio': {
        'start': 22.35, 'end': 22.95, 'pos': (520, 540),
        'img': create_comic_burst('Rio Grande!', bg='#00E5FF', shadow='#304FFE', stroke='#000000', text_c='#FFFFFF', shape='shock', angle=-12, w=440, h=200)
    },
    'gold': {
        'start': 27.58, 'end': 28.20, 'pos': (80, 520),
        'img': create_comic_burst('Gold, baby!', bg='#FF9100', shadow='#FFEA00', stroke='#000000', text_c='#FFFFFF', shape='flame', angle=8, w=420, h=200)
    },
    'right_now': {
        'start': 30.55, 'end': 30.95, 'pos': (330, 480),
        'img': create_comic_burst('Right now!', bg='#FF1744', shadow='#FFEA00', stroke='#000000', text_c='#FFFFFF', shape='star', angle=-10, w=420, h=190)
    },
    'ride_out': {
        'start': 33.15, 'end': 33.55, 'pos': (80, 540),
        'img': create_comic_burst('Ride out!', bg='#76FF03', shadow='#00B0FF', stroke='#000000', text_c='#000000', shape='star', angle=14, w=400, h=190)
    },
    'louie': {
        'start': 46.50, 'end': 48.35, 'pos': (490, 480),
        'img': create_comic_burst("Talk to 'em Louie", bg='#FFD54F', shadow='#D84315', stroke='#000000', text_c='#000000', shape='cloud', angle=-6, w=490, h=200)
    }
}

# 3. Lyric Karaoke Subtitle Events
lyrics_timeline = [
    {
        'start': 5.04, 'end': 9.46,
        'words': [
            ("Now", 5.04, 5.64), ("I'm", 5.64, 6.00), ("the", 6.00, 6.14),
            ("king", 6.14, 6.64), ("of", 6.64, 7.12), ("the", 7.12, 7.66),
            ("swingers,", 7.66, 8.16), ("oh,", 8.16, 8.48), ("the", 8.48, 8.76),
            ("jungle", 8.76, 9.08), ("VIP!", 9.08, 9.46)
        ]
    },
    {
        'start': 10.98, 'end': 13.80,
        'words': [
            ("Hit", 10.98, 11.58), ("the", 11.58, 11.78), ("throttle,", 11.78, 12.50),
            ("COWBOY", 12.50, 12.94), ("MOTTO", 12.94, 13.80)
        ]
    },
    {
        'start': 13.80, 'end': 16.63,
        'words': [
            ("Limestone", 13.80, 14.40), ("grotto,", 14.40, 15.00),
            ("I'M", 15.00, 15.50), ("SO", 15.50, 15.90),
            ("HOT", 15.90, 16.20), ("THOUGH", 16.20, 16.63)
        ]
    },
    {
        'start': 16.63, 'end': 19.45,
        'words': [
            ("Cold", 16.63, 17.10), ("spring", 17.10, 17.40), ("water,", 17.40, 17.90),
            ("DESPERADO", 17.90, 19.45)
        ]
    },
    {
        'start': 19.45, 'end': 22.28,
        'words': [
            ("Pedernales,", 19.45, 20.30), ("COLORADO", 20.30, 22.28)
        ]
    },
    {
        'start': 22.28, 'end': 25.10,
        'words': [
            ("Outlaw", 22.28, 23.20), ("spirit,", 23.20, 23.80),
            ("BIG", 23.80, 24.30), ("BRAVADO", 24.30, 25.10)
        ]
    },
    {
        'start': 25.10, 'end': 27.93,
        'words': [
            ("Cypress", 25.10, 25.80), ("shadow,", 25.80, 26.50),
            ("EL", 26.50, 27.00), ("DORADO", 27.00, 27.93)
        ]
    },
    {
        'start': 27.93, 'end': 30.50,
        'words': [
            ("Stack", 28.00, 28.35), ("the", 28.35, 28.55), ("paper,", 28.55, 28.85),
            ("GETTIN'", 28.85, 29.40), ("IT", 29.40, 29.65), ("PRONTO", 29.65, 30.40)
        ]
    },
    {
        'start': 30.75, 'end': 33.20,
        'words': [
            ("Eighty-five", 30.75, 31.34), ("beat,", 31.34, 31.62),
            ("LIKE", 31.62, 32.48), ("TONTO", 32.48, 33.20)
        ]
    },
    {
        'start': 33.46, 'end': 35.80,
        'words': [
            ("'Round", 33.46, 33.70), ("here", 33.70, 33.90), ("is", 33.90, 34.08),
            ("outlaw", 34.08, 34.28), ("country,", 34.28, 34.54),
            ("MAKE", 34.54, 34.94), ("NO", 34.94, 35.26), ("MISTAKE", 35.26, 35.80)
        ]
    },
    {
        'start': 35.80, 'end': 38.70,
        'words': [
            ("'Round", 35.80, 36.08), ("here", 36.08, 36.38), ("we", 36.38, 36.62),
            ("don't", 36.62, 36.80), ("call", 36.80, 36.98), ("'em", 36.98, 37.16),
            ("rivers,", 37.16, 37.50), ("WE", 37.50, 37.76), ("CALL", 37.76, 38.06),
            ("'EM", 38.06, 38.30), ("LAKES", 38.30, 38.70)
        ]
    },
    {
        'start': 38.70, 'end': 41.70,
        'words': [
            ("Slow", 38.70, 38.84), ("down", 38.84, 39.18), ("in", 39.18, 39.40),
            ("Pedernales,", 39.40, 40.26), ("HIT", 40.26, 40.62), ("YOUR", 40.62, 40.88),
            ("CEDAR", 40.88, 41.28), ("BREAKS", 41.28, 41.70)
        ]
    },
    {
        'start': 41.50, 'end': 44.10,
        'words': [
            ("We", 41.50, 41.70), ("dammed", 41.70, 41.92), ("up", 41.92, 42.14), ("the", 42.14, 42.26),
            ("Colorado,", 42.26, 42.90), ("JUST", 42.90, 43.38), ("FOR", 43.38, 43.56),
            ("SWIMMIN'", 43.56, 43.80), ("SAKES", 43.80, 44.10)
        ]
    },
    {
        'start': 44.08, 'end': 48.50,
        'words': [
            ("King", 44.30, 44.60), ("of", 44.60, 44.85), ("swing", 44.85, 45.20),
            ("at", 45.20, 45.45), ("Krause", 45.45, 45.85), ("Springs,", 45.85, 46.45),
            ("WHERE", 46.45, 46.85), ("THE", 46.85, 47.15), ("WATER", 47.15, 47.80), ("SHAKES", 47.80, 48.50)
        ]
    },
    {
        'start': 49.00, 'end': 51.68,
        'words': [
            ("Water", 49.00, 49.64), ("so", 49.64, 49.98), ("chilly,", 49.98, 50.40),
            ("Spicewood", 50.40, 51.02), ("villain", 51.02, 51.68)
        ]
    },
    {
        'start': 51.68, 'end': 53.50,
        'words': [
            ("WITH", 51.68, 52.12), ("THE", 52.12, 52.40),
            ("HIGHEST", 52.40, 52.82), ("STAKES!", 52.82, 53.50)
        ]
    }
]

# 4. Modern Glassmorphic Title Badge Generator
def create_title_badge():
    scale = 2
    pw, ph = 480 * scale, 84 * scale
    pill = Image.new('RGBA', (pw, ph), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pill)
    
    # Sleek frosted dark background with delicate warm amber border
    pdraw.rounded_rectangle(
        [(0, 0), (pw, ph)],
        radius=42 * scale,
        fill=(14, 16, 22, 215),
        outline=(245, 158, 11, 90),
        width=2 * scale
    )
    
    # Vinyl record icon circle on left
    icx, icy = 46 * scale, ph // 2
    r_outer = 24 * scale
    pdraw.ellipse([(icx - r_outer, icy - r_outer), (icx + r_outer, icy + r_outer)], fill=(24, 26, 32, 255), outline=(245, 158, 11, 160), width=2*scale)
    # Inner grooves
    pdraw.ellipse([(icx - 16*scale, icy - 16*scale), (icx + 16*scale, icy + 16*scale)], outline=(255, 255, 255, 50), width=1*scale)
    pdraw.ellipse([(icx - 9*scale, icy - 9*scale), (icx + 9*scale, icy + 9*scale)], outline=(255, 255, 255, 40), width=1*scale)
    # Center gold label dot
    pdraw.ellipse([(icx - 5*scale, icy - 5*scale), (icx + 5*scale, icy + 5*scale)], fill=(245, 158, 11, 255))
    
    f_title = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 21 * scale, index=1)
    f_sub = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', 13 * scale, index=1)
    
    # Text
    pdraw.text((86 * scale, 18 * scale), 'SPICEWOOD OUTLAWS', font=f_title, fill=(255, 255, 255, 255))
    pdraw.text((86 * scale, 48 * scale), 'VIFI  •  BEAT: "SOCIETY" BY SHINRA B', font=f_sub, fill=(245, 158, 11, 230))
    
    return pill.resize((pw // scale, ph // scale), Image.Resampling.LANCZOS)

title_badge_img = create_title_badge()
TITLE_START = 1.00
TITLE_FADE_IN = 1.40
TITLE_FADE_OUT = 4.60
TITLE_END = 5.00

# Generate discrete time boundaries
time_points = {0.0, 55.56, TITLE_START, TITLE_FADE_IN, TITLE_FADE_OUT, TITLE_END}
for ft in [1.10, 1.20, 1.30, 4.70, 4.80, 4.90]:
    time_points.add(ft)
for p in lyrics_timeline:
    time_points.add(p['start'])
    time_points.add(p['end'])
    for w in p['words']:
        time_points.add(w[1])
        time_points.add(w[2])

for h in hype_bursts.values():
    time_points.add(h['start'])
    time_points.add(h['end'])

sorted_times = sorted([t for t in time_points if 0.0 <= t <= 55.56])

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
        
    if TITLE_START <= t_start < TITLE_END:
        if t_start < TITLE_FADE_IN:
            alpha = (t_start - TITLE_START) / (TITLE_FADE_IN - TITLE_START)
        elif t_start >= TITLE_FADE_OUT:
            alpha = (TITLE_END - t_start) / (TITLE_END - TITLE_FADE_OUT)
        else:
            alpha = 1.0
        alpha = max(0.0, min(1.0, alpha))
        if alpha > 0.02:
            badge_copy = title_badge_img.copy()
            r, g, b, a = badge_copy.split()
            a = a.point(lambda p: int(p * alpha))
            badge_copy.putalpha(a)
            badge_x = (1080 - title_badge_img.width) // 2
            frame.alpha_composite(badge_copy, dest=(badge_x, 180))
        
    png_path = os.path.join(work_dir, f'ovl_{i:04d}.png')
    frame.save(png_path)
    plan_lines.append(f"file '{png_path}'\nduration {dur:.3f}\n")

if plan_lines:
    plan_lines.append(plan_lines[-1].split('\n')[0] + '\n')

with open(plan_file, 'w') as f:
    f.writelines(plan_lines)

print('Compositing Act 1 vertical master with 24-bit audio & karaoke overlay...')
t1 = time.time()

needle_sfx = '/Users/jaketrigg/Projects/VoiceFi/assets/audio/sfx/needle_drop/NeedleDrop02.mp3'
audio_raw = os.path.join(work_dir, 'act1_audio_raw.wav')
subprocess.run([
    'ffmpeg', '-y',
    '-ss', '0.0', '-t', '55.56',
    '-i', audio_master,
    '-i', needle_sfx,
    '-filter_complex', '[1:a]aresample=44100,volume=0.88,adelay=2100|2100,afade=t=out:st=5.0:d=1.0[sfx];[0:a][sfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]',
    '-map', '[a]',
    '-c:a', 'pcm_s24le',
    audio_raw
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

final_cmd = [
    'ffmpeg', '-y',
    '-i', base_video,
    '-f', 'concat', '-safe', '0', '-i', plan_file,
    '-i', audio_raw,
    '-filter_complex', '[0:v][1:v]overlay=0:0[v]',
    '-map', '[v]',
    '-map', '2:a',
    '-map_chapters', '-1',
    '-t', '55.56',
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '18',
    '-pix_fmt', 'yuv420p',
    '-g', '24',
    '-keyint_min', '12',
    '-avoid_negative_ts', 'make_zero',
    '-movflags', '+faststart',
    '-c:a', 'aac',
    '-b:a', '320k',
    output_mp4
]
res = subprocess.run(final_cmd, capture_output=True, text=True)
if res.returncode != 0:
    print('Final vertical render error:', res.stderr)
    exit(1)

print(f'Rendered Act 1 Vertical successfully: {output_mp4} ({time.time()-t1:.1f}s)')
