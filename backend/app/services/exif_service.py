"""
EXIF metadata extraction service.
Extracts date, GPS, and camera information from image files using Pillow.
"""
import os
from typing import Optional
from datetime import datetime


def _dms_to_decimal(dms_tuple, ref: str) -> Optional[float]:
    """Convert GPS DMS tuple (degrees, minutes, seconds) to decimal degrees."""
    try:
        degrees = float(dms_tuple[0])
        minutes = float(dms_tuple[1])
        seconds = float(dms_tuple[2])
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ('S', 'W'):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def extract_exif_metadata(file_path: str) -> dict:
    """
    Extract EXIF metadata from an image file.
    
    Returns a dict with keys:
        date_taken      - datetime | None
        gps_latitude    - float | None  (decimal degrees, negative = S)
        gps_longitude   - float | None  (decimal degrees, negative = W)
        gps_altitude    - float | None  (meters)
        camera_make     - str | None
        camera_model    - str | None
    """
    result = {
        "date_taken": None,
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_altitude": None,
        "camera_make": None,
        "camera_model": None,
    }

    ext = os.path.splitext(file_path)[1].lower()
    # Only process image files (not videos)
    if ext not in {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.webp', '.bmp'}:
        return result

    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS, IFD

        img = Image.open(file_path)
        exif = img.getexif()
        if not exif:
            return result

        # ── Basic IFD ──────────────────────────────────────────────────────────
        tag_map = {TAGS.get(k, k): v for k, v in exif.items()}

        result["camera_make"] = tag_map.get("Make")
        result["camera_model"] = tag_map.get("Model")

        # ── Exif IFD (DateTimeOriginal) ────────────────────────────────────────
        try:
            ifd_exif = exif.get_ifd(IFD.Exif)
            exif_tag_map = {TAGS.get(k, k): v for k, v in ifd_exif.items()}
            date_str = exif_tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
            if date_str:
                result["date_taken"] = datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass

        # ── GPS IFD ────────────────────────────────────────────────────────────
        try:
            ifd_gps = exif.get_ifd(IFD.GPSInfo)
            gps_map = {GPSTAGS.get(k, k): v for k, v in ifd_gps.items()}

            lat_dms = gps_map.get("GPSLatitude")
            lat_ref = gps_map.get("GPSLatitudeRef", "N")
            lon_dms = gps_map.get("GPSLongitude")
            lon_ref = gps_map.get("GPSLongitudeRef", "E")
            alt_raw = gps_map.get("GPSAltitude")

            if lat_dms and lon_dms:
                result["gps_latitude"] = _dms_to_decimal(lat_dms, lat_ref)
                result["gps_longitude"] = _dms_to_decimal(lon_dms, lon_ref)

            if alt_raw is not None:
                result["gps_altitude"] = float(alt_raw)

        except Exception:
            pass

    except Exception as e:
        # Silently ignore corrupt or unsupported files
        pass

    return result
