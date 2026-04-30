import random
import colorsys
import os
from typing import Optional

# Thumbnail settings
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
THUMB_DIR = os.path.join(PROJECT_ROOT, 'data', 'thumbnails')
THUMB_W = 400
THUMB_H = 340

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
