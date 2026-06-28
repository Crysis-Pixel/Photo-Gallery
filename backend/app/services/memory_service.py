"""
Memory generation service.
Auto-generates Memory records by clustering files by location + time range,
and creates album-based memories from folder names.
"""
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models import File, Memory


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Approximate distance in km between two GPS coordinates."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _album_from_path(path: str) -> Optional[str]:
    """Extract the album/folder name from a file path."""
    try:
        parts = re.split(r'[\\/]', path)
        if len(parts) >= 2:
            return parts[-2]
    except Exception:
        pass
    return None


def _format_date_range(start: datetime, end: datetime) -> str:
    """Format a date range as a human-readable string."""
    if start.year == end.year:
        if start.month == end.month:
            if start.day == end.day:
                return start.strftime("%b %d, %Y")
            return f"{start.strftime('%b %d')}–{end.strftime('%d, %Y')}"
        return f"{start.strftime('%b %d')}–{end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


def _pick_cover(files: list) -> Optional[int]:
    """Pick the best cover photo from a list of File objects (first image with GPS)."""
    for f in files:
        if f.gps_latitude is not None:
            ext = os.path.splitext(f.path)[1].lower()
            if ext not in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
                return f.id
    # Fall back to first image
    for f in files:
        ext = os.path.splitext(f.path)[1].lower()
        if ext not in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
            return f.id
    return files[0].id if files else None

def _pick_previews(files: list, limit: int = 5) -> Optional[str]:
    """Pick up to `limit` preview photos (comma-separated IDs) for animation."""
    previews = []
    for f in files:
        ext = os.path.splitext(f.path)[1].lower()
        if ext not in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
            previews.append(str(f.id))
            if len(previews) >= limit:
                break
    return ",".join(previews) if previews else None


# ── Main generation function ───────────────────────────────────────────────────

def generate_memories(db: Session) -> dict:
    """
    Generate or refresh Memory records based on current file metadata.
    Returns a summary dict.
    """
    # Clear existing memories and regenerate fresh
    db.query(Memory).delete()
    db.commit()

    memories_created = 0

    # ── Strategy 1: Location + Time clusters ──────────────────────────────────
    # Group files that have GPS data into location clusters, then split by date
    gps_files = (
        db.query(File)
        .filter(
            File.gps_latitude.isnot(None),
            File.gps_longitude.isnot(None),
        )
        .order_by(File.date_taken.asc().nullslast())
        .all()
    )

    location_clusters = _cluster_by_location(gps_files, radius_km=15.0)

    for cluster_files in location_clusters:
        # Split cluster by time gaps > 2 days
        time_groups = _split_by_time_gap(cluster_files, gap_days=2)
        for group in time_groups:
            if len(group) < 2:
                continue  # Skip singletons

            # Determine location name from the most common location_name in the group
            location_name = _most_common_location(group)

            # Compute centroid
            lats = [f.gps_latitude for f in group if f.gps_latitude]
            lons = [f.gps_longitude for f in group if f.gps_longitude]
            centroid_lat = sum(lats) / len(lats) if lats else None
            centroid_lon = sum(lons) / len(lons) if lons else None

            # Date range
            dates = [f.date_taken for f in group if f.date_taken]
            start_date = min(dates) if dates else None
            end_date = max(dates) if dates else None

            title = location_name or _album_from_path(group[0].path) or "Memory"
            subtitle = _format_date_range(start_date, end_date) if start_date and end_date else None
            cover_id = _pick_cover(group)
            preview_ids = _pick_previews(group)

            mem = Memory(
                title=title,
                subtitle=subtitle,
                memory_type="location",
                location_name=location_name,
                latitude=centroid_lat,
                longitude=centroid_lon,
                start_date=start_date,
                end_date=end_date,
                cover_file_id=cover_id,
                preview_ids=preview_ids,
                photo_count=len(group),
            )
            db.add(mem)
            memories_created += 1

    db.commit()

    # ── Strategy 2: Album-based memories (for folders without GPS) ────────────
    all_files = db.query(File).all()
    album_map: dict = {}
    for f in all_files:
        album = _album_from_path(f.path)
        if album:
            album_map.setdefault(album, []).append(f)

    # Find albums that don't already have a location-based memory
    # (i.e. most files in this album have no GPS, or the album is unique enough)
    existing_location_memories = set()
    for mem in db.query(Memory).filter(Memory.memory_type == "location").all():
        if mem.location_name:
            existing_location_memories.add(mem.location_name.lower())

    for album_name, album_files in album_map.items():
        if len(album_files) < 2:
            continue

        # Check if this album is covered by an existing location memory
        # (simple heuristic: if album name is a substring of any location memory title)
        album_lower = album_name.lower()
        already_covered = any(
            album_lower in loc or loc in album_lower
            for loc in existing_location_memories
        )
        if already_covered:
            continue

        # Check if most files already have GPS (covered by location clustering above)
        gps_count = sum(1 for f in album_files if f.gps_latitude is not None)
        if gps_count > len(album_files) * 0.5:
            continue  # Mostly covered by location memory

        dates = [f.date_taken for f in album_files if f.date_taken]
        start_date = min(dates) if dates else None
        end_date = max(dates) if dates else None
        subtitle = _format_date_range(start_date, end_date) if start_date and end_date else None
        cover_id = _pick_cover(album_files)
        preview_ids = _pick_previews(album_files)

        mem = Memory(
            title=album_name,
            subtitle=subtitle,
            memory_type="album",
            album_name=album_name,
            start_date=start_date,
            end_date=end_date,
            cover_file_id=cover_id,
            preview_ids=preview_ids,
            photo_count=len(album_files),
        )
        db.add(mem)
        memories_created += 1

    db.commit()

    return {"memories_created": memories_created}


# ── Clustering helpers ─────────────────────────────────────────────────────────

def _cluster_by_location(files: list, radius_km: float = 15.0) -> list:
    """
    Greedy clustering: assign each file to the first cluster whose centroid
    is within `radius_km`. Returns list of lists of File objects.
    """
    clusters: list = []      # list of {"centroid": (lat, lon), "files": [...]}

    for f in files:
        if f.gps_latitude is None or f.gps_longitude is None:
            continue
        assigned = False
        for c in clusters:
            clat, clon = c["centroid"]
            if _haversine_km(f.gps_latitude, f.gps_longitude, clat, clon) <= radius_km:
                c["files"].append(f)
                # Update centroid
                all_files = c["files"]
                c["centroid"] = (
                    sum(x.gps_latitude for x in all_files if x.gps_latitude) / len(all_files),
                    sum(x.gps_longitude for x in all_files if x.gps_longitude) / len(all_files),
                )
                assigned = True
                break
        if not assigned:
            clusters.append({"centroid": (f.gps_latitude, f.gps_longitude), "files": [f]})

    return [c["files"] for c in clusters]


def _split_by_time_gap(files: list, gap_days: int = 2) -> list:
    """
    Split a list of files into sub-groups wherever there is a time gap
    larger than `gap_days` between consecutive date_taken values.
    Files without dates are included in the previous group or a catch-all.
    """
    # Sort by date_taken (None last)
    dated = sorted([f for f in files if f.date_taken], key=lambda f: f.date_taken)
    undated = [f for f in files if not f.date_taken]

    if not dated:
        return [undated] if undated else []

    groups = []
    current_group = [dated[0]]
    for i in range(1, len(dated)):
        delta = dated[i].date_taken - dated[i - 1].date_taken
        if delta > timedelta(days=gap_days):
            groups.append(current_group)
            current_group = []
        current_group.append(dated[i])

    groups.append(current_group)

    # Append undated files to the last group
    if undated:
        if groups:
            groups[-1].extend(undated)
        else:
            groups.append(undated)

    return groups


def _most_common_location(files: list) -> Optional[str]:
    """Return the most common non-None location_name among a list of files."""
    from collections import Counter
    names = [f.location_name for f in files if f.location_name]
    if not names:
        return None
    counter = Counter(names)
    return counter.most_common(1)[0][0]
