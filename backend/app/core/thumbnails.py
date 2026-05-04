import os
from PIL import Image, ImageOps
from app.utils import THUMB_DIR, THUMB_W, THUMB_H, get_video_meta

def generate_thumbnail(db_file) -> bool:
    """Pre-generate a WebP thumbnail for a file if it doesn't exist."""
    thumb_path = os.path.join(THUMB_DIR, f"{db_file.id}.webp")
    if os.path.exists(thumb_path):
        return True

    if not os.path.exists(db_file.path):
        return False

    try:
        ext = os.path.splitext(db_file.path)[1].lower()
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
        
        if ext in video_exts:
            try:
                import cv2
                cap = cv2.VideoCapture(db_file.path)
                
                # Use ffprobe to check for mirroring/rotation that OpenCV might miss
                _, mirror = get_video_meta(db_file.path)

                # Seek to ~1 second in
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                    ret, frame = cap.read()
                cap.release()
                if not ret:
                    return False
                
                # Convert BGR -> RGB then to PIL
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                
                if mirror:
                    img = ImageOps.mirror(img)

            except Exception as ve:
                print(f"[thumbnail-gen] Video frame extract failed for {db_file.path}: {ve}")
                return False
        else:
            img = Image.open(db_file.path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")

        # Cover-crop to exact card dimensions
        from PIL import ImageOps as _io
        img = _io.fit(img, (THUMB_W, THUMB_H), method=Image.LANCZOS)
        img.save(thumb_path, "WEBP", quality=82, method=4)
        return True
    except Exception as e:
        print(f"[thumbnail-gen] Failed for {db_file.path}: {e}")
        return False
