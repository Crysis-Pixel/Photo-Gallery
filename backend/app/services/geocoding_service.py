"""
Offline reverse geocoding service.
Converts GPS coordinates to human-readable place names using the
reverse_geocoder library (no internet / API key required).

Falls back gracefully if the library is not installed.
"""
from typing import Optional
import threading

_lock = threading.Lock()
_rg = None          # lazy-loaded reverse_geocoder module
_available = None   # None = not checked yet, True/False after first check


def _load_rg():
    """Lazily load reverse_geocoder and cache availability."""
    global _rg, _available
    with _lock:
        if _available is None:
            try:
                import reverse_geocoder as rg
                _rg = rg
                _available = True
            except ImportError:
                _available = False
    return _available


# In-memory cache: (lat_rounded, lon_rounded) -> place_string
_cache: dict = {}
_PRECISION = 2  # round to 2 decimal places (~1 km grid)


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Return a human-readable location string for the given coordinates.
    Examples: "Cox's Bazar, BD", "Dhaka, BD", "London, GB"
    Returns None if the library is not available or lookup fails.
    """
    if lat is None or lon is None:
        return None

    if not _load_rg():
        return None

    key = (round(lat, _PRECISION), round(lon, _PRECISION))
    if key in _cache:
        return _cache[key]

    try:
        results = _rg.search([(lat, lon)], mode=1, verbose=False)
        if results:
            r = results[0]
            name = r.get("name", "")
            country_code = r.get("cc", "")
            place = f"{name}, {country_code}" if name and country_code else name or None
            _cache[key] = place
            return place
    except Exception:
        pass

    _cache[key] = None
    return None
