import random
import colorsys
import os
from typing import Optional

# Thumbnail settings
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORKSPACE_ROOT = PROJECT_ROOT
THUMB_DIR = os.path.join(PROJECT_ROOT, 'data', 'thumbnails')
THUMB_W = 480
THUMB_H = 408

os.makedirs(THUMB_DIR, exist_ok=True)

def generate_random_color() -> str:
    # Use hsv_to_rgb for more visually pleasing vibrant random colors
    h = random.random()
    # Avoid too much saturation or too little brightness
    s = random.uniform(0.6, 0.8)
    v = random.uniform(0.7, 0.9)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))

def get_default_person_color(person_id: Optional[int] = None) -> str:
    """Fallback color if a person record doesn't have one assigned."""
    if person_id is None:
        return "#e8d5b0" # Match project accent
        
    # Deterministic but non-global random color based on ID
    rng = random.Random(person_id)
    h = rng.random()
    s = rng.uniform(0.6, 0.8)
    v = rng.uniform(0.7, 0.9)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))

def get_video_meta(path: str):
    """Use ffprobe to detect rotation and mirroring metadata."""
    import subprocess
    import json
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 
        'stream=index:stream_side_data_list:stream_tags=rotate', 
        '-of', 'json', path
    ]
    try:
        res = subprocess.check_output(cmd)
        data = json.loads(res)
        rotation = 0
        mirror = False
        
        for stream in data.get('streams', []):
            # Check tags
            tags = stream.get('tags', {})
            if 'rotate' in tags:
                rotation = int(tags['rotate'])
            
            # Check side data for matrix
            for sd in stream.get('side_data_list', []):
                if sd.get('side_data_type') == 'Display Matrix':
                    rotation = sd.get('rotation', rotation)
                    matrix = sd.get('displaymatrix', '')
                    # Check for horizontal mirroring (negative scale in matrix)
                    if '-' in matrix.split(':')[1].split()[0]:
                        mirror = True
        return rotation, mirror
    except Exception:
        return 0, False
