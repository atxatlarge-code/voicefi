#!/usr/bin/env python3
import os
import subprocess
import time

act1 = '/Users/jaketrigg/Desktop/spicewood_act1.mp4'
act2 = '/Users/jaketrigg/Desktop/spicewood_act2.mp4'
act3 = '/Users/jaketrigg/Desktop/spicewood_act3.mp4'
master_out = '/Users/jaketrigg/Desktop/spicewood_outlaws_full_master.mp4'
work_dir = '/tmp/spicewood_master_work'
os.makedirs(work_dir, exist_ok=True)

for p in [act1, act2, act3]:
    if not os.path.exists(p):
        print(f'Error: Missing {p}. Run individual assemble_act scripts first.')
        exit(1)

concat_txt = os.path.join(work_dir, 'master_concat.txt')
with open(concat_txt, 'w') as f:
    f.write(f"file '{act1}'\n")
    f.write(f"file '{act2}'\n")
    f.write(f"file '{act3}'\n")

raw_master = os.path.join(work_dir, 'raw_master.mp4')
print('Concatenating Acts 1, 2, and 3 losslessly (-c copy)...')
t0 = time.time()
cmd1 = [
    'ffmpeg', '-y',
    '-f', 'concat', '-safe', '0',
    '-i', concat_txt,
    '-c', 'copy',
    raw_master
]
res1 = subprocess.run(cmd1, capture_output=True, text=True)
if res1.returncode != 0:
    print('Master concat error:', res1.stderr)
    exit(1)

# Normalizing stream start time to 0.000000s so QuickTime/Finder displays the video frame immediately
# instead of a 23ms black gap caused by AAC priming delay in container edit lists
cmd2 = [
    'ffmpeg', '-y',
    '-ss', '0.023193',
    '-i', raw_master,
    '-c', 'copy',
    '-movflags', '+faststart',
    master_out
]
res2 = subprocess.run(cmd2, capture_output=True, text=True)
if res2.returncode != 0:
    print('Master remux error:', res2.stderr)
    exit(1)

print(f'Master video created: {master_out} ({time.time()-t0:.2f}s)')
print('Launching Master in QuickTime Player...')
subprocess.run(['open', '-a', 'QuickTime Player', master_out])
